"""Command dispatchers — one function per Poppet wire command.

Runs inside Cascadeur's embedded Python 3.8 on the Qt main thread (under
process_pending.run). Mutations wrap in `scene.modify(...)` or
`scene.modify_with_session(...)` for undo safety, matching the pattern used
by Cascadeur's own bundled commands.

The `scene` parameter is a `csc.domain.Scene` (NOT `csc.view.Scene`) — same as
Cascadeur passes to every command's run(). So `scene.selector()`,
`scene.model_viewer()`, `scene.layers_viewer()`, `scene.modify_with_session(...)`
all work directly.

The patterns here are derived from Cascadeur's own bundled commands in
resources/scripts/python/commands/ — see change_namespace.py, restore_values.py,
common/selection_operations.py, common/layers_operation.py.
"""

import os
import time
import traceback


def dispatch(message, scene):
    """Route a single request to its handler and wrap the response."""
    cmd_type = message.get("type")
    params = message.get("params") or {}
    handler = _HANDLERS.get(cmd_type)
    if handler is None:
        return {"status": "error", "message": f"unknown command: {cmd_type!r}"}
    try:
        result = handler(params, scene)
        return {"status": "success", "result": result}
    except Exception as e:
        return {
            "status": "error",
            "message": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }


# ============================================================================
# Helpers (csc utilities adapted from common/selection_operations.py)
# ============================================================================


def _safe_repr(obj):
    try:
        r = repr(obj)
        return r if len(r) <= 500 else r[:500] + "..."
    except Exception:
        return "<unrepresentable>"


def _id_str(obj_id):
    """Compact string form of a csc.model.ObjectId for transport."""
    try:
        return str(obj_id)
    except Exception:
        return repr(obj_id)


def _selected_obj_ids(scene):
    """Return list of selected csc.model.ObjectId values (filter out non-objects)."""
    import csc

    sel = scene.selector().selected()
    return [sid for sid in sel.ids if isinstance(sid, csc.model.ObjectId)]


def _all_object_ids(scene):
    return list(scene.model_viewer().get_objects())


def _object_name(scene, obj_id):
    try:
        return scene.model_viewer().get_object_name(obj_id)
    except Exception:
        return None


def _find_obj_by_name(scene, name):
    """Return first ObjectId whose name matches, or None."""
    mv = scene.model_viewer()
    for oid in mv.get_objects():
        try:
            if mv.get_object_name(oid) == name:
                return oid
        except Exception:
            continue
    return None


# ============================================================================
# Core
# ============================================================================


def _d_echo(params, scene):
    return params


def _d_exec_csc(params, scene):
    """Run arbitrary Python in Cascadeur's interpreter. Escape hatch."""
    code = params.get("code", "")
    if not isinstance(code, str):
        raise ValueError("'code' must be a string")
    import csc

    ns = {"csc": csc, "scene": scene, "_result": None}
    try:
        ns["_result"] = eval(code, ns)
    except SyntaxError:
        exec(code, ns)
    return {"repr": _safe_repr(ns.get("_result"))}


def _d_call_action(params, scene):
    """Invoke a Cascadeur action by ID. Fire-and-forget."""
    import csc

    action_id = params.get("action_id")
    if not isinstance(action_id, str):
        raise ValueError("'action_id' must be a string")
    app = csc.app.get_application()
    am = app.get_action_manager()
    am.call_action(action_id)
    return {"action_id": action_id, "invoked": True}


def _d_scene_info(params, scene):
    """Return scene metadata using the real csc.domain.Scene API surface."""
    import csc

    info = {"has_scene": True}
    try:
        info["current_frame"] = scene.get_current_frame()
    except Exception as e:
        info["current_frame_error"] = str(e)

    try:
        info["object_count"] = len(scene.model_viewer().get_objects())
    except Exception as e:
        info["object_count_error"] = str(e)

    try:
        info["layer_count"] = len(list(scene.layers_viewer().all_layer_ids()))
    except Exception as e:
        info["layer_count_error"] = str(e)

    try:
        info["selection_count"] = len(_selected_obj_ids(scene))
    except Exception as e:
        info["selection_count_error"] = str(e)

    # View-scene name + animation_boundary live on csc.view.Scene, not domain scene.
    try:
        view_scene = csc.app.get_application().current_scene()
        info["scene_name"] = view_scene.name()
    except Exception as e:
        info["scene_name_error"] = str(e)

    return info


# ============================================================================
# Selection
# ============================================================================


def _d_selection_get(params, scene):
    """List selected objects with name + id."""
    out = []
    for oid in _selected_obj_ids(scene):
        out.append({"id": _id_str(oid), "name": _object_name(scene, oid)})
    return {"selected": out, "count": len(out)}


def _d_selection_set(params, scene):
    """Replace selection by object name list. Uses modify_with_session for undo."""
    import csc

    names = params.get("object_names", [])
    if not isinstance(names, list):
        raise ValueError("'object_names' must be a list")

    resolved = []
    missing = []
    for n in names:
        oid = _find_obj_by_name(scene, n)
        if oid is None:
            missing.append(n)
        else:
            resolved.append(oid)

    focus = resolved[0] if resolved else csc.model.ObjectId.null()

    def mod(model, update, sc, session):
        session.take_selector().select(set(resolved), focus)

    scene.modify_with_session("Poppet: set selection", mod)
    return {
        "requested": names,
        "resolved_count": len(resolved),
        "missing": missing,
    }


def _d_selection_clear(params, scene):
    """Clear the selection."""
    import csc

    def mod(model, update, sc, session):
        session.take_selector().select(set(), csc.model.ObjectId.null())

    scene.modify_with_session("Poppet: clear selection", mod)
    return {"cleared": True}


def _d_objects_list(params, scene):
    """List all objects in scene (id + name + type). Honors optional name_contains filter."""
    name_contains = params.get("name_contains")
    out = []
    mv = scene.model_viewer()
    for oid in mv.get_objects():
        try:
            name = mv.get_object_name(oid)
        except Exception:
            name = None
        if name_contains and (name is None or name_contains not in name):
            continue
        try:
            type_name = mv.get_object_type_name(oid)
        except Exception:
            type_name = None
        out.append({"id": _id_str(oid), "name": name, "type": type_name})
    return {"objects": out, "count": len(out)}


# ============================================================================
# Layers / keyframes
# ============================================================================


def _d_layers_list(params, scene):
    """List animation layers — id + obj count + key count summary."""
    lv = scene.layers_viewer()
    layers = []
    try:
        layer_ids = list(lv.all_layer_ids())
    except Exception as e:
        return {"layers": [], "error": f"all_layer_ids() failed: {e}"}

    for lid in layer_ids:
        info = {"id": _id_str(lid)}
        try:
            layer = lv.layer(lid)
            try:
                # header is a property (csc.layers.Header); .name is a str property
                h = layer.header
                n = getattr(h, "name", None)
                if n is not None:
                    info["name"] = str(n)
            except Exception:
                pass
            try:
                info["obj_id_count"] = len(list(layer.obj_ids()))
            except Exception:
                pass
            try:
                info["key_frame_count"] = len(list(layer.key_frame_indices()))
            except Exception:
                pass
            try:
                info["is_visible"] = layer.is_visible()
            except Exception:
                pass
            try:
                info["is_locked"] = layer.is_locked()
            except Exception:
                pass
        except Exception as e:
            info["error"] = str(e)
        layers.append(info)
    return {
        "layers": layers,
        "count": len(layers),
        "frames_count": _safe_call(lambda: lv.frames_count()),
    }


def _d_keyframes_get(params, scene):
    """Get keyframe frame indices for a single layer."""
    layer_id_str = params.get("layer_id")
    frame_start = int(params.get("frame_start", -1))
    frame_end = int(params.get("frame_end", -1))

    lv = scene.layers_viewer()
    # We don't have a clean str->LayerId reverse — caller must pass an id we can find.
    # Strategy: enumerate layer ids, match by stringified id.
    target = None
    for lid in lv.all_layer_ids():
        if _id_str(lid) == layer_id_str:
            target = lid
            break
    if target is None:
        raise ValueError(f"layer_id not found: {layer_id_str!r}")

    layer = lv.layer(target)
    indices = list(layer.key_frame_indices())
    if frame_start >= 0 and frame_end >= 0:
        indices = [f for f in indices if frame_start <= f <= frame_end]
    return {
        "layer_id": layer_id_str,
        "key_frame_indices": indices,
        "count": len(indices),
    }


def _d_keyframe_set(params, scene):
    """Set a controller's position or rotation at a frame.

    Implementation derived from go_to_origin.py (scene.modify_update +
    update.get_object_by_id(obj_id).root_group().node_deep("Position")
    .set_value(val, frame) + scene_updater.run_update(actuals, frame)).

    Params:
      controller_id: str (object name OR uuid string)
      frame: int
      position: [x, y, z]  (optional — sets "Position" or "Local Position")
      rotation_quat: [qx, qy, qz, qw]  (optional — sets "Rotation" or "Local Rotation")
      local: bool (default True — use "Local Position"/"Local Rotation" instead of world)
    """
    import csc

    controller = params.get("controller_id")
    frame = int(params["frame"])
    position = params.get("position")
    rotation_quat = params.get("rotation_quat")
    use_local = params.get("local", True)

    if not controller:
        raise ValueError("controller_id is required")
    if position is None and rotation_quat is None:
        raise ValueError("at least one of position / rotation_quat is required")

    # Resolve controller name -> ObjectId. Allow either name or stringified id.
    obj_id = _find_obj_by_name(scene, controller)
    if obj_id is None:
        # Try matching by id string.
        mv = scene.model_viewer()
        for oid in mv.get_objects():
            if _id_str(oid) == controller:
                obj_id = oid
                break
    if obj_id is None:
        raise ValueError(f"controller not found by name or id: {controller!r}")

    pos_node_name = "Local Position" if use_local else "Position"
    rot_node_name = "Local Rotation" if use_local else "Rotation"

    # Step 1: Extend animation data to include the target frame.
    # This must happen in a modify_with_session context — mixing layers_editor
    # operations inside modify_update corrupts the data buffers.
    # set_fixed_interpolation_or_key_if_need creates a layer keyframe AND extends
    # the per-attribute data arrays to cover the target frame.
    _ext_err = {"value": None}

    def _extend_mod(model, update, sc, session):
        try:
            le = model.layers_editor()
            for _lid in list(scene.layers_viewer().all_layer_ids()):
                try:
                    le.set_fixed_interpolation_or_key_if_need(_lid, frame, True)
                except Exception:
                    pass
        except Exception as e:
            _ext_err["value"] = str(e)

    scene.modify_with_session("Poppet: extend animation for keyframe", _extend_mod)

    actuals_acc = []
    applied = {"position": False, "rotation": False, "frame": frame}
    if _ext_err["value"]:
        applied["extend_warning"] = _ext_err["value"]

    def mod(model, update, scene_updater):
        actuals = set()
        try:
            node = update.get_object_by_id(obj_id).root_group()
        except Exception as e:
            applied["error"] = f"get_object_by_id failed: {e}"
            return

        if position is not None:
            try:
                pos_attr = node.node_deep(pos_node_name)
                if pos_attr is None:
                    applied["position_error"] = f"node {pos_node_name!r} not on {controller!r}"
                else:
                    try:
                        current = pos_attr.value(frame)
                    except Exception:
                        current = None
                    if current is not None:
                        # Type-preserving: delta from current keeps Vec3-like type.
                        delta = [
                            float(position[0]) - float(current[0]),
                            float(position[1]) - float(current[1]),
                            float(position[2]) - float(current[2]),
                        ]
                        new_pos = current + delta
                    else:
                        new_pos = [float(position[0]), float(position[1]), float(position[2])]
                    pos_attr.set_value(new_pos, frame)
                    actuals.add(pos_attr.data_id())
                    applied["position"] = True
                    applied["position_new"] = _vec_to_list(new_pos)
            except Exception as e:
                applied["position_error"] = f"{type(e).__name__}: {e}"

        if rotation_quat is not None:
            try:
                rot_attr = node.node_deep(rot_node_name)
                if rot_attr is None:
                    applied["rotation_error"] = f"node {rot_node_name!r} not on {controller!r}"
                else:
                    qx, qy, qz, qw = (float(x) for x in rotation_quat)
                    euler = _quat_to_euler_xyz(qx, qy, qz, qw)
                    rot_val = csc.math.Rotation.from_euler(euler)
                    rot_attr.set_value(rot_val, frame)
                    actuals.add(rot_attr.data_id())
                    applied["rotation"] = True
            except Exception as e:
                applied["rotation_error"] = f"{type(e).__name__}: {e}"

        actuals_acc.extend(actuals)
        if actuals:
            try:
                scene_updater.run_update(actuals, frame)
            except Exception as e:
                applied["run_update_error"] = f"{type(e).__name__}: {e}"

    scene.modify_update("Poppet: set keyframe", mod)
    return {
        "controller": controller,
        "obj_id": _id_str(obj_id),
        "applied": applied,
        "attrs_updated": len(actuals_acc),
    }


# ============================================================================
# AutoPosing / AutoPhysics
# ============================================================================


def _d_autopose_run(params, scene):
    """Wrap AutoPosingTool.AutoPosing action."""
    import csc

    app = csc.app.get_application()
    am = app.get_action_manager()
    am.call_action("AutoPosingTool.AutoPosing")
    return {"invoked": "AutoPosingTool.AutoPosing"}


def _d_autophysics_run(params, scene):
    """Wrap AutoPhysicsTool.Snap to Auto Physics with convergence polling.

    Since call_action returns no completion signal, poll a coarse scene-state
    fingerprint until it stops changing or timeout fires.
    """
    import csc

    timeout_sec = float(params.get("timeout_sec", 30.0))
    poll_interval = float(params.get("poll_interval", 0.25))

    app = csc.app.get_application()
    am = app.get_action_manager()
    am.call_action("AutoPhysicsTool.Snap to Auto Physics")

    deadline = time.time() + timeout_sec
    last_fp = _scene_state_fingerprint(scene)
    stable_for = 0.0
    while time.time() < deadline:
        time.sleep(poll_interval)
        fp = _scene_state_fingerprint(scene)
        if fp == last_fp:
            stable_for += poll_interval
            if stable_for >= 0.5:
                return {
                    "invoked": "AutoPhysicsTool.Snap to Auto Physics",
                    "converged": True,
                }
        else:
            stable_for = 0.0
            last_fp = fp
    return {
        "invoked": "AutoPhysicsTool.Snap to Auto Physics",
        "converged": False,
        "status": "timeout",
    }


def _scene_state_fingerprint(scene):
    """Coarse fingerprint of scene state for convergence detection."""
    try:
        lv = scene.layers_viewer()
        # Sum all key frame counts as a coarse signal — changes when keys move.
        total = 0
        for lid in lv.all_layer_ids():
            try:
                total += len(list(lv.layer(lid).key_frame_indices()))
            except Exception:
                pass
        return (scene.get_current_frame(), total)
    except Exception:
        return 0


def _d_telemetry_read(params, scene):
    """Read controller position+rotation at given frames using csc.update.

    Implementation derived from go_to_origin.py (update.get_object_by_id(...)
    .root_group().node_deep("Local Position").value(frame)).

    Params:
      controller_ids: list[str]  (object names or stringified ObjectIds)
      frames: list[int]
      local: bool (default True — read "Local Position"/"Local Rotation")

    Returns:
      telemetry[controller_name][frame] = {position: [x,y,z], rotation: [qx,qy,qz,qw]}
    """
    controller_ids = params.get("controller_ids", [])
    frames = params.get("frames", [])
    use_local = params.get("local", True)
    if not isinstance(controller_ids, list) or not isinstance(frames, list):
        raise ValueError("controller_ids and frames must be lists")

    # Resolve names/ids → ObjectId.
    resolved = []  # list of (name_or_id_str, ObjectId or None)
    mv = scene.model_viewer()
    name_index = {}
    id_index = {}
    for oid in mv.get_objects():
        try:
            name_index[mv.get_object_name(oid)] = oid
        except Exception:
            pass
        id_index[_id_str(oid)] = oid

    for c in controller_ids:
        oid = name_index.get(c) or id_index.get(c)
        resolved.append((c, oid))

    pos_node_name = "Local Position" if use_local else "Position"
    rot_node_name = "Local Rotation" if use_local else "Rotation"

    telemetry = {}
    missing = []

    def mod(model, update, scene_updater):
        for label, oid in resolved:
            if oid is None:
                missing.append(label)
                continue
            try:
                node = update.get_object_by_id(oid).root_group()
            except Exception as e:
                telemetry[label] = {"error": f"get_object_by_id: {e}"}
                continue
            pos_attr = node.node_deep(pos_node_name)
            rot_attr = node.node_deep(rot_node_name)
            per_frame = {}
            for f in frames:
                entry = {}
                if pos_attr is not None:
                    try:
                        v = pos_attr.value(int(f))
                        entry["position"] = _vec_to_list(v)
                        if entry["position"] is None:
                            entry["position_repr"] = _safe_repr(v)
                    except Exception as e:
                        entry["position_error"] = str(e)
                if rot_attr is not None:
                    try:
                        r = rot_attr.value(int(f))
                        try:
                            q = r.to_quaternion()
                            # csc.math.Quaternion exposes .x()/.y()/.z()/.w() as methods
                            entry["rotation"] = [
                                float(q.x() if callable(q.x) else q.x),
                                float(q.y() if callable(q.y) else q.y),
                                float(q.z() if callable(q.z) else q.z),
                                float(q.w() if callable(q.w) else q.w),
                            ]
                        except Exception:
                            # Fallback: convert via euler
                            try:
                                e_ang = r.to_euler_angles()
                                entry["rotation_euler"] = _vec_to_list(e_ang) or [
                                    float(e_ang[0]),
                                    float(e_ang[1]),
                                    float(e_ang[2]),
                                ]
                            except Exception:
                                entry["rotation_repr"] = _safe_repr(r)
                    except Exception as e:
                        entry["rotation_error"] = str(e)
                per_frame[str(f)] = entry
            telemetry[label] = per_frame

    scene.modify_update("Poppet: read telemetry", mod)
    return {
        "telemetry": telemetry,
        "frames": frames,
        "missing": missing,
        "node_names": [pos_node_name, rot_node_name],
    }


# ============================================================================
# FBX I/O
# ============================================================================


def _fbx_loader_and_settings(scope="scene"):
    """Get the FbxSceneLoader's loader + return configured FbxSettings.

    Pattern from Cascadeur's bundled quick_export and export_to_roblox scripts:
        loader_tool = app.get_tools_manager().get_tool('FbxSceneLoader')
        loader = loader_tool.get_fbx_loader(scene)
    """
    import csc
    from csc import fbx

    app = csc.app.get_application()
    scene_pr = app.get_scene_manager().current_scene()
    loader_tool = app.get_tools_manager().get_tool("FbxSceneLoader")
    loader = loader_tool.get_fbx_loader(scene_pr)
    settings = fbx.FbxSettings()
    settings.mode = fbx.FbxSettingsMode.Binary
    settings.up_axis = fbx.FbxSettingsAxis.Y
    settings.bake_animation = True
    settings.apply_euler_filter = True
    loader.set_settings(settings)
    return loader, settings


def _d_fbx_export(params, scene):
    """Export the entire scene to FBX without a dialog.

    Path must be absolute. Uses csc.fbx.FbxLoader.export_all_objects which
    is the canonical Cascadeur dialog-free entry point.
    """
    import os

    path = params.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("'path' must be a non-empty string")
    if not os.path.isabs(path):
        raise ValueError(f"'path' must be absolute: {path!r}")
    # Make sure target dir exists (FbxLoader errors out if it doesn't).
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass

    # Normalize path separators — FbxLoader is finicky on Windows.
    normalized = path.replace("\\", "/")

    loader, settings = _fbx_loader_and_settings()
    loader.export_all_objects(normalized)

    # Verify the file appeared (FbxLoader silently no-ops on some error paths).
    exists = os.path.exists(normalized)
    size = os.path.getsize(normalized) if exists else 0
    return {
        "path": normalized,
        "exists": exists,
        "size_bytes": size,
        "settings": {
            "mode": "Binary",
            "up_axis": "Y",
            "bake_animation": True,
            "apply_euler_filter": True,
        },
    }


def _d_fbx_import(params, scene):
    """Import an FBX file into the current scene without a dialog."""
    import os

    path = params.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("'path' must be a non-empty string")
    if not os.path.exists(path):
        raise ValueError(f"FBX file not found: {path!r}")
    normalized = path.replace("\\", "/")
    loader, _ = _fbx_loader_and_settings()
    # FbxLoader.import_scene loads the whole file as a new scene.
    # For animation-only import into the current scene, use import_animation.
    target = params.get("target", "scene")  # "scene" | "animation"
    if target == "animation":
        loader.import_animation(normalized)
    else:
        loader.import_scene(normalized)
    return {"path": normalized, "target": target, "imported": True}


# ============================================================================
# Frame / playhead
# ============================================================================


def _d_frame_get(params, scene):
    return {"current_frame": scene.get_current_frame()}


def _d_frame_set(params, scene):
    """Move the playhead. Pattern from bundled export_to_roblox.py:

        def mod(model, update, scene_updater, session):
            session.set_current_frame(frame_num)
        scene.modify_update_with_session("...", mod)

    The set_current_frame call MUST be inside the modify_update_with_session
    callback — bare scene.set_current_frame() or session.set_current_frame()
    outside a session context is silently no-op in 2025.3.3.
    """
    frame = int(params["frame"])
    err = {"value": None}

    def mod(model, update, scene_updater, session):
        try:
            session.set_current_frame(frame)
        except Exception as e:
            err["value"] = f"{type(e).__name__}: {e}"

    try:
        scene.modify_update_with_session("Poppet: set frame", mod)
    except Exception as e:
        err["value"] = f"modify_update_with_session: {type(e).__name__}: {e}"

    actual = scene.get_current_frame()
    out = {
        "requested": frame,
        "current_frame": actual,
        # get_current_frame() often lags behind the in-session change; the
        # visual playhead moves correctly even when this reads back 0.
        "note": "playhead moves visually; readback may lag until next drain",
    }
    if err["value"]:
        out["error"] = err["value"]
    return out


# ============================================================================
# Scene file I/O (save / load / new)
# ============================================================================


def _d_save_scene(params, scene):
    """Save the current scene to a .casc file via DataSourceManager.

    Tries several method signatures because the API surface drifts between
    Cascadeur versions — reports which variant worked.
    """
    import csc

    path = params.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("'path' must be a non-empty string")
    normalized = path.replace("\\", "/")
    try:
        os.makedirs(os.path.dirname(normalized), exist_ok=True)
    except Exception:
        pass

    app = csc.app.get_application()
    dsm = app.get_data_source_manager()
    cur = app.current_scene()

    last_err = None
    method = None
    for label, attempt in (
        ("dsm.save_scene(cur, path)", lambda: dsm.save_scene(cur, normalized)),
        ("dsm.save_scene(path, cur)", lambda: dsm.save_scene(normalized, cur)),
        ("dsm.save(cur, path)", lambda: dsm.save(cur, normalized)),
        ("cur.save(path)", lambda: cur.save(normalized)),
    ):
        try:
            attempt()
            method = label
            last_err = None
            break
        except Exception as e:
            last_err = f"{label}: {type(e).__name__}: {e}"

    out = {"path": normalized}
    if last_err and not method:
        out["error"] = last_err
        out["saved"] = False
    else:
        out["method"] = method
        out["exists"] = os.path.exists(normalized)
        out["size_bytes"] = os.path.getsize(normalized) if out["exists"] else 0
        out["saved"] = True
    return out


def _d_load_scene(params, scene):
    """Open a .casc file via DataSourceManager.load_scene."""
    import csc

    path = params.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("'path' must be a non-empty string")
    if not os.path.exists(path):
        raise ValueError(f"scene file not found: {path!r}")
    normalized = path.replace("\\", "/")

    app = csc.app.get_application()
    dsm = app.get_data_source_manager()

    last_err = None
    method = None
    for label, attempt in (
        ("dsm.load_scene(path)", lambda: dsm.load_scene(normalized)),
        ("dsm.open_scene(path)", lambda: dsm.open_scene(normalized)),
    ):
        try:
            attempt()
            method = label
            last_err = None
            break
        except Exception as e:
            last_err = f"{label}: {type(e).__name__}: {e}"

    out = {"path": normalized, "loaded": method is not None}
    if method:
        out["method"] = method
    if last_err and not method:
        out["error"] = last_err
    return out


def _d_new_scene(params, scene):
    """Create a fresh empty scene via SceneManager.create_application_scene."""
    import csc

    app = csc.app.get_application()
    sm = app.get_scene_manager()

    last_err = None
    method = None
    for label, attempt in (
        ("sm.create_application_scene()", lambda: sm.create_application_scene()),
        ("sm.create_scene()", lambda: sm.create_scene()),
        ("sm.new_scene()", lambda: sm.new_scene()),
    ):
        try:
            ns = attempt()
            try:
                sm.set_current_scene(ns)
            except Exception:
                pass
            method = label
            last_err = None
            break
        except Exception as e:
            last_err = f"{label}: {type(e).__name__}: {e}"

    out = {"created": method is not None}
    if method:
        out["method"] = method
    if last_err and not method:
        out["error"] = last_err
    return out


# ============================================================================
# Object hierarchy + transforms
# ============================================================================


def _d_object_hierarchy(params, scene):
    """Walk the scene's object hierarchy returning parent + children per object."""
    mv = scene.model_viewer()
    out = []
    for oid in mv.get_objects():
        entry = {"id": _id_str(oid)}
        try:
            entry["name"] = mv.get_object_name(oid)
        except Exception:
            entry["name"] = None
        try:
            entry["type"] = mv.get_object_type_name(oid)
        except Exception:
            entry["type"] = None
        for getter in ("get_parent_id", "get_parent", "parent_id", "parent"):
            try:
                fn = getattr(mv, getter, None)
                if fn is None:
                    continue
                pid = fn(oid)
                if pid is not None:
                    entry["parent_id"] = _id_str(pid)
                    break
            except Exception:
                continue
        for getter in ("get_children_ids", "get_children", "children_ids", "children"):
            try:
                fn = getattr(mv, getter, None)
                if fn is None:
                    continue
                children = list(fn(oid))
                entry["children_ids"] = [_id_str(c) for c in children]
                break
            except Exception:
                continue
        out.append(entry)
    return {"objects": out, "count": len(out)}


def _d_object_transform_get(params, scene):
    """Read Position+Rotation+Scale on one object at a given frame.

    Variant of telemetry_read for a single object with all three transforms.
    """
    name = params.get("object_name")
    frame = int(params.get("frame", 0))
    use_local = params.get("local", True)
    if not name:
        raise ValueError("'object_name' is required")

    obj_id = _find_obj_by_name(scene, name)
    if obj_id is None:
        raise ValueError(f"object not found: {name!r}")

    pos_name = "Local Position" if use_local else "Position"
    rot_name = "Local Rotation" if use_local else "Rotation"
    scale_name = "Local Scale" if use_local else "Scale"

    out = {"object": name, "frame": frame}

    def mod(model, update, scene_updater):
        try:
            node = update.get_object_by_id(obj_id).root_group()
        except Exception as e:
            out["error"] = f"get_object_by_id: {e}"
            return
        for label, node_name in (
            ("position", pos_name),
            ("rotation", rot_name),
            ("scale", scale_name),
        ):
            try:
                attr = node.node_deep(node_name)
                if attr is None:
                    out[label] = None
                    continue
                v = attr.value(frame)
                if label == "rotation":
                    # csc.math.Rotation — not a plain Vec3, needs special handling.
                    try:
                        q = v.to_quaternion()
                        # csc.math.Quaternion exposes .x()/.y()/.z()/.w() as methods
                        out[label] = [
                            float(q.x() if callable(q.x) else q.x),
                            float(q.y() if callable(q.y) else q.y),
                            float(q.z() if callable(q.z) else q.z),
                            float(q.w() if callable(q.w) else q.w),
                        ]
                    except Exception:
                        try:
                            e_ang = v.to_euler_angles()
                            out[label + "_euler"] = _vec_to_list(e_ang) or [
                                float(e_ang[0]), float(e_ang[1]), float(e_ang[2])
                            ]
                        except Exception:
                            out[label + "_repr"] = _safe_repr(v)
                else:
                    listed = _vec_to_list(v)
                    if listed is not None:
                        out[label] = listed
                    else:
                        out[label + "_repr"] = _safe_repr(v)
            except Exception as e:
                out[label + "_error"] = f"{type(e).__name__}: {e}"

    scene.modify_update("Poppet: read transform", mod)
    return out


def _d_object_attributes_list(params, scene):
    """List all attribute node names on an object's root_group.

    Helps the LLM discover what's settable on a controller without guessing
    ("Local Position", "Local Rotation", "Local Scale", IK weights, etc.).
    """
    name = params.get("object_name")
    if not name:
        raise ValueError("'object_name' is required")
    obj_id = _find_obj_by_name(scene, name)
    if obj_id is None:
        raise ValueError(f"object not found: {name!r}")

    out = {"object": name, "attributes": []}

    def mod(model, update, scene_updater):
        try:
            root = update.get_object_by_id(obj_id).root_group()
        except Exception as e:
            out["error"] = f"get_object_by_id: {e}"
            return
        attrs = []
        # First: flat nodes() if available.
        try:
            for n in root.nodes():
                try:
                    attrs.append({"name": n.full_name()})
                except Exception:
                    try:
                        attrs.append({"name": n.name()})
                    except Exception:
                        attrs.append({"repr": _safe_repr(n)})
        except Exception:
            pass
        # Fallback: recursive children() walk.
        if not attrs:

            def walk(g, prefix=""):
                try:
                    for c in g.children():
                        n = prefix + (c.name() if hasattr(c, "name") else "?")
                        attrs.append({"name": n})
                        try:
                            walk(c, n + ".")
                        except Exception:
                            pass
                except Exception:
                    pass

            walk(root)
        out["attributes"] = attrs
        out["count"] = len(attrs)

    scene.modify_update("Poppet: read attributes", mod)
    return out


# ============================================================================
# Layer ops
# ============================================================================


def _resolve_layer(scene, layer_id_str):
    """Find (LayerId, Layer) by stringified id, or (None, None)."""
    lv = scene.layers_viewer()
    for lid in lv.all_layer_ids():
        if _id_str(lid) == layer_id_str:
            return lid, lv.layer(lid)
    return None, None


def _d_layer_visible_set(params, scene):
    """Toggle layer visibility via layers_editor (or layer.set_visible fallback)."""
    layer_id_str = params.get("layer_id")
    visible = bool(params.get("visible", True))
    if not layer_id_str:
        raise ValueError("'layer_id' is required")
    lid, layer = _resolve_layer(scene, layer_id_str)
    if layer is None:
        raise ValueError(f"layer_id not found: {layer_id_str!r}")

    err = {"value": None}

    def mod(model, update, sc, session):
        try:
            try:
                ed = model.layers_editor()
                ed.set_visible_for_layer(lid, visible)
            except Exception:
                layer.set_visible(visible)
        except Exception as e:
            err["value"] = f"{type(e).__name__}: {e}"

    scene.modify_with_session("Poppet: set layer visible", mod)
    out = {"layer_id": layer_id_str, "visible": visible}
    if err["value"]:
        out["error"] = err["value"]
    return out


def _d_layer_locked_set(params, scene):
    """Toggle layer lock via layers_editor (or layer.set_locked fallback)."""
    layer_id_str = params.get("layer_id")
    locked = bool(params.get("locked", True))
    if not layer_id_str:
        raise ValueError("'layer_id' is required")
    lid, layer = _resolve_layer(scene, layer_id_str)
    if layer is None:
        raise ValueError(f"layer_id not found: {layer_id_str!r}")

    err = {"value": None}

    def mod(model, update, sc, session):
        try:
            try:
                ed = model.layers_editor()
                ed.set_locked_for_layer(lid, locked)
            except Exception:
                layer.set_locked(locked)
        except Exception as e:
            err["value"] = f"{type(e).__name__}: {e}"

    scene.modify_with_session("Poppet: set layer locked", mod)
    out = {"layer_id": layer_id_str, "locked": locked}
    if err["value"]:
        out["error"] = err["value"]
    return out


# ============================================================================
# Object edit (delete / duplicate)
# ============================================================================


def _d_object_delete(params, scene):
    """Delete an object by name. Tries model_editor first, falls back to action ID."""
    import csc

    name = params.get("object_name")
    if not name:
        raise ValueError("'object_name' is required")
    obj_id = _find_obj_by_name(scene, name)
    if obj_id is None:
        raise ValueError(f"object not found: {name!r}")

    # Strategy 1: model_editor.delete_objects([oid])
    try:

        def mod(model, update, sc, session):
            me = session.model_editor()
            me.delete_objects([obj_id])

        scene.modify_with_session("Poppet: delete object", mod)
        return {
            "deleted": name,
            "obj_id": _id_str(obj_id),
            "method": "model_editor.delete_objects",
        }
    except Exception as e:
        last_err = f"model_editor: {type(e).__name__}: {e}"

    # Strategy 2: select then call Scene.Edit.Delete-style action.
    try:

        def sel(model, update, sc, session):
            session.take_selector().select({obj_id}, obj_id)

        scene.modify_with_session("Poppet: select for delete", sel)
    except Exception as e:
        last_err = f"select: {e}"

    app = csc.app.get_application()
    am = app.get_action_manager()
    for action in ("Scene.Edit.Delete", "Edit.Delete", "Object.Delete"):
        try:
            am.call_action(action)
            return {
                "deleted": name,
                "obj_id": _id_str(obj_id),
                "method": f"call_action:{action}",
            }
        except Exception as e:
            last_err = f"{action}: {e}"

    return {"deleted": False, "obj_id": _id_str(obj_id), "last_error": last_err}


def _d_object_duplicate(params, scene):
    """Duplicate object by selecting it and invoking a duplicate action.

    Returns the list of newly-created objects (object names that appeared in
    the scene between before/after).
    """
    import csc

    name = params.get("object_name")
    if not name:
        raise ValueError("'object_name' is required")
    obj_id = _find_obj_by_name(scene, name)
    if obj_id is None:
        raise ValueError(f"object not found: {name!r}")

    before = set()
    try:
        for oid in scene.model_viewer().get_objects():
            before.add(_id_str(oid))
    except Exception:
        pass

    def sel(model, update, sc, session):
        session.take_selector().select({obj_id}, obj_id)

    scene.modify_with_session("Poppet: select for duplicate", sel)

    app = csc.app.get_application()
    am = app.get_action_manager()
    last_err = None
    invoked = None
    for action in ("Scene.Edit.Duplicate", "Edit.Duplicate", "Object.Duplicate"):
        try:
            am.call_action(action)
            invoked = action
            break
        except Exception as e:
            last_err = f"{action}: {e}"

    after = []
    try:
        for oid in scene.model_viewer().get_objects():
            sid = _id_str(oid)
            if sid not in before:
                try:
                    nm = scene.model_viewer().get_object_name(oid)
                    after.append({"id": sid, "name": nm})
                except Exception:
                    after.append({"id": sid})
    except Exception:
        pass

    out = {"source": name, "source_id": _id_str(obj_id), "new_objects": after}
    if invoked:
        out["invoked"] = invoked
    if last_err and not invoked:
        out["error"] = last_err
    return out


# ============================================================================
# Viewport screenshot
# ============================================================================


def _d_viewport_screenshot(params, scene):
    """Capture the 3D viewport to an image file.

    Tries RenderToFile tool first, falls back to Viewport.* action IDs.
    """
    import csc

    path = params.get("path")
    if not isinstance(path, str) or not path:
        import tempfile, time
        path = os.path.join(tempfile.gettempdir(), f"poppet_screenshot_{int(time.time())}.png")
    normalized = path.replace("\\", "/")
    try:
        os.makedirs(os.path.dirname(normalized), exist_ok=True)
    except Exception:
        pass

    app = csc.app.get_application()
    last_err = None

    # Strategy 1: RenderToFile tool.
    try:
        tm = app.get_tools_manager()
        rtf = tm.get_tool("RenderToFile")
        view_scene = app.current_scene()
        editor = rtf.editor(view_scene)
        editor.take_image(normalized)
        if os.path.exists(normalized):
            return {
                "path": normalized,
                "exists": True,
                "size_bytes": os.path.getsize(normalized),
                "method": "RenderToFile.editor.take_image",
            }
    except Exception as e:
        last_err = f"RenderToFile: {type(e).__name__}: {e}"

    # Strategy 2: Viewport action fallbacks (path arg cannot be passed via call_action).
    am = app.get_action_manager()
    for action in ("Viewport.TakeScreenshot", "Viewport.Screenshot", "Render.Image"):
        try:
            am.call_action(action)
            return {
                "path": normalized,
                "exists": os.path.exists(normalized),
                "method": f"call_action:{action}",
                "note": "action invoked but path arg couldn't be passed — "
                "Cascadeur may have written to its default screenshot dir.",
            }
        except Exception as e:
            last_err = f"{action}: {e}"

    return {"path": normalized, "exists": False, "error": last_err}


# ============================================================================
# Layer create / delete + animation utilities
# ============================================================================


def _d_layer_add(params, scene):
    """Create a new animation layer. Pattern from common/layers_operation.py.

    Params:
      name: str (required)
      parent_id: str (optional, stringified parent LayerId)
    """
    import csc

    name = params.get("name")
    if not name:
        raise ValueError("'name' is required")
    parent_str = params.get("parent_id")

    out = {"name": name}

    def mod(model, update, sc, session):
        try:
            le = model.layers_editor()
        except Exception as e:
            out["error"] = f"layers_editor: {e}"
            return
        # Resolve parent: use stringified id match, fall back to root.
        parent_id = None
        if parent_str:
            for lid in scene.layers_viewer().all_layer_ids():
                if _id_str(lid) == parent_str:
                    parent_id = lid
                    break
            if parent_id is None:
                out["parent_warning"] = f"parent_id {parent_str!r} not found; creating at root"
        if parent_id is None:
            try:
                parent_id = scene.layers_viewer().root_id()
            except Exception:
                parent_id = csc.layers.LayerId.null() if hasattr(csc, "layers") else None
        try:
            new_id = le.create_layer(name, parent_id)
            out["layer_id"] = _id_str(new_id)
            out["created"] = True
        except Exception as e:
            out["error"] = f"create_layer: {e}"

    scene.modify_with_session("Poppet: add layer", mod)
    return out


def _d_layer_delete(params, scene):
    """Delete a layer by id."""
    layer_id_str = params.get("layer_id")
    if not layer_id_str:
        raise ValueError("'layer_id' is required")
    lid, _ = _resolve_layer(scene, layer_id_str)
    if lid is None:
        raise ValueError(f"layer_id not found: {layer_id_str!r}")

    err = {"value": None}

    def mod(model, update, sc, session):
        try:
            le = model.layers_editor()
            le.delete_layer(lid)
        except Exception as e:
            err["value"] = f"{type(e).__name__}: {e}"

    scene.modify_with_session("Poppet: delete layer", mod)
    out = {"layer_id": layer_id_str, "deleted": err["value"] is None}
    if err["value"]:
        out["error"] = err["value"]
    return out


def _d_undo(params, scene):
    """Wraps the Scene.Undo action."""
    import csc

    app = csc.app.get_application()
    app.get_action_manager().call_action("Scene.Undo")
    return {"invoked": "Scene.Undo"}


def _d_redo(params, scene):
    """Wraps the Scene.Redo action."""
    import csc

    app = csc.app.get_application()
    app.get_action_manager().call_action("Scene.Redo")
    return {"invoked": "Scene.Redo"}


def _d_selection_filter(params, scene):
    """Replace selection with objects whose names match a pattern.

    Modes:
      contains: name contains substring (default)
      prefix:   name starts with substring
      suffix:   name ends with substring
      regex:    name fully matches a regex
    """
    import re as _re

    import csc

    pattern = params.get("pattern", "")
    mode = params.get("mode", "contains")
    if not pattern:
        raise ValueError("'pattern' is required")
    if mode not in ("contains", "prefix", "suffix", "regex"):
        raise ValueError(f"'mode' must be contains/prefix/suffix/regex, got {mode!r}")

    matched_ids = []
    matched_names = []
    mv = scene.model_viewer()
    rx = _re.compile(pattern) if mode == "regex" else None
    for oid in mv.get_objects():
        try:
            name = mv.get_object_name(oid) or ""
        except Exception:
            continue
        keep = False
        if mode == "contains":
            keep = pattern in name
        elif mode == "prefix":
            keep = name.startswith(pattern)
        elif mode == "suffix":
            keep = name.endswith(pattern)
        elif mode == "regex":
            keep = rx is not None and rx.fullmatch(name) is not None
        if keep:
            matched_ids.append(oid)
            matched_names.append(name)

    focus = matched_ids[0] if matched_ids else csc.model.ObjectId.null()

    def mod(model, update, sc, session):
        session.take_selector().select(set(matched_ids), focus)

    scene.modify_with_session("Poppet: selection_filter", mod)
    return {
        "pattern": pattern,
        "mode": mode,
        "matched_count": len(matched_ids),
        "matched_names": matched_names[:50],  # cap for transport
    }


def _d_active_layer_get(params, scene):
    """Return the currently-active editing layer (id + name)."""
    lv = scene.layers_viewer()
    # Try several access paths (API drift).
    out = {"active_layer_id": None, "active_layer_name": None}
    for getter in ("current_layer_id", "active_layer_id", "selected_layer_id"):
        try:
            fn = getattr(lv, getter, None)
            if fn is None:
                continue
            lid = fn()
            if lid is None:
                continue
            out["active_layer_id"] = _id_str(lid)
            try:
                out["active_layer_name"] = lv.layer(lid).name()
            except Exception:
                pass
            out["method"] = getter
            return out
        except Exception:
            continue
    out["error"] = "no current/active/selected_layer_id method on layers_viewer"
    return out


def _d_selection_extend(params, scene):
    """Add names to the existing selection (union)."""
    import csc

    names = params.get("object_names", [])
    if not isinstance(names, list):
        raise ValueError("'object_names' must be a list")

    # Resolve names + capture current selection.
    to_add = []
    missing = []
    for n in names:
        oid = _find_obj_by_name(scene, n)
        if oid is None:
            missing.append(n)
        else:
            to_add.append(oid)

    existing = set()
    try:
        for sid in scene.selector().selected().ids:
            if isinstance(sid, csc.model.ObjectId):
                existing.add(sid)
    except Exception:
        pass

    new_set = existing | set(to_add)
    # focus: keep the existing focus if possible, else first of the new additions
    focus = next(iter(to_add), None)
    if focus is None:
        focus = next(iter(existing), csc.model.ObjectId.null())

    def mod(model, update, sc, session):
        session.take_selector().select(new_set, focus)

    scene.modify_with_session("Poppet: selection_extend", mod)
    return {
        "added": [n for n in names if n not in missing],
        "missing": missing,
        "selection_count": len(new_set),
    }


def _d_selection_subtract(params, scene):
    """Remove names from the existing selection (difference)."""
    import csc

    names = params.get("object_names", [])
    if not isinstance(names, list):
        raise ValueError("'object_names' must be a list")

    to_remove_ids = set()
    missing = []
    for n in names:
        oid = _find_obj_by_name(scene, n)
        if oid is None:
            missing.append(n)
        else:
            to_remove_ids.add(oid)

    existing = set()
    try:
        for sid in scene.selector().selected().ids:
            if isinstance(sid, csc.model.ObjectId):
                existing.add(sid)
    except Exception:
        pass

    new_set = existing - to_remove_ids
    focus = next(iter(new_set), csc.model.ObjectId.null())

    def mod(model, update, sc, session):
        session.take_selector().select(new_set, focus)

    scene.modify_with_session("Poppet: selection_subtract", mod)
    return {
        "removed": [n for n in names if n not in missing],
        "missing": missing,
        "selection_count": len(new_set),
    }


def _d_telemetry_read_range(params, scene):
    """Bulk-read controller transforms across a frame range.

    More efficient than calling telemetry_read once per frame because we
    walk the update graph once. Returns a frames-indexed dict per controller.

    Params:
      controller_ids: list[str]
      frame_start: int
      frame_end: int (inclusive)
      step: int (default 1 — sample every Nth frame)
      local: bool (default True)
    """
    controllers = params.get("controller_ids", [])
    if not isinstance(controllers, list) or not controllers:
        raise ValueError("'controller_ids' must be a non-empty list")
    frame_start = int(params.get("frame_start", 0))
    frame_end = int(params.get("frame_end", 0))
    step = int(params.get("step", 1))
    if step < 1:
        raise ValueError("'step' must be >= 1")
    if frame_end < frame_start:
        raise ValueError("'frame_end' must be >= frame_start")
    use_local = params.get("local", True)

    frames = list(range(frame_start, frame_end + 1, step))

    # Reuse telemetry_read's resolution + read logic.
    return _d_telemetry_read(
        {"controller_ids": controllers, "frames": frames, "local": use_local},
        scene,
    )


def _d_keyframe_add(params, scene):
    """Add a keyframe on `layer_id` at `frame`.

    Uses the same `set_fixed_interpolation_or_key_if_need` path bake_range
    uses, but for a single frame.
    """
    layer_id_str = params.get("layer_id")
    frame = int(params.get("frame", 0))
    if not layer_id_str:
        raise ValueError("'layer_id' is required")
    lid, _ = _resolve_layer(scene, layer_id_str)
    if lid is None:
        raise ValueError(f"layer_id not found: {layer_id_str!r}")

    err = {"value": None}

    def mod(model, update, sc, session):
        try:
            le = model.layers_editor()
            le.set_fixed_interpolation_or_key_if_need(lid, frame, True)
        except Exception as e:
            err["value"] = f"{type(e).__name__}: {e}"

    scene.modify_with_session("Poppet: add keyframe", mod)
    out = {"layer_id": layer_id_str, "frame": frame, "added": err["value"] is None}
    if err["value"]:
        out["error"] = err["value"]
    return out


def _d_keyframe_remove(params, scene):
    """Remove the keyframe at `frame` on `layer_id`.

    Pattern from commands/animation_scripts/keyframe_reduction.py:
        le.unset_section(frame, layer_id)
    """
    layer_id_str = params.get("layer_id")
    frame = int(params.get("frame", 0))
    if not layer_id_str:
        raise ValueError("'layer_id' is required")
    lid, _ = _resolve_layer(scene, layer_id_str)
    if lid is None:
        raise ValueError(f"layer_id not found: {layer_id_str!r}")

    err = {"value": None}

    def mod(model, update, sc, session):
        try:
            le = model.layers_editor()
            le.unset_section(frame, lid)
        except Exception as e:
            err["value"] = f"{type(e).__name__}: {e}"

    scene.modify_with_session("Poppet: remove keyframe", mod)
    out = {"layer_id": layer_id_str, "frame": frame, "removed": err["value"] is None}
    if err["value"]:
        out["error"] = err["value"]
    return out


def _d_set_controller_scale(params, scene):
    """Set a controller's Local Scale (or Scale) at a frame.

    Mirrors _d_keyframe_set but writes to the Scale node instead of
    Position/Rotation. Useful for stretchy IK or non-uniform scale targets.

    Params:
      controller_id: str
      frame: int
      scale: [sx, sy, sz]
      local: bool (default True)
    """
    controller = params.get("controller_id")
    if not controller:
        raise ValueError("controller_id is required")
    if "scale" not in params:
        raise ValueError("'scale' is required (list of 3 floats)")
    scale = params["scale"]
    frame = int(params["frame"])
    use_local = params.get("local", True)

    obj_id = _find_obj_by_name(scene, controller)
    if obj_id is None:
        mv = scene.model_viewer()
        for oid in mv.get_objects():
            if _id_str(oid) == controller:
                obj_id = oid
                break
    if obj_id is None:
        raise ValueError(f"controller not found by name or id: {controller!r}")

    scale_node_name = "Local Scale" if use_local else "Scale"
    applied = {"frame": frame}
    actuals_acc = []

    _ext_err_s = {"value": None}

    def _extend_mod_s(model, update, sc, session):
        try:
            le = model.layers_editor()
            for _lid in list(scene.layers_viewer().all_layer_ids()):
                try:
                    le.set_fixed_interpolation_or_key_if_need(_lid, frame, True)
                except Exception:
                    pass
        except Exception as e:
            _ext_err_s["value"] = str(e)

    scene.modify_with_session("Poppet: extend animation for scale", _extend_mod_s)
    if _ext_err_s["value"]:
        applied["extend_warning"] = _ext_err_s["value"]

    def mod(model, update, scene_updater):
        actuals = set()
        try:
            node = update.get_object_by_id(obj_id).root_group()
        except Exception as e:
            applied["error"] = f"get_object_by_id: {e}"
            return
        try:
            attr = node.node_deep(scale_node_name)
            if attr is None:
                applied["error"] = f"node {scale_node_name!r} not on {controller!r}"
                return
            current = attr.value(frame)
            if current is not None:
                delta = [
                    float(scale[0]) - float(current[0]),
                    float(scale[1]) - float(current[1]),
                    float(scale[2]) - float(current[2]),
                ]
                new_val = current + delta
            else:
                new_val = [float(scale[0]), float(scale[1]), float(scale[2])]
            attr.set_value(new_val, frame)
            actuals.add(attr.data_id())
            applied["scale_new"] = _vec_to_list(new_val)
            applied["scale_set"] = True
        except Exception as e:
            applied["error"] = f"{type(e).__name__}: {e}"
        actuals_acc.extend(actuals)
        if actuals:
            try:
                scene_updater.run_update(actuals, frame)
            except Exception as e:
                applied["run_update_error"] = f"{type(e).__name__}: {e}"

    scene.modify_update("Poppet: set scale", mod)
    return {
        "controller": controller,
        "obj_id": _id_str(obj_id),
        "applied": applied,
        "attrs_updated": len(actuals_acc),
    }


def _d_active_layer_set(params, scene):
    """Switch the editing-active layer."""
    layer_id_str = params.get("layer_id")
    if not layer_id_str:
        raise ValueError("'layer_id' is required")
    lid, _ = _resolve_layer(scene, layer_id_str)
    if lid is None:
        raise ValueError(f"layer_id not found: {layer_id_str!r}")

    err = {"value": None}
    method_used = {"value": None}

    def mod(model, update, sc, session):
        try:
            le = model.layers_editor()
        except Exception as e:
            err["value"] = f"layers_editor: {e}"
            return
        for setter in ("set_current_layer", "set_active_layer", "set_selected_layer"):
            try:
                fn = getattr(le, setter, None)
                if fn is None:
                    continue
                fn(lid)
                method_used["value"] = setter
                return
            except Exception as e:
                err["value"] = f"{setter}: {e}"

    scene.modify_with_session("Poppet: set active layer", mod)
    out = {"layer_id": layer_id_str}
    if method_used["value"]:
        out["method"] = method_used["value"]
        out["set"] = True
    else:
        out["set"] = False
        if err["value"]:
            out["error"] = err["value"]
    return out


def _d_bake_range(params, scene):
    """Bake keyframes across a frame range on the given layer.

    Pattern from commands/animation_scripts/reverse_animation.py — calls
    layers_editor.set_fixed_interpolation_or_key_if_need(layer_id, frame, True)
    for every frame in [frame_start, frame_end] to materialize per-frame keys.
    """
    layer_id_str = params.get("layer_id")
    frame_start = int(params.get("frame_start", 0))
    frame_end = int(params.get("frame_end", 0))
    if not layer_id_str:
        raise ValueError("'layer_id' is required")
    if frame_end < frame_start:
        raise ValueError("frame_end must be >= frame_start")
    lid, _ = _resolve_layer(scene, layer_id_str)
    if lid is None:
        raise ValueError(f"layer_id not found: {layer_id_str!r}")

    out = {
        "layer_id": layer_id_str,
        "frame_start": frame_start,
        "frame_end": frame_end,
        "baked_count": 0,
    }
    err = {"value": None}

    def mod(model, update, sc, session):
        try:
            le = model.layers_editor()
        except Exception as e:
            err["value"] = f"layers_editor: {e}"
            return
        baked = 0
        last_err = None
        for f in range(frame_start, frame_end + 1):
            try:
                le.set_fixed_interpolation_or_key_if_need(lid, f, True)
                baked += 1
            except Exception as e:
                last_err = f"frame {f}: {e}"
                # Continue — best-effort baking.
        out["baked_count"] = baked
        if last_err and baked == 0:
            err["value"] = last_err

    scene.modify_with_session("Poppet: bake range", mod)
    if err["value"]:
        out["error"] = err["value"]
    return out


# ============================================================================
# Schema (introspection cache)
# ============================================================================


def _d_schema_get(params, scene):
    from . import _introspect

    path = _introspect.schema_cache_path()
    if not os.path.exists(path):
        _introspect.dump_schema(path)
    with open(path, encoding="utf-8") as f:
        schema_json = f.read()
    return {"path": path, "schema_json_size": len(schema_json), "schema_json": schema_json}


# ============================================================================
# Internals
# ============================================================================


def _safe_call(fn):
    try:
        return fn()
    except Exception:
        return None


def _quat_to_euler_xyz(qx, qy, qz, qw):
    """Convert a quaternion (x,y,z,w) to XYZ Euler angles (radians).

    Standard pitch-roll-yaw from quaternion, math via stdlib only.
    Returns [rx, ry, rz].
    """
    import math as _m

    # roll (X-axis rotation)
    sinr_cosp = 2.0 * (qw * qx + qy * qz)
    cosr_cosp = 1.0 - 2.0 * (qx * qx + qy * qy)
    rx = _m.atan2(sinr_cosp, cosr_cosp)
    # pitch (Y-axis rotation)
    sinp = 2.0 * (qw * qy - qz * qx)
    if abs(sinp) >= 1.0:
        ry = _m.copysign(_m.pi / 2.0, sinp)
    else:
        ry = _m.asin(sinp)
    # yaw (Z-axis rotation)
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    rz = _m.atan2(siny_cosp, cosy_cosp)
    return [rx, ry, rz]


def _vec_to_list(v):
    """Coerce a csc vec-like (Vec3f, numpy array, list, tuple) into [x, y, z]."""
    if v is None:
        return None
    # Try attribute access first (csc Vec types expose .x/.y/.z)
    if all(hasattr(v, c) for c in "xyz"):
        try:
            return [float(v.x), float(v.y), float(v.z)]
        except Exception:
            pass
    # Try indexed access (lists, tuples, numpy)
    try:
        return [float(v[0]), float(v[1]), float(v[2])]
    except Exception:
        return None


_HANDLERS = {
    "echo": _d_echo,
    "exec_csc": _d_exec_csc,
    "call_action": _d_call_action,
    "scene_info": _d_scene_info,
    "selection_get": _d_selection_get,
    "selection_set": _d_selection_set,
    "selection_clear": _d_selection_clear,
    "objects_list": _d_objects_list,
    "layers_list": _d_layers_list,
    "keyframes_get": _d_keyframes_get,
    "keyframe_set": _d_keyframe_set,
    "autopose_run": _d_autopose_run,
    "autophysics_run": _d_autophysics_run,
    "telemetry_read": _d_telemetry_read,
    "fbx_import": _d_fbx_import,
    "fbx_export": _d_fbx_export,
    "frame_get": _d_frame_get,
    "frame_set": _d_frame_set,
    "schema_get": _d_schema_get,
    # New in v0.2 — scene file I/O
    "save_scene": _d_save_scene,
    "load_scene": _d_load_scene,
    "new_scene": _d_new_scene,
    # New in v0.2 — hierarchy + transforms
    "object_hierarchy": _d_object_hierarchy,
    "object_transform_get": _d_object_transform_get,
    "object_attributes_list": _d_object_attributes_list,
    # New in v0.2 — layer ops
    "layer_visible_set": _d_layer_visible_set,
    "layer_locked_set": _d_layer_locked_set,
    # New in v0.2 — object edit
    "object_delete": _d_object_delete,
    "object_duplicate": _d_object_duplicate,
    # New in v0.2 — viewport
    "viewport_screenshot": _d_viewport_screenshot,
    # New in v0.3 — layer create/delete + undo/redo + range bake
    "layer_add": _d_layer_add,
    "layer_delete": _d_layer_delete,
    "undo": _d_undo,
    "redo": _d_redo,
    "bake_range": _d_bake_range,
    "selection_filter": _d_selection_filter,
    "active_layer_get": _d_active_layer_get,
    "active_layer_set": _d_active_layer_set,
    # v0.4 — proper keyframe add/remove + scale
    "keyframe_add": _d_keyframe_add,
    "keyframe_remove": _d_keyframe_remove,
    "controller_scale_set": _d_set_controller_scale,
    # v0.5
    "selection_extend": _d_selection_extend,
    "selection_subtract": _d_selection_subtract,
    "telemetry_read_range": _d_telemetry_read_range,
}
