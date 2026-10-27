"""cascadeur-mcp in-app runtime — executed *inside* Cascadeur 2026.2+.

This file is not imported by the MCP server process. Its source text is shipped
to Cascadeur's built-in MCP script server (``Scripts -> MCP -> Start script
server``) on the first tool call, then executed there as a private module named
``poppet_rt``. The Cascadeur side of cascadeur-mcp therefore has **no install step**.

Contract with the MCP side (see ``src/poppet_mcp/_expression.py``)::

    dispatch(request_json, scene, csc, app) -> str

``request_json`` is ``{"command": str, "params": {...}}`` and the return value is
a JSON string ``{"status": "success", "result": ...}`` or
``{"status": "error", "message": str, "traceback": str}``.

Every handler runs on Cascadeur's Qt main thread, inside a ``scene_idle`` event —
the same context bundled Cascadeur commands run in — so mutating handlers use the
same undo-friendly ``scene.modify*`` patterns as Nekki's own scripts.

The handlers below were migrated from cascadeur-mcp 0.6's file-queue dispatchers; the
command names and parameter shapes are unchanged so the MCP tool surface (and
any agent prompt written against it) keeps working.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

# Bump when the wire contract or handler semantics change. The MCP client reads
# this value out of the source text (see runtime/__init__.py) and re-bootstraps
# the in-app module whenever the running version differs.
RUNTIME_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def dispatch(request_json, scene, csc, app):
    """JSON entry point used by the expression the MCP server submits."""
    try:
        request = json.loads(request_json)
        message = {
            "type": request.get("command"),
            "params": request.get("params") or {},
        }
        response = _dispatch_legacy(message, scene)
    except Exception:
        response = {
            "status": "error",
            "message": "malformed cascadeur-mcp request",
            "traceback": traceback.format_exc(),
        }
    try:
        return json.dumps(response, default=_json_default)
    except Exception:
        return json.dumps(
            {
                "status": "error",
                "message": "in-app result was not JSON-serialisable",
                "traceback": traceback.format_exc(),
            }
        )


def _json_default(obj):
    """Last-resort encoder for Cascadeur API values (ObjectId and friends)."""
    try:
        return str(obj)
    except Exception:
        return repr(obj)


# ---------------------------------------------------------------------------
# Helpers (csc utilities adapted from Cascadeur's common/selection_operations.py)
# ---------------------------------------------------------------------------


def _dispatch_legacy(message, scene):
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


def _checked_modify(scene, title, callback, *, session=False, update=False):
    """Run a ``scene.modify*`` call and treat an explicit ``False`` as failure.

    Cascadeur logs modify-callback exceptions to its event log and returns
    ``False`` instead of re-raising them (documented by the 2026.2 shipped script
    server). Ignoring that return value is how a handler reports success while
    nothing changed, so every mutating handler routes through here.

    ``session`` selects the ``*_with_session`` variants; ``update`` selects the
    ``*_update*`` variants (both may be set).
    """
    if session and update:
        ok = scene.modify_update_with_session(title, callback)
    elif session:
        ok = scene.modify_with_session(title, callback)
    elif update:
        ok = scene.modify_update(title, callback)
    else:
        ok = scene.modify(title, callback)
    if ok is False:
        raise RuntimeError(
            f"Cascadeur rejected {title!r}: the modify callback failed "
            "(traceback is in Cascadeur's event log)"
        )
    return ok


def _animation_range(scene):
    """Return ``(first, last)`` frames covering the scene animation.

    Verified stub: ``csc.domain.Scene.data_viewer()`` ->
    ``csc.model.DataViewer.get_animation_size()`` (a frame count).
    """
    try:
        size = int(scene.data_viewer().get_animation_size())
        return 0, max(0, size - 1)
    except Exception:
        frame = int(scene.get_current_frame() or 0)
        return frame, frame


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

    # csc.domain.Scene.modify_with_session(str, Callable) -> bool
    _checked_modify(scene, "cascadeur-mcp: set selection", mod, session=True)
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

    _checked_modify(scene, "cascadeur-mcp: clear selection", mod, session=True)
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
            # 2026.2: obj_ids / is_visible / is_locked are properties, not
            # methods (csc.layers.Layer.obj_ids, .is_visible, .is_locked).
            try:
                info["obj_id_count"] = len(layer.obj_ids)
            except Exception:
                pass
            try:
                info["key_frame_count"] = len(list(layer.key_frame_indices()))
            except Exception:
                pass
            try:
                info["is_visible"] = layer.is_visible
            except Exception:
                pass
            try:
                info["is_locked"] = layer.is_locked
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
      transform: {"position": [x, y, z]} and/or {"rotation": [qx, qy, qz, qw]}
          — the envelope the MCP tool layer sends (set_controller_position /
          set_controller_rotation)
      position: [x, y, z]  (legacy flat form, still accepted)
      rotation_quat: [qx, qy, qz, qw]  (legacy flat form, still accepted)
      local: bool (default True — use "Local Position"/"Local Rotation" instead of world)
    """
    import csc

    controller = params.get("controller_id")
    frame = int(params["frame"])
    # The MCP tool layer forwards both channels as {"transform": {...}}; the
    # legacy flat position/rotation_quat keys stay accepted for old clients.
    transform = params.get("transform")
    if not isinstance(transform, dict):
        transform = {}
    position = params.get("position", transform.get("position"))
    rotation_quat = params.get("rotation_quat", transform.get("rotation"))
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

    _checked_modify(
        scene, "cascadeur-mcp: extend animation for keyframe", _extend_mod, session=True
    )

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
                    # Write an explicit 3-vector. csc.update.RegularData.set_value
                    # accepts np.float32[3,1] or a 3-sequence; adding a list to the
                    # array returned by value() broadcasts to (3,3) and corrupts it.
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
                    # csc.math.Rotation.from_quaternion(w, x, y, z) — no
                    # quaternion→Euler→Rotation round-trip (and no gimbal cases).
                    rot_val = csc.math.Rotation.from_quaternion(qw, qx, qy, qz)
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

    _checked_modify(scene, "cascadeur-mcp: set keyframe", mod, update=True)
    errors = [
        applied[key]
        for key in ("error", "position_error", "rotation_error", "run_update_error")
        if key in applied
    ]
    if errors:
        raise RuntimeError("; ".join(str(err) for err in errors))
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

    _checked_modify(scene, "cascadeur-mcp: read telemetry", mod, update=True)
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
    """Move the playhead.

    Live-verified on 2026.2.3: a direct ``csc.domain.Scene.set_current_frame(int)``
    call on the main thread moves the playhead and reads back immediately. The
    2025.3-era "must be inside modify_update_with_session" workaround is stale —
    in 2026.2 it returned success while doing nothing.
    """
    frame = int(params["frame"])
    scene.set_current_frame(frame)  # csc.domain.Scene.set_current_frame(frame) -> None
    return {"requested": frame, "current_frame": scene.get_current_frame()}


# ============================================================================
# Scene file I/O (save / load / new)
# ============================================================================


def _d_save_scene(params, scene):
    """Save the current scene to ``path``.

    Live-verified on 2026.2.3: ``csc.view.Scene.save(path)`` is what actually
    writes the .casc file. ``DataSourceManager.save_scene_as`` and the
    callback-based ``save_scene`` return without writing anything, so they are
    kept only as fallbacks. The client polls for the file, since a large scene can
    take a moment to hit disk.
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
    view_scene = app.current_scene()

    last_err = None
    method = None
    for label, attempt in (
        ("view.Scene.save", lambda: view_scene.save(normalized)),
        (
            "DataSourceManager.save_scene_as",
            lambda: dsm.save_scene_as(view_scene, normalized),
        ),
    ):
        try:
            attempt()
            method = label
            last_err = None
            break
        except Exception as exc:  # noqa: BLE001 - report which shape failed
            last_err = f"{label}: {type(exc).__name__}: {exc}"

    if method is None:
        raise RuntimeError(f"could not save the scene: {last_err}")

    exists = os.path.exists(normalized)
    return {
        "path": normalized,
        "method": method,
        "exists": exists,
        "size_bytes": os.path.getsize(normalized) if exists else 0,
        "saved": True,
        "save_pending": not exists,
    }


def _d_load_scene(params, scene):
    """Open a .casc file via DataSourceManager.load_scene.

    Verified stub: ``csc.app.DataSourceManager.load_scene(str) -> bool``. The
    ``open_scene`` fallback never existed and was removed.
    """
    import csc

    path = params.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("'path' must be a non-empty string")
    if not os.path.exists(path):
        raise ValueError(f"scene file not found: {path!r}")
    normalized = path.replace("\\", "/")

    app = csc.app.get_application()
    dsm = app.get_data_source_manager()
    loaded = dsm.load_scene(normalized)
    if loaded is False:
        raise RuntimeError(f"Cascadeur refused to load {normalized!r}")
    return {
        "path": normalized,
        "loaded": True,
        "method": "DataSourceManager.load_scene",
    }


def _d_new_scene(params, scene):
    """Create a fresh empty scene via SceneManager.create_application_scene.

    Verified stubs: ``csc.app.SceneManager.create_application_scene() ->
    csc.view.Scene`` and ``set_current_scene(csc.view.Scene)``. The
    ``create_scene`` / ``new_scene`` fallbacks never existed and were removed.
    """
    import csc

    app = csc.app.get_application()
    sm = app.get_scene_manager()
    view_scene = sm.create_application_scene()
    if view_scene is None:
        raise RuntimeError("SceneManager.create_application_scene() returned None")
    sm.set_current_scene(view_scene)
    return {"created": True, "method": "SceneManager.create_application_scene"}


# ============================================================================
# Object hierarchy + transforms
# ============================================================================


def _d_object_hierarchy(params, scene):
    """Walk the scene hierarchy (parent + children) per object.

    In 2026.2 the parent link lives in the object's ``Basic`` behaviour;
    ModelViewer has no parent/children getters. Verified stubs:
      * csc.model.BehaviourViewer.get_behaviour_by_name(ObjectId, str) -> BehaviourId
      * csc.model.BehaviourViewer.get_behaviour_object(BehaviourId, str) -> ObjectId
      * csc.model.BehaviourViewer.get_children(ObjectId) -> list[BehaviourId]
      * csc.model.BehaviourViewer.get_behaviour_owner(BehaviourId) -> ObjectId
      * csc.model.ObjectId.is_null()
    """
    mv = scene.model_viewer()
    bv = mv.behaviour_viewer()
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
        entry["parent_id"] = None
        try:
            basic = bv.get_behaviour_by_name(oid, "Basic")
            parent_id = bv.get_behaviour_object(basic, "parent")
            if parent_id is not None and not parent_id.is_null():
                entry["parent_id"] = _id_str(parent_id)
        except Exception:
            pass
        entry["children_ids"] = []
        try:
            children = []
            for behaviour_id in bv.get_children(oid):
                child_id = bv.get_behaviour_owner(behaviour_id)
                if child_id is not None and not child_id.is_null():
                    children.append(_id_str(child_id))
            entry["children_ids"] = children
        except Exception:
            pass
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
                                float(e_ang[0]),
                                float(e_ang[1]),
                                float(e_ang[2]),
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

    _checked_modify(scene, "cascadeur-mcp: read transform", mod, update=True)
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
        # csc.update.Group.nodes() returns the direct child nodes; there is no
        # children() walker on the update graph (the old fallback never existed).
        out["attributes"] = attrs
        out["count"] = len(attrs)

    _checked_modify(scene, "cascadeur-mcp: read attributes", mod, update=True)
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
    lid, _ = _resolve_layer(scene, layer_id_str)
    if lid is None:
        raise ValueError(f"layer_id not found: {layer_id_str!r}")

    def mod(model, update, sc, session):
        # csc.model.ModelEditor.layers_editor() -> csc.layers.Editor
        editor = model.layers_editor()
        # csc.layers.Editor.set_visible_for_layer(is_v: bool, id: csc.Guid)
        editor.set_visible_for_layer(visible, lid)

    _checked_modify(scene, "cascadeur-mcp: set layer visible", mod, session=True)
    return {
        "layer_id": layer_id_str,
        "visible": visible,
        "method": "set_visible_for_layer",
    }


def _d_layer_locked_set(params, scene):
    """Toggle layer lock via layers_editor (or layer.set_locked fallback)."""
    layer_id_str = params.get("layer_id")
    locked = bool(params.get("locked", True))
    if not layer_id_str:
        raise ValueError("'layer_id' is required")
    lid, _ = _resolve_layer(scene, layer_id_str)
    if lid is None:
        raise ValueError(f"layer_id not found: {layer_id_str!r}")

    def mod(model, update, sc, session):
        # csc.model.ModelEditor.layers_editor() -> csc.layers.Editor
        editor = model.layers_editor()
        # csc.layers.Editor.set_locked_for_layer(is_l: bool, id: csc.Guid)
        editor.set_locked_for_layer(locked, lid)

    _checked_modify(scene, "cascadeur-mcp: set layer locked", mod, session=True)
    return {
        "layer_id": layer_id_str,
        "locked": locked,
        "method": "set_locked_for_layer",
    }


# ============================================================================
# Object edit (delete / duplicate)
# ============================================================================


def _d_object_delete(params, scene):
    """Delete an object by name via the 2026.2 model editor.

    Verified stubs:
      * csc.model.ModelEditor.delete_objects(set[ObjectId], close_connections=True)
      * csc.domain.SceneUpdater.generate_update()
      * csc.domain.SceneUpdater.run_update(set[csc.model.DataId], frame)
    ``session.model_editor()`` and the ``Scene.Edit.Delete`` action IDs never
    existed and were removed rather than guessed at.
    """
    name = params.get("object_name")
    if not name:
        raise ValueError("'object_name' is required")
    obj_id = _find_obj_by_name(scene, name)
    if obj_id is None:
        raise ValueError(f"object not found: {name!r}")

    def mod(model, update, scene_updater):
        # csc.model.ModelEditor.delete_objects(set[csc.model.ObjectId], close_connections=True)
        model.delete_objects({obj_id})
        frame = scene.get_current_frame()
        # csc.domain.SceneUpdater.generate_update() / run_update(set[csc.model.DataId], frame)
        scene_updater.generate_update()
        scene_updater.run_update(set(), frame)

    _checked_modify(scene, "cascadeur-mcp: delete object", mod, update=True)
    return {
        "deleted": name,
        "obj_id": _id_str(obj_id),
        "method": "ModelEditor.delete_objects",
    }


_PENDING_DUPLICATE: dict[str, list] = {}


def _d_object_duplicate(params, scene):
    """Stage 1 of duplicate: select the source object.

    Cascadeur's bundled ``commands/copy_paste_objects/duplicate.py`` operates on the
    current selection, and on 2026.2.3 a selection made in the same dispatch is not
    visible to the command yet. The MCP tool therefore issues this dispatch first and
    runs the command in the paired ``object_duplicate_finish`` dispatch — the same
    two-step sequence that was live-verified as the workaround.
    """
    name = params.get("object_name")
    if not name:
        raise ValueError("'object_name' is required")
    obj_id = _find_obj_by_name(scene, name)
    if obj_id is None:
        raise ValueError(f"object not found: {name!r}")

    previous_ids = []
    try:
        previous_ids = _selected_obj_ids(scene)
    except Exception:
        previous_ids = []
    _PENDING_DUPLICATE[name] = previous_ids

    def mod(model, update, sc, session):
        session.take_selector().select({obj_id}, obj_id)

    _checked_modify(scene, "cascadeur-mcp: select for duplicate", mod, session=True)
    return {"source": name, "source_id": _id_str(obj_id), "stage": "selected"}


def _d_object_duplicate_finish(params, scene):
    """Stage 2 of duplicate: run Cascadeur's bundled duplicate command."""
    import csc

    name = params.get("object_name")
    if not name:
        raise ValueError("'object_name' is required")
    obj_id = _find_obj_by_name(scene, name)
    if obj_id is None:
        raise ValueError(f"object not found: {name!r}")

    previous_ids = _PENDING_DUPLICATE.pop(name, [])
    mv = scene.model_viewer()

    selected_count = 0
    try:
        selected_count = len(_selected_obj_ids(scene))
    except Exception:
        pass

    before_ids = set()
    try:
        before_ids = set(mv.get_objects())
    except Exception:
        pass

    try:
        import commands.copy_paste_objects.duplicate as duplicate_command
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"could not import Cascadeur's bundled duplicate command: {exc}"
        ) from exc

    duplicate_command.run(scene)

    created_ids = []
    try:
        created_ids = [oid for oid in mv.get_objects() if oid not in before_ids]
    except Exception:
        pass
    if not created_ids:
        raise RuntimeError(
            "Cascadeur's duplicate command did not create an object "
            f"(selection_count_in_finish={selected_count})"
        )

    try:

        def _restore_selection(model, update, sc, session):
            focus = previous_ids[0] if previous_ids else csc.model.ObjectId.null()
            session.take_selector().select(set(previous_ids), focus)

        _checked_modify(scene, "cascadeur-mcp: restore selection", _restore_selection, session=True)
    except Exception:
        pass

    new_objects = []
    for oid in created_ids:
        try:
            new_objects.append({"id": _id_str(oid), "name": mv.get_object_name(oid)})
        except Exception:
            new_objects.append({"id": _id_str(oid)})
    return {
        "source": name,
        "source_id": _id_str(obj_id),
        "new_objects": new_objects,
        "method": "commands.copy_paste_objects.duplicate",
    }


# ============================================================================
# Viewport screenshot
# ============================================================================


def _d_viewport_screenshot(params, scene):
    """Capture the 3D viewport to a PNG via csc.tools.RenderToFile.

    Verified 2026.2 stub: ``csc.tools.RenderToFile.take_image(
    scene_view: csc.view.Scene, render_parameters: csc.tools.RenderParameters,
    file_name: str)``. The old 1-argument call and the unverified
    ``Viewport.*`` action fallbacks were removed.
    """
    import csc

    path = params.get("path")
    if not isinstance(path, str) or not path:
        import tempfile

        path = os.path.join(tempfile.gettempdir(), f"poppet_screenshot_{int(time.time())}.png")
    normalized = path.replace("\\", "/")
    try:
        os.makedirs(os.path.dirname(normalized), exist_ok=True)
    except Exception:
        pass

    app = csc.app.get_application()
    # csc.tools.RenderParameters has width / height / samples attributes.
    render_parameters = csc.tools.RenderParameters()
    render_parameters.width = 1920
    render_parameters.height = 1080
    render_parameters.samples = 1
    view_scene = app.current_scene()  # csc.app.Application.current_scene() -> csc.view.Scene
    tool = app.get_tools_manager().get_tool("RenderToFile")  # csc.app.ToolsManager.get_tool
    tool.take_image(view_scene, render_parameters, normalized)
    # Cascadeur renders asynchronously: the PNG lands on a later frame (~150 ms in
    # the 2026.2.3 sample scene). Report the render as started and let the MCP
    # tool layer poll for the file instead of blocking the main thread here.
    exists = os.path.exists(normalized)
    return {
        "path": normalized,
        "exists": exists,
        "size_bytes": os.path.getsize(normalized) if exists else 0,
        "render_started": True,
        "method": "RenderToFile.take_image",
    }


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
        # csc.model.ModelEditor.layers_editor() -> csc.layers.Editor
        editor = model.layers_editor()
        # Resolve parent: stringified layer id match, else the layers root.
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
                # csc.layers.Viewer.root_id() -> csc.Guid
                parent_id = scene.layers_viewer().root_id()
            except Exception:
                parent_id = csc.Guid.null()  # csc.Guid.null()
        # csc.layers.Editor.create_layer(name: str, parent: csc.Guid) -> csc.Guid
        new_id = editor.create_layer(name, parent_id)
        out["layer_id"] = _id_str(new_id)
        out["created"] = True

    _checked_modify(scene, "cascadeur-mcp: add layer", mod, session=True)
    return out


def _d_layer_delete(params, scene):
    """Delete a layer by id."""
    layer_id_str = params.get("layer_id")
    if not layer_id_str:
        raise ValueError("'layer_id' is required")
    lid, _ = _resolve_layer(scene, layer_id_str)
    if lid is None:
        raise ValueError(f"layer_id not found: {layer_id_str!r}")

    def mod(model, update, sc, session):
        # csc.layers.Editor.delete_layer(id: csc.Guid)
        model.layers_editor().delete_layer(lid)

    _checked_modify(scene, "cascadeur-mcp: delete layer", mod, session=True)
    return {
        "layer_id": layer_id_str,
        "deleted": True,
        "method": "delete_layer",
    }


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

    _checked_modify(scene, "cascadeur-mcp: selection_filter", mod, session=True)
    return {
        "pattern": pattern,
        "mode": mode,
        "matched_count": len(matched_ids),
        "matched_names": matched_names[:50],  # cap for transport
    }


def _d_active_layer_get(params, scene):
    """Return the current timeline layer selection (id + name).

    2026.2 has no editing-active-layer API for the layers panel; keyframe writes
    always address each object's own layer. The nearest verified concept is the
    layers selection. Verified stubs:
      * csc.domain.Scene.get_layers_selector() -> csc.layers.Selector
      * csc.layers.Selector.all_included_layer_ids() / top_layer_id()
      * csc.layers.Viewer.header(id) -> csc.layers.Header (``name`` attribute)
    """
    out = {
        "active_layer_id": None,
        "active_layer_name": None,
        "layer_ids": [],
        "semantics": "timeline-layer-selection",
    }
    try:
        selector = scene.get_layers_selector()
        ids = list(selector.all_included_layer_ids())
    except Exception as e:
        out["error"] = f"layers selector unavailable: {type(e).__name__}: {e}"
        return out
    out["layer_ids"] = [_id_str(lid) for lid in ids]
    if not ids:
        return out
    try:
        active_id = selector.top_layer_id()
    except Exception:
        active_id = ids[0]
    if active_id is None or active_id.is_null():
        active_id = ids[0]
    out["active_layer_id"] = _id_str(active_id)
    try:
        lv = scene.layers_viewer()
        out["active_layer_name"] = str(lv.header(active_id).name)
    except Exception:
        pass
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

    _checked_modify(scene, "cascadeur-mcp: selection_extend", mod, session=True)
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

    _checked_modify(scene, "cascadeur-mcp: selection_subtract", mod, session=True)
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

    def mod(model, update, sc, session):
        # csc.layers.Editor.set_fixed_interpolation_or_key_if_need(Guid, int, bool)
        model.layers_editor().set_fixed_interpolation_or_key_if_need(lid, frame, True)

    _checked_modify(scene, "cascadeur-mcp: add keyframe", mod, session=True)
    return {"layer_id": layer_id_str, "frame": frame, "added": True}


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

    def mod(model, update, sc, session):
        # csc.layers.Editor.unset_section(pos: int, id: csc.Guid)
        model.layers_editor().unset_section(frame, lid)

    _checked_modify(scene, "cascadeur-mcp: remove keyframe", mod, session=True)
    return {"layer_id": layer_id_str, "frame": frame, "removed": True}


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

    def _extend_mod_s(model, update, sc, session):
        # csc.layers.Editor.set_fixed_interpolation_or_key_if_need(Guid, int, bool)
        editor = model.layers_editor()
        for _lid in list(scene.layers_viewer().all_layer_ids()):
            try:
                editor.set_fixed_interpolation_or_key_if_need(_lid, frame, True)
            except Exception:
                pass

    _checked_modify(scene, "cascadeur-mcp: extend animation for scale", _extend_mod_s, session=True)

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
            # Explicit 3-vector; see _d_keyframe_set for the broadcasting caveat.
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

    _checked_modify(scene, "cascadeur-mcp: set scale", mod, update=True)
    errors = [applied[key] for key in ("error", "run_update_error") if key in applied]
    if errors:
        raise RuntimeError("; ".join(str(err) for err in errors))
    return {
        "controller": controller,
        "obj_id": _id_str(obj_id),
        "applied": applied,
        "attrs_updated": len(actuals_acc),
    }


def _d_active_layer_set(params, scene):
    """Select ``layer_id`` as the timeline's current layer selection.

    2026.2 has no editing-active-layer API (keyframe writes always address each
    object's own layer), so the old tool is mapped onto the closest verified
    concept: the layers selection over the whole animation range. Verified stubs:
      * csc.domain.Scene.data_viewer() / csc.model.DataViewer.get_animation_size()
      * csc.domain.Session.take_layers_selector() -> csc.layers.Selector
      * csc.layers.Selector.set_full_selection_by_parts(list[csc.Guid], int, int)
    """
    layer_id_str = params.get("layer_id")
    if not layer_id_str:
        raise ValueError("'layer_id' is required")
    lid, _ = _resolve_layer(scene, layer_id_str)
    if lid is None:
        raise ValueError(f"layer_id not found: {layer_id_str!r}")

    first_frame, last_frame = _animation_range(scene)

    def mod(model, update, sc, session):
        selector = session.take_layers_selector()
        selector.set_full_selection_by_parts([lid], first_frame, last_frame)

    _checked_modify(scene, "cascadeur-mcp: select layer", mod, session=True)
    return {
        "layer_id": layer_id_str,
        "set": True,
        "frame_range": [first_frame, last_frame],
        "semantics": "timeline-layer-selection",
    }


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

    def mod(model, update, sc, session):
        # csc.layers.Editor.set_fixed_interpolation_or_key_if_need(Guid, int, bool)
        editor = model.layers_editor()
        baked = 0
        for frame in range(frame_start, frame_end + 1):
            editor.set_fixed_interpolation_or_key_if_need(lid, frame, True)
            baked += 1
        out["baked_count"] = baked

    _checked_modify(scene, "cascadeur-mcp: bake range", mod, session=True)
    return out


# ============================================================================
# Schema (introspection cache)
# ============================================================================


# ============================================================================
# Schema (introspection)
# ============================================================================


def _extract_module_schema(module_obj, _seen=None, _depth=0, _max_depth=4):
    """Reflect a module into a JSON-able tree of names, signatures and docs."""
    import inspect

    if _seen is None:
        _seen = set()
    if id(module_obj) in _seen or _depth > _max_depth:
        return {"_truncated": True}
    _seen.add(id(module_obj))

    schema = {}
    for name in dir(module_obj):
        if name.startswith("__"):
            continue
        try:
            attr = getattr(module_obj, name)
        except Exception as e:
            schema[name] = {"type": "unreadable", "error": str(e)}
            continue

        if inspect.ismodule(attr):
            schema[name] = _extract_module_schema(attr, _seen, _depth + 1, _max_depth)
        elif inspect.isclass(attr):
            schema[name] = {
                "type": "class",
                "methods": [m for m in dir(attr) if not m.startswith("__")],
                "doc": (getattr(attr, "__doc__", "") or "").strip(),
            }
        elif callable(attr):
            try:
                sig = str(inspect.signature(attr))
            except (ValueError, TypeError):
                sig = "(...)"
            schema[name] = {
                "type": "function",
                "signature": sig,
                "doc": (getattr(attr, "__doc__", "") or "").strip(),
            }
        else:
            schema[name] = {"type": "value", "repr": _schema_safe_repr(attr)}
    return schema


def _schema_safe_repr(obj):
    try:
        text = repr(obj)
    except Exception:
        return "<unrepresentable>"
    return text if len(text) <= 200 else text[:200] + "..."


def _d_schema_get(params, scene):
    """Return the live csc.* API surface (cached client-side by the MCP server)."""
    import csc

    payload = {
        "csc": _extract_module_schema(csc),
        "runtime_version": RUNTIME_VERSION,
    }
    schema_json = json.dumps(payload, default=str)
    return {
        "schema_json_size": len(schema_json),
        "schema_json": schema_json,
    }


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
    "object_duplicate_finish": _d_object_duplicate_finish,
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


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------


def _d_ping(params, scene):
    """Cheap identity/liveness probe: proves the runtime is loaded and on-thread."""
    return {
        "pong": True,
        "runtime_version": RUNTIME_VERSION,
        "python": sys.version.split()[0],
        "has_scene": scene is not None,
    }


_HANDLERS["ping"] = _d_ping
