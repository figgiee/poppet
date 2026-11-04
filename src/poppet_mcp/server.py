"""cascadeur-mcp MCP server — the tool layer for Cascadeur 2026.2+.

Runs as a normal stdio MCP server (``cascadeur-mcp``) next to any MCP client. Every
tool call is translated into a JSON command and handed to cascadeur-mcp's in-app runtime
running inside Cascadeur, via Cascadeur's **built-in** MCP script server
(``Scripts -> MCP -> Start script server``, loopback HTTP on port 8765).

There is no Cascadeur-side install: on the first call the connection layer ships
the runtime source (``poppet_mcp/runtime/inapp.py``) into Cascadeur and executes
it as a private module. See ``docs/architecture.md`` for the full story.

Environment:
  POPPET_URL      default http://127.0.0.1:8765
  POPPET_TIMEOUT  default 35 seconds (the script server caps a call at ~30s)
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from poppet_mcp import __version__
from poppet_mcp.cascadeur_connection import CascadeurConnection
from poppet_mcp.runtime import runtime_version

mcp = FastMCP("cascadeur-mcp")
# Report the real package version in the MCP handshake when the SDK allows it.
try:  # pragma: no cover - depends on the installed MCP SDK internals
    mcp._mcp_server.version = __version__
except Exception:  # pragma: no cover
    pass
_conn: CascadeurConnection | None = None


def _connection() -> CascadeurConnection:
    global _conn
    if _conn is None:
        _conn = CascadeurConnection(
            timeout=float(os.environ.get("POPPET_TIMEOUT", "35")),
            url=os.environ.get("POPPET_URL") or None,
        )
    return _conn


def _call(command: str, **params: Any) -> Any:
    """Send one command to the in-app runtime and return its result payload."""
    return _connection().request(command, params)


# ----------------------------------------------------------------------------
# Diagnostics
# ----------------------------------------------------------------------------


@mcp.tool()
def get_script_server_status() -> dict:
    """Check the cascadeur-mcp <-> Cascadeur link and report both sides' versions.

    Returns ``connected`` (bool), the loopback ``url``, the script server's
    ``server_version``, the loaded in-app ``runtime_version``, the embedded
    ``python`` version, and ``has_scene``. When the link is down, ``error``
    carries the actionable reason (usually: start the script server in Cascadeur).
    """
    connection = _connection()
    status: dict[str, Any] = {
        "connected": False,
        "url": connection.url,
        "expected_runtime_version": runtime_version(),
    }
    try:
        health = connection.health()
    except Exception as exc:
        status["error"] = str(exc)
        return status
    status["connected"] = True
    status["server_version"] = health.get("version")
    status["queued"] = health.get("queued")
    try:
        status.update(connection.request("ping"))
    except Exception as exc:
        status["ping_error"] = str(exc)
    return status


@mcp.tool()
def run_script(code: str) -> dict:
    """Run raw Python inside Cascadeur and return the script server's raw reply.

    This is the untyped escape hatch and the lowest-level tool: it submits
    ``code`` straight to Cascadeur's built-in script server, which executes it on
    the next ``scene_idle`` event with ``csc``, ``scene`` and ``app`` in scope.
    An expression's value is returned ``repr``-encoded in ``value``.

    Returns the script server's own response dict:
    ``{"ok": bool, "value": str, "messages": [...], "error": str?}``.
    Failures (including Python tracebacks) come back with ``ok: false`` — they
    are raised in-app while the HTTP call still succeeds.

    Cascadeur caps a call at roughly 30 seconds, so keep scripts short. Prefer
    the typed tools; use this for discovery or one-off operations.
    """
    return _connection().run_script(code)


# ----------------------------------------------------------------------------
# Core scene / selection
# ----------------------------------------------------------------------------


@mcp.tool()
def get_scene_info() -> dict:
    """Get scene summary: name, frame range, current frame, object and layer counts."""
    return _call("scene_info")


@mcp.tool()
def get_selection() -> dict:
    """List the currently selected objects/controllers (id, name, type)."""
    return _call("selection_get")


@mcp.tool()
def set_selection(object_names: list[str]) -> dict:
    """Replace the current selection with the given object names.

    Missing names are reported in ``missing``; the change is wrapped in a
    Cascadeur session so it participates in undo.
    """
    return _call("selection_set", object_names=object_names)


@mcp.tool()
def clear_selection() -> dict:
    """Clear the current object selection."""
    return _call("selection_clear")


@mcp.tool()
def list_objects(name_contains: str | None = None) -> dict:
    """List scene objects as ``{id, name, type}``, optionally filtered by substring."""
    return _call("objects_list", name_contains=name_contains)


@mcp.tool()
def get_current_frame() -> dict:
    """Return the playhead frame index."""
    return _call("frame_get")


@mcp.tool()
def set_current_frame(frame: int) -> dict:
    """Move the playhead to ``frame``.

    Readback of ``current_frame`` can lag one drain behind the visual playhead;
    trust the viewport, not the number, immediately after the call.
    """
    return _call("frame_set", frame=frame)


@mcp.tool()
def call_action(action_id: str) -> dict:
    """Invoke any Cascadeur menu/toolbar action by its ID.

    Examples: ``Scene.Undo``, ``File.Save``, ``AutoPosingTool.AutoPosing``,
    ``AutoPhysicsTool.Snap to Auto Physics``. Actions are fire-and-forget: there
    is no completion signal. Use ``run_autophysics()`` when you need to wait for
    a solver to finish. Action ID catalog: https://cascadeur.com/help/category/301
    """
    return _call("call_action", action_id=action_id)


@mcp.tool()
def execute_csc_code(code: str) -> dict:
    """Execute Python in Cascadeur's embedded interpreter (typed escape hatch).

    Runs through cascadeur-mcp's in-app runtime, so ``csc`` and ``scene`` are available.
    Returns the expression value (or ``None`` for statements). Prefer ``run_script``
    if you want the script server's raw response instead, and wrap mutations in
    ``scene.modify_with_session(...)`` to keep undo working.
    """
    return _call("exec_csc", code=code)


# ----------------------------------------------------------------------------
# Layers and keyframes
# ----------------------------------------------------------------------------


@mcp.tool()
def list_layers() -> dict:
    """List animation layers with their ids, names and keyframe counts."""
    return _call("layers_list")


@mcp.tool()
def get_keyframes(layer_id: str, frame_start: int, frame_end: int) -> dict:
    """Return the keyframe frames on ``layer_id`` inside the inclusive range."""
    return _call("keyframes_get", layer_id=layer_id, frame_start=frame_start, frame_end=frame_end)


@mcp.tool()
def set_controller_position(controller_id: str, frame: int, x: float, y: float, z: float) -> dict:
    """Set a controller's world-space position at ``frame`` (creates a key)."""
    return _call(
        "keyframe_set",
        controller_id=controller_id,
        frame=frame,
        transform={"position": [x, y, z]},
    )


@mcp.tool()
def set_controller_rotation(
    controller_id: str, frame: int, qx: float, qy: float, qz: float, qw: float
) -> dict:
    """Set a controller's rotation as a quaternion ``(x, y, z, w)`` at ``frame``."""
    return _call(
        "keyframe_set",
        controller_id=controller_id,
        frame=frame,
        transform={"rotation": [qx, qy, qz, qw]},
    )


@mcp.tool()
def set_controller_scale(
    controller_id: str,
    frame: int,
    sx: float,
    sy: float,
    sz: float,
    local: bool = True,
) -> dict:
    """Set a controller's scale at ``frame`` (useful for stretchy IK targets)."""
    return _call(
        "controller_scale_set",
        controller_id=controller_id,
        frame=frame,
        scale=[sx, sy, sz],
        local=local,
    )


@mcp.tool()
def add_keyframe(layer_id: str, frame: int) -> dict:
    """Add a keyframe on ``layer_id`` at ``frame`` using fixed interpolation."""
    return _call("keyframe_add", layer_id=layer_id, frame=frame)


@mcp.tool()
def remove_keyframe(layer_id: str, frame: int) -> dict:
    """Remove the keyframe at ``frame`` on ``layer_id``."""
    return _call("keyframe_remove", layer_id=layer_id, frame=frame)


@mcp.tool()
def bake_range(layer_id: str, frame_start: int, frame_end: int) -> dict:
    """Bake per-frame keys across an inclusive range on ``layer_id``.

    Converts interpolated motion into discrete keys — use after procedurally
    modifying an interval, before exporting.
    """
    return _call("bake_range", layer_id=layer_id, frame_start=frame_start, frame_end=frame_end)


# ----------------------------------------------------------------------------
# Telemetry
# ----------------------------------------------------------------------------


@mcp.tool()
def read_telemetry(controller_ids: list[str], frames: list[int]) -> dict:
    """Read position + rotation (Euler) of controllers at specific frames.

    The feedback half of the AutoPosing/AutoPhysics loop: read what the solver
    produced, then correct drift or timing.
    """
    return _call("telemetry_read", controller_ids=controller_ids, frames=frames)


@mcp.tool()
def read_telemetry_range(
    controller_ids: list[str],
    frame_start: int,
    frame_end: int,
    step: int = 1,
    local: bool = True,
) -> dict:
    """Read controller transforms across a frame range in one update-graph walk.

    ``step`` samples every Nth frame; endpoints are inclusive. Much cheaper than
    calling ``read_telemetry`` once per frame.
    """
    return _call(
        "telemetry_read_range",
        controller_ids=controller_ids,
        frame_start=frame_start,
        frame_end=frame_end,
        step=step,
        local=local,
    )


@mcp.tool()
def get_object_transform(object_name: str, frame: int = 0, local: bool = True) -> dict:
    """Read Position + Rotation + Scale for one object at ``frame``."""
    return _call("object_transform_get", object_name=object_name, frame=frame, local=local)


@mcp.tool()
def list_object_attributes(object_name: str) -> dict:
    """List every attribute node on an object's root group.

    Discovery aid: tells you which attributes (Position, Rotation, Local Scale,
    IK weights, ...) exist before you address one in ``execute_csc_code``.
    """
    return _call("object_attributes_list", object_name=object_name)


# ----------------------------------------------------------------------------
# AutoPosing / AutoPhysics
# ----------------------------------------------------------------------------


@mcp.tool()
def run_autoposing() -> dict:
    """Run AutoPosing on the current frame.

    Resolves natural joint rotations from the active control points. Near-instant
    per frame: set sparse milestone hips/hands/feet, then autopose.
    """
    return _call("autopose_run")


@mcp.tool()
def run_autophysics(timeout_sec: float = 30.0) -> dict:
    """Run AutoPhysics across the timeline and report convergence.

    Wraps ``AutoPhysicsTool.Snap to Auto Physics`` and polls scene state until it
    stabilises, or returns ``{"converged": false, "status": "timeout"}``.
    Keep ``timeout_sec`` under the script server's ~30s per-call cap (~25s is a
    safe budget); for longer solves, call again or use the timestamped
    ``Scene.SnapToPhysics*`` actions with ``call_action``.
    """
    return _call("autophysics_run", timeout_sec=timeout_sec)


# ----------------------------------------------------------------------------
# FBX I/O
# ----------------------------------------------------------------------------


@mcp.tool()
def import_fbx(path: str, target: str = "scene") -> dict:
    """Import an FBX file.

    ``target="scene"`` loads the whole file as scene contents;
    ``target="animation"`` imports animation only into the current scene.
    """
    return _call("fbx_import", path=path, target=target)


@mcp.tool()
def export_fbx(path: str) -> dict:
    """Export the current scene to a binary FBX (baked animation, Y-up).

    Large scenes can exceed the script server's ~30s call cap. If the call times
    out the export may still be in progress — check the file before retrying.
    """
    return _call("fbx_export", path=path)


# ----------------------------------------------------------------------------
# Scene file I/O
# ----------------------------------------------------------------------------


@mcp.tool()
def save_scene(path: str) -> dict:
    """Save the current scene to a ``.casc`` file.

    Cascadeur writes large scenes asynchronously, so this tool waits briefly for
    the file to hit disk before returning ``exists``/``size_bytes``.
    """
    import time
    from pathlib import Path

    result = _call("save_scene", path=path)
    target = result.get("path") if isinstance(result, dict) else None
    if target and not result.get("exists"):
        deadline = time.monotonic() + 10.0
        candidate = Path(target)
        while time.monotonic() < deadline:
            if candidate.exists():
                result["exists"] = True
                result["size_bytes"] = candidate.stat().st_size
                result["save_pending"] = False
                break
            time.sleep(0.1)
    return result


@mcp.tool()
def load_scene(path: str) -> dict:
    """Open a ``.casc`` file, replacing the current scene."""
    return _call("load_scene", path=path)


@mcp.tool()
def new_scene() -> dict:
    """Create a fresh empty scene."""
    return _call("new_scene")


# ----------------------------------------------------------------------------
# Hierarchy
# ----------------------------------------------------------------------------


@mcp.tool()
def get_object_hierarchy() -> dict:
    """Return the object hierarchy as ``{id, name, parent_id, child_ids}`` rows.

    Use it to understand the rig structure — which controllers attach to which
    joints — without introspecting ``csc.*`` by hand.
    """
    return _call("object_hierarchy")


# ----------------------------------------------------------------------------
# Layer state
# ----------------------------------------------------------------------------


@mcp.tool()
def set_layer_visible(layer_id: str, visible: bool) -> dict:
    """Show/hide an animation layer."""
    return _call("layer_visible_set", layer_id=layer_id, visible=visible)


@mcp.tool()
def set_layer_locked(layer_id: str, locked: bool) -> dict:
    """Lock/unlock an animation layer against edits."""
    return _call("layer_locked_set", layer_id=layer_id, locked=locked)


@mcp.tool()
def add_layer(name: str, parent_id: str | None = None) -> dict:
    """Create a new animation layer under the scene root (or ``parent_id``)."""
    return _call("layer_add", name=name, parent_id=parent_id)


@mcp.tool()
def delete_layer(layer_id: str) -> dict:
    """Delete an animation layer by id."""
    return _call("layer_delete", layer_id=layer_id)


@mcp.tool()
def get_active_layer() -> dict:
    """Return the timeline layer selection (layer-editor semantics).

    Cascadeur 2026.2 has no separate "active editing layer" object; cascadeur-mcp maps
    this tool to the timeline layers selection: the included layer ids plus the
    top layer. Responses carry ``"semantics": "timeline-layer-selection"`` with
    layer ids, names and key counts.
    """
    return _call("active_layer_get")


@mcp.tool()
def set_active_layer(layer_id: str) -> dict:
    """Select a single timeline layer (see ``get_active_layer``).

    Replaces the timeline layer selection with ``layer_id``; timeline keyframes
    then land on that layer. Same ``"semantics": "timeline-layer-selection"``
    contract.
    """
    return _call("active_layer_set", layer_id=layer_id)


# ----------------------------------------------------------------------------
# Object edit
# ----------------------------------------------------------------------------


@mcp.tool()
def delete_object(object_name: str) -> dict:
    """Delete an object (and its subtree) by name."""
    return _call("object_delete", object_name=object_name)


@mcp.tool()
def duplicate_object(object_name: str) -> dict:
    """Duplicate an object and return the newly created object names.

    Two dispatches: 2026.2.3's bundled duplicate command needs the selection made in a
    previous scene update, so the tool selects first and then runs the command.
    """
    _call("object_duplicate", object_name=object_name)
    return _call("object_duplicate_finish", object_name=object_name)


# ----------------------------------------------------------------------------
# Selection helpers
# ----------------------------------------------------------------------------


@mcp.tool()
def selection_filter(pattern: str, mode: str = "contains") -> dict:
    """Replace the selection with objects whose name matches ``pattern``.

    ``mode`` is one of ``contains`` (default), ``prefix``, ``suffix``, ``regex``.
    Handy for batch work, e.g. ``selection_filter("_Box", "suffix")`` selects
    every box controller.
    """
    return _call("selection_filter", pattern=pattern, mode=mode)


@mcp.tool()
def selection_extend(object_names: list[str]) -> dict:
    """Add names to the current selection (set union); reports ``missing`` names."""
    return _call("selection_extend", object_names=object_names)


@mcp.tool()
def selection_subtract(object_names: list[str]) -> dict:
    """Remove names from the current selection (set difference)."""
    return _call("selection_subtract", object_names=object_names)


# ----------------------------------------------------------------------------
# Undo / viewport
# ----------------------------------------------------------------------------


@mcp.tool()
def undo() -> dict:
    """Invoke Cascadeur's undo (``Scene.Undo``)."""
    return _call("undo")


@mcp.tool()
def redo() -> dict:
    """Invoke Cascadeur's redo (``Scene.Redo``)."""
    return _call("redo")


@mcp.tool()
def screenshot_viewport(path: str | None = None, wait_sec: float = 10.0) -> dict:
    """Capture the 3D viewport to a PNG and return the written path/size.

    If ``path`` is omitted a timestamped file is generated. Cascadeur renders
    asynchronously, so this tool submits the render and waits up to ``wait_sec``
    for the file to appear before returning ``exists``/``size_bytes``.
    """
    result = _call("viewport_screenshot", path=path)
    target = result.get("path") if isinstance(result, dict) else None
    if target and not result.get("exists"):
        import time
        from pathlib import Path

        deadline = time.monotonic() + max(0.0, wait_sec)
        candidate = Path(target)
        while time.monotonic() < deadline:
            if candidate.exists():
                result["exists"] = True
                result["size_bytes"] = candidate.stat().st_size
                break
            time.sleep(0.1)
    return result


# ----------------------------------------------------------------------------
# Resources
# ----------------------------------------------------------------------------


@mcp.resource("csc://schema")
def csc_schema() -> str:
    """Live ``csc.*`` API surface from the running Cascadeur, as JSON.

    Dumped by cascadeur-mcp's in-app runtime at read time, so it matches the exact
    Cascadeur version you are driving — use it as ground truth for any
    ``execute_csc_code`` / ``run_script`` work.
    """
    result = _call("schema_get")
    return result.get("schema_json", "{}")


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
