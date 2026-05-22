"""Command dispatchers — one function per Poppet wire command.

Runs inside Cascadeur's embedded Python 3.8 interpreter on the Qt main thread.
Mutations should be wrapped in `scene.modify_with_session(...)` for undo safety.

Many dispatchers below are best-effort scaffolding marked TODO — the csc.* API
surface is uneven and the cleanest way to verify method names is against a live
install. Refine these as they get exercised.
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
# Core
# ============================================================================

def _d_echo(params, scene):
    return params


def _d_exec_csc(params, scene):
    """Run arbitrary Python in Cascadeur's interpreter. Escape hatch."""
    code = params.get("code", "")
    if not isinstance(code, str):
        raise ValueError("'code' must be a string")
    import csc  # noqa: F401 — available in exec namespace
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
    """Return basic scene metadata. Defensive — csc surface is uneven."""
    import csc
    info = {"has_scene": False}
    try:
        app = csc.app.get_application()
        cur = app.current_scene()
        info["has_scene"] = True
        info["scene_repr"] = _safe_repr(cur)
        try:
            ds = cur.domain_scene()
            info["domain_scene_repr"] = _safe_repr(ds)
            # Best-effort frame/fps probe — method names vary by version
            for fn_name in ("get_frame_count", "frame_count", "frames"):
                if hasattr(ds, fn_name):
                    try:
                        info["frame_count"] = getattr(ds, fn_name)()
                        break
                    except Exception:
                        pass
            for fn_name in ("fps", "get_fps", "frame_rate"):
                if hasattr(ds, fn_name):
                    try:
                        info["fps"] = getattr(ds, fn_name)()
                        break
                    except Exception:
                        pass
        except Exception:
            pass
    except Exception as e:
        info["error"] = str(e)
    return info


# ============================================================================
# Selection
# ============================================================================

def _d_selection_get(params, scene):
    # TODO: verify against live install — selection API lives in csc.model or csc.domain.
    import csc
    result = {"selected": [], "raw": None}
    try:
        app = csc.app.get_application()
        cur = app.current_scene()
        # Common selection access patterns — try in order
        for path in (("selector",), ("get_selector",), ("selection",)):
            obj = cur
            try:
                for p in path:
                    obj = getattr(obj, p)
                    if callable(obj):
                        obj = obj()
                result["raw"] = _safe_repr(obj)
                if hasattr(obj, "selected"):
                    sel = obj.selected()
                    result["selected"] = [_safe_repr(s) for s in sel]
                break
            except Exception:
                continue
    except Exception as e:
        result["error"] = str(e)
    return result


def _d_selection_set(params, scene):
    object_names = params.get("object_names", [])
    if not isinstance(object_names, list):
        raise ValueError("'object_names' must be a list")
    # TODO: real implementation depends on csc selection API specifics
    return {"requested": object_names, "applied": False, "note": "not yet implemented — exec_csc as workaround"}


# ============================================================================
# Animation layers / keyframes
# ============================================================================

def _d_layers_list(params, scene):
    # TODO: csc.layers API access pattern needs live verification.
    import csc
    result = {"layers": [], "raw": None}
    try:
        app = csc.app.get_application()
        cur = app.current_scene()
        result["raw"] = _safe_repr(getattr(cur, "layers", lambda: None)() if hasattr(cur, "layers") else None)
    except Exception as e:
        result["error"] = str(e)
    return result


def _d_keyframes_get(params, scene):
    layer_id = params.get("layer_id")
    frame_start = int(params.get("frame_start", 0))
    frame_end = int(params.get("frame_end", 0))
    return {
        "layer_id": layer_id,
        "frame_start": frame_start,
        "frame_end": frame_end,
        "keyframes": [],
        "note": "TODO: implement against csc.layers — use exec_csc as workaround",
    }


def _d_keyframe_set(params, scene):
    controller_id = params.get("controller_id")
    frame = int(params.get("frame", 0))
    transform = params.get("transform") or {}
    return {
        "controller_id": controller_id,
        "frame": frame,
        "transform": transform,
        "applied": False,
        "note": "TODO: implement against csc.layers + csc.model — use exec_csc as workaround",
    }


# ============================================================================
# AutoPosing / AutoPhysics (spec §4 closed loop)
# ============================================================================

def _d_autopose_run(params, scene):
    """Wrap AutoPosingTool.AutoPosing. Near-instant for current frame."""
    import csc
    app = csc.app.get_application()
    am = app.get_action_manager()
    am.call_action("AutoPosingTool.AutoPosing")
    return {"invoked": "AutoPosingTool.AutoPosing"}


def _d_autophysics_run(params, scene):
    """Wrap AutoPhysicsTool.Snap to Auto Physics — solves asynchronously.

    Polls for convergence by reading a coarse scene-state hash before and after,
    waiting up to `timeout_sec` for stability.
    """
    import csc
    timeout_sec = float(params.get("timeout_sec", 30.0))
    poll_interval = float(params.get("poll_interval", 0.25))

    app = csc.app.get_application()
    am = app.get_action_manager()
    am.call_action("AutoPhysicsTool.Snap to Auto Physics")

    # Poll for convergence — coarse heuristic since call_action returns no signal.
    deadline = time.time() + timeout_sec
    last_hash = _scene_state_hash(app)
    stable_for = 0.0
    while time.time() < deadline:
        time.sleep(poll_interval)
        h = _scene_state_hash(app)
        if h == last_hash:
            stable_for += poll_interval
            if stable_for >= 0.5:
                return {"invoked": "AutoPhysicsTool.Snap to Auto Physics", "converged": True}
        else:
            stable_for = 0.0
            last_hash = h
    return {"invoked": "AutoPhysicsTool.Snap to Auto Physics", "converged": False, "status": "timeout"}


def _scene_state_hash(app):
    """Coarse fingerprint of current scene state — used for convergence detection."""
    try:
        cur = app.current_scene()
        return hash(_safe_repr(cur.domain_scene()))
    except Exception:
        return 0


def _d_telemetry_read(params, scene):
    controller_ids = params.get("controller_ids", [])
    frames = params.get("frames", [])
    return {
        "controller_ids": controller_ids,
        "frames": frames,
        "telemetry": {},
        "note": "TODO: implement world-space transform reads against csc.layers",
    }


# ============================================================================
# FBX I/O
# ============================================================================

def _d_fbx_import(params, scene):
    path = params.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("'path' must be a non-empty string")
    import csc
    app = csc.app.get_application()
    am = app.get_action_manager()
    # NOTE: action-based import uses last-used dialog state. For programmatic import,
    # prefer csc.fbx.FbxIO if available — needs live verification.
    am.call_action("File.Import.Animation.Fbx...")
    return {"path": path, "invoked": "File.Import.Animation.Fbx...",
            "note": "may require dialog interaction depending on Cascadeur version"}


def _d_fbx_export(params, scene):
    path = params.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("'path' must be a non-empty string")
    import csc
    app = csc.app.get_application()
    am = app.get_action_manager()
    am.call_action("File.Export.Scene.Fbx...")
    return {"path": path, "invoked": "File.Export.Scene.Fbx...",
            "note": "may require dialog interaction depending on Cascadeur version"}


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
    return {"path": path, "schema_json": schema_json}


# ============================================================================
# Dispatch table
# ============================================================================

_HANDLERS = {
    "echo": _d_echo,
    "exec_csc": _d_exec_csc,
    "call_action": _d_call_action,
    "scene_info": _d_scene_info,
    "selection_get": _d_selection_get,
    "selection_set": _d_selection_set,
    "layers_list": _d_layers_list,
    "keyframes_get": _d_keyframes_get,
    "keyframe_set": _d_keyframe_set,
    "autopose_run": _d_autopose_run,
    "autophysics_run": _d_autophysics_run,
    "telemetry_read": _d_telemetry_read,
    "fbx_import": _d_fbx_import,
    "fbx_export": _d_fbx_export,
    "schema_get": _d_schema_get,
}


def _safe_repr(obj):
    try:
        r = repr(obj)
        return r if len(r) <= 500 else r[:500] + "..."
    except Exception:
        return "<unrepresentable>"
