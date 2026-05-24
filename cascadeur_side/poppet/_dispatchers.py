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

import json
import os
import time
import traceback


def dispatch(message, scene):
    """Route a single request to its handler and wrap the response."""
    cmd_type = message.get("type")
    params = message.get("params") or {}
    handler = _HANDLERS.get(cmd_type)
    if handler is None:
        return {"status": "error", "message": "unknown command: {!r}".format(cmd_type)}
    try:
        result = handler(params, scene)
        return {"status": "success", "result": result}
    except Exception as e:
        return {
            "status": "error",
            "message": "{}: {}".format(type(e).__name__, e),
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
        return {"layers": [], "error": "all_layer_ids() failed: {}".format(e)}

    for lid in layer_ids:
        info = {"id": _id_str(lid)}
        try:
            layer = lv.layer(lid)
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
        raise ValueError("layer_id not found: {!r}".format(layer_id_str))

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
        raise ValueError("controller not found by name or id: {!r}".format(controller))

    pos_node_name = "Local Position" if use_local else "Position"
    rot_node_name = "Local Rotation" if use_local else "Rotation"

    actuals_acc = []
    applied = {"position": False, "rotation": False, "frame": frame}

    def mod(model, update, scene_updater):
        actuals = set()
        try:
            node = update.get_object_by_id(obj_id).root_group()
        except Exception as e:
            applied["error"] = "get_object_by_id failed: {}".format(e)
            return

        if position is not None:
            try:
                pos_attr = node.node_deep(pos_node_name)
                if pos_attr is None:
                    applied["position_error"] = "node {!r} not on {!r}".format(pos_node_name, controller)
                else:
                    current = pos_attr.value(frame)
                    if current is not None:
                        # Type-preserving: delta from current keeps Vec3-like type.
                        delta = [float(position[0]) - float(current[0]),
                                 float(position[1]) - float(current[1]),
                                 float(position[2]) - float(current[2])]
                        new_pos = current + delta
                    else:
                        new_pos = [float(position[0]), float(position[1]), float(position[2])]
                    pos_attr.set_value(new_pos, frame)
                    actuals.add(pos_attr.data_id())
                    applied["position"] = True
                    applied["position_new"] = _vec_to_list(new_pos)
            except Exception as e:
                applied["position_error"] = "{}: {}".format(type(e).__name__, e)

        if rotation_quat is not None:
            try:
                rot_attr = node.node_deep(rot_node_name)
                if rot_attr is None:
                    applied["rotation_error"] = "node {!r} not on {!r}".format(rot_node_name, controller)
                else:
                    qx, qy, qz, qw = (float(x) for x in rotation_quat)
                    euler = _quat_to_euler_xyz(qx, qy, qz, qw)
                    rot_val = csc.math.Rotation.from_euler(euler)
                    rot_attr.set_value(rot_val, frame)
                    actuals.add(rot_attr.data_id())
                    applied["rotation"] = True
            except Exception as e:
                applied["rotation_error"] = "{}: {}".format(type(e).__name__, e)

        actuals_acc.extend(actuals)
        if actuals:
            try:
                scene_updater.run_update(actuals, frame)
            except Exception as e:
                applied["run_update_error"] = "{}: {}".format(type(e).__name__, e)

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
                telemetry[label] = {"error": "get_object_by_id: {}".format(e)}
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
                            entry["rotation"] = [
                                float(getattr(q, "x", 0)),
                                float(getattr(q, "y", 0)),
                                float(getattr(q, "z", 0)),
                                float(getattr(q, "w", 1)),
                            ]
                        except Exception:
                            # Fallback: convert via euler
                            try:
                                e_ang = r.to_euler_angles()
                                entry["rotation_euler"] = _vec_to_list(e_ang) or [
                                    float(e_ang[0]), float(e_ang[1]), float(e_ang[2])
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
        raise ValueError("'path' must be absolute: {!r}".format(path))
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
        "settings": {"mode": "Binary", "up_axis": "Y",
                     "bake_animation": True, "apply_euler_filter": True},
    }


def _d_fbx_import(params, scene):
    """Import an FBX file into the current scene without a dialog."""
    import os
    path = params.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("'path' must be a non-empty string")
    if not os.path.exists(path):
        raise ValueError("FBX file not found: {!r}".format(path))
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
    """Attempt to move the playhead. KNOWN BUG: in Cascadeur 2025.3.3 neither
    scene.set_current_frame() nor session.set_current_frame() actually persist
    the playhead — both accept the value but get_current_frame() still returns
    the prior frame. The real playhead setter is likely on csc.view.Scene's
    animation_boundary or requires a UI message dispatch we haven't found.

    Returns the post-call get to surface whether the change stuck.
    Use call_action with a Timeline.* action ID as a workaround until resolved.
    """
    frame = int(params["frame"])
    # Try direct (no session); session-based had the same issue.
    scene.set_current_frame(frame)
    actual = scene.get_current_frame()
    return {
        "requested": frame,
        "current_frame": actual,
        "persisted": actual == frame,
        "note": "see _dispatchers.py _d_frame_set docstring for the known issue" if actual != frame else None,
    }


# ============================================================================
# Schema (introspection cache)
# ============================================================================

def _d_schema_get(params, scene):
    from . import _introspect
    path = _introspect.schema_cache_path()
    if not os.path.exists(path):
        _introspect.dump_schema(path)
    with open(path, "r", encoding="utf-8") as f:
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
}
