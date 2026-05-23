"""Poppet MCP server.

FastMCP frontend that translates Claude's tool calls into commands for the
Cascadeur-side Poppet listener (cascadeur_side/poppet/_listener.py).

Run via: `uvx poppet-mcp` (or `python -m poppet_mcp.server`).

Environment:
  POPPET_HOST  default 127.0.0.1
  POPPET_PORT  default 53145
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from poppet_mcp.cascadeur_connection import CascadeurConnection

mcp = FastMCP("poppet")
_conn: CascadeurConnection | None = None


def _connection() -> CascadeurConnection:
    global _conn
    if _conn is None:
        _conn = CascadeurConnection(
            timeout=float(os.environ.get("POPPET_TIMEOUT", "60")),
            poll_interval=float(os.environ.get("POPPET_POLL_INTERVAL", "0.1")),
        )
    return _conn


def _call(command: str, **params: Any) -> Any:
    return _connection().request(command, params)


# ----------------------------------------------------------------------------
# Core
# ----------------------------------------------------------------------------

@mcp.tool()
def get_scene_info() -> dict:
    """Get basic Cascadeur scene info — name, frame count, fps, whether a scene is open."""
    return _call("scene_info")


@mcp.tool()
def get_selection() -> dict:
    """Get the currently selected objects/controllers in the scene."""
    return _call("selection_get")


@mcp.tool()
def set_selection(object_names: list[str]) -> dict:
    """Replace the current selection with the given object names.

    Reports any names that couldn't be matched in `missing`. Wraps the change
    in a Cascadeur session for undo support.
    """
    return _call("selection_set", object_names=object_names)


@mcp.tool()
def clear_selection() -> dict:
    """Clear the current object selection."""
    return _call("selection_clear")


@mcp.tool()
def list_objects(name_contains: str | None = None) -> dict:
    """List all scene objects (id, name, type). Optional `name_contains` filter."""
    return _call("objects_list", name_contains=name_contains)


@mcp.tool()
def get_current_frame() -> dict:
    """Return the current playhead frame index."""
    return _call("frame_get")


@mcp.tool()
def set_current_frame(frame: int) -> dict:
    """Move the playhead to the given frame index."""
    return _call("frame_set", frame=frame)


@mcp.tool()
def execute_csc_code(code: str) -> dict:
    """Run arbitrary Python in Cascadeur's embedded interpreter.

    `csc` and `scene` are available in the exec namespace. Returns repr of the
    last expression value (if `code` is an expression) or {"repr": "None"} (if a
    statement). Wrap mutations in `scene.modify_with_session(lambda s: ...)` to
    keep undo working.

    Use this as an escape hatch when no higher-level tool fits.
    """
    return _call("exec_csc", code=code)


@mcp.tool()
def call_action(action_id: str) -> dict:
    """Invoke a Cascadeur action by ID (any menu/toolbar command).

    Examples: "Scene.Undo", "File.Save", "AutoPosingTool.AutoPosing",
    "AutoPhysicsTool.Snap to Auto Physics", "Timeline.Play",
    "Viewport.FOV increase".

    Full list: https://cascadeur.com/help/category/301

    Note: actions are fire-and-forget — no return value, no completion signal.
    For AutoPhysics specifically, use `run_autophysics()` which polls for
    convergence after invoking.
    """
    return _call("call_action", action_id=action_id)


# ----------------------------------------------------------------------------
# Animation layers / keyframes
# ----------------------------------------------------------------------------

@mcp.tool()
def list_layers() -> dict:
    """List animation layers (tracks) in the current scene."""
    return _call("layers_list")


@mcp.tool()
def get_keyframes(layer_id: str, frame_start: int, frame_end: int) -> dict:
    """Get keyframes on a layer between frame_start and frame_end (inclusive)."""
    return _call("keyframes_get", layer_id=layer_id,
                 frame_start=frame_start, frame_end=frame_end)


@mcp.tool()
def set_controller_position(
    controller_id: str, frame: int, x: float, y: float, z: float
) -> dict:
    """Set a controller's world-space position at the given frame."""
    return _call("keyframe_set",
                 controller_id=controller_id, frame=frame,
                 transform={"position": [x, y, z]})


@mcp.tool()
def set_controller_rotation(
    controller_id: str, frame: int, qx: float, qy: float, qz: float, qw: float
) -> dict:
    """Set a controller's rotation (quaternion) at the given frame."""
    return _call("keyframe_set",
                 controller_id=controller_id, frame=frame,
                 transform={"rotation": [qx, qy, qz, qw]})


@mcp.tool()
def add_keyframe(layer_id: str, frame: int) -> dict:
    """Add a keyframe at `frame` on `layer_id` (uses current selection)."""
    return _call("keyframe_set",
                 controller_id=None, frame=frame,
                 transform={"add": True, "layer_id": layer_id})


@mcp.tool()
def remove_keyframe(layer_id: str, frame: int) -> dict:
    """Remove the keyframe at `frame` on `layer_id`."""
    return _call("keyframe_set",
                 controller_id=None, frame=frame,
                 transform={"remove": True, "layer_id": layer_id})


# ----------------------------------------------------------------------------
# AutoPosing / AutoPhysics — the spec §4 closed loop
# ----------------------------------------------------------------------------

@mcp.tool()
def run_autoposing() -> dict:
    """Run AutoPosing — resolves natural joint rotations from active control points.

    Near-instant for the current frame. Use after setting sparse milestone
    positions on hip/foot/hand controllers to let Cascadeur fill in plausible
    intermediate joint angles.
    """
    return _call("autopose_run")


@mcp.tool()
def run_autophysics(timeout_sec: float = 30.0) -> dict:
    """Run AutoPhysics across the timeline and wait for convergence.

    Wraps `AutoPhysicsTool.Snap to Auto Physics`. Since action invocations
    return no completion signal, this tool polls scene state and returns when
    stable (or `{"converged": false, "status": "timeout"}` after `timeout_sec`).

    Use this after AutoPosing to apply gravity, floor collisions, and momentum
    to the animation.
    """
    return _call("autophysics_run", timeout_sec=timeout_sec)


@mcp.tool()
def read_telemetry(controller_ids: list[str], frames: list[int]) -> dict:
    """Read world-space positions and rotations of controllers at given frames.

    Closes the spec §4 loop — after AutoPosing + AutoPhysics, read what the
    solver produced and feed the result back to the model so it can correct
    drift or refine timing.
    """
    return _call("telemetry_read",
                 controller_ids=controller_ids, frames=frames)


# ----------------------------------------------------------------------------
# FBX I/O
# ----------------------------------------------------------------------------

@mcp.tool()
def import_fbx(path: str) -> dict:
    """Import an FBX file into the current scene."""
    return _call("fbx_import", path=path)


@mcp.tool()
def export_fbx(path: str) -> dict:
    """Export the current scene to an FBX file."""
    return _call("fbx_export", path=path)


# ----------------------------------------------------------------------------
# Resources
# ----------------------------------------------------------------------------

@mcp.resource("csc://schema")
def csc_schema() -> str:
    """Live-introspected csc.* signature JSON from the user's actual Cascadeur install.

    Use this as ground truth for the csc API surface — the help-site docs lag,
    this doesn't. Generated by the `Poppet → Refresh Schema` command (and
    cached at first read).
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
