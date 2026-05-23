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
    """Stub — needs DataEditor + per-controller mutation. Use exec_csc for now."""
    return {
        "applied": False,
        "note": (
            "Not yet wired. Use execute_csc_code with a session-based mutation that "
            "calls model.data_editor().set_data_value(data_id, frame, value) — see "
            "cascadeur bundled commands like restore_values.py for the pattern."
        ),
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
    """Read controller transforms at given frames.

    Stub for now — proper implementation needs csc.update / pycsc.TransformUpdate
    to read global world transforms. Pattern is in go_to_default_pose.py.
    """
    controller_ids = params.get("controller_ids", [])
    frames = params.get("frames", [])
    return {
        "controller_ids": controller_ids,
        "frames": frames,
        "telemetry": {},
        "note": (
            "Not yet wired. Use execute_csc_code with pycsc.TransformUpdate(obj_id, py_scene) "
            "and node.get_global_orto_transform() to read world transforms — see "
            "go_to_default_pose.py for the pattern."
        ),
    }


# ============================================================================
# FBX I/O
# ============================================================================

def _d_fbx_import(params, scene):
    path = params.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("'path' must be a non-empty string")
    import csc
    am = csc.app.get_application().get_action_manager()
    am.call_action("File.Import.Animation.Fbx...")
    return {
        "path": path,
        "invoked": "File.Import.Animation.Fbx...",
        "note": "Dialog-based action — pre-set default-FBX path with DefaultFbxSynchronization for headless.",
    }


def _d_fbx_export(params, scene):
    path = params.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("'path' must be a non-empty string")
    import csc
    am = csc.app.get_application().get_action_manager()
    am.call_action("File.Export.Scene.Fbx...")
    return {
        "path": path,
        "invoked": "File.Export.Scene.Fbx...",
        "note": "Dialog-based action — pre-set default-FBX path with DefaultFbxSynchronization for headless.",
    }


# ============================================================================
# Frame / playhead
# ============================================================================

def _d_frame_get(params, scene):
    return {"current_frame": scene.get_current_frame()}


def _d_frame_set(params, scene):
    frame = int(params["frame"])

    def mod(model, update, sc, session):
        session.set_current_frame(frame)

    scene.modify_with_session("Poppet: set current frame", mod)
    return {"current_frame": frame}


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
