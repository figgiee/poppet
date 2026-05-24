"""Tests for the MCP server tool surface.

These tests verify that:
  1. All advertised tools register on the FastMCP instance.
  2. Each tool's signature matches the dispatcher it forwards to.
  3. CascadeurConnection.request is called with the right command name +
     params for each tool (we don't drive a real Cascadeur — that's the
     job of the mcp_smoke_test + the manual demos).

We monkeypatch poppet_mcp.server._connection() to return a stub that
records calls, so we can assert on what each @mcp.tool() forwards.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# The MCP server module reads POPPET_TIMEOUT etc. at first _call invocation
# but we never let it reach that path because we stub _connection() instead.


@pytest.fixture
def stub_conn(monkeypatch):
    """Replace server._connection() with a stub that records request() calls."""
    from poppet_mcp import server as srv

    stub = MagicMock(name="stub-conn")
    stub.request = MagicMock(return_value={"ok": True})

    monkeypatch.setattr(srv, "_connection", lambda: stub)
    return stub, srv


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def test_at_least_38_tools_registered():
    """v0.3 ships 39 tools (36 from v0.2 + 3 layer/selection adds). Future
    minors must NOT regress below 38.
    """
    import asyncio

    from poppet_mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    assert len(tools) >= 38, f"only {len(tools)} tools: {[t.name for t in tools]}"


def test_csc_schema_resource_registered():
    """The csc://schema MCP resource must be advertised."""
    import asyncio

    from poppet_mcp.server import mcp

    resources = asyncio.run(mcp.list_resources())
    uris = [str(r.uri) for r in resources]
    assert any("csc://schema" in u for u in uris), f"missing csc://schema: {uris}"


# ---------------------------------------------------------------------------
# Tool -> dispatcher routing
# ---------------------------------------------------------------------------


def test_get_scene_info_forwards_to_scene_info(stub_conn):
    stub, srv = stub_conn
    srv.get_scene_info()
    stub.request.assert_called_once_with("scene_info", {})


def test_set_selection_forwards_object_names(stub_conn):
    stub, srv = stub_conn
    srv.set_selection(object_names=["pelvis_Box", "foot_Box_l"])
    stub.request.assert_called_once_with(
        "selection_set", {"object_names": ["pelvis_Box", "foot_Box_l"]}
    )


def test_set_controller_position_packs_xyz_into_transform(stub_conn):
    stub, srv = stub_conn
    srv.set_controller_position(controller_id="pelvis_Box", frame=0, x=0.0, y=0.0, z=30.0)
    stub.request.assert_called_once_with(
        "keyframe_set",
        {
            "controller_id": "pelvis_Box",
            "frame": 0,
            "transform": {"position": [0.0, 0.0, 30.0]},
        },
    )


def test_set_controller_rotation_packs_quat_into_transform(stub_conn):
    stub, srv = stub_conn
    srv.set_controller_rotation(controller_id="pelvis_Box", frame=0, qx=0.0, qy=0.0, qz=0.0, qw=1.0)
    stub.request.assert_called_once_with(
        "keyframe_set",
        {
            "controller_id": "pelvis_Box",
            "frame": 0,
            "transform": {"rotation": [0.0, 0.0, 0.0, 1.0]},
        },
    )


def test_run_autophysics_passes_timeout(stub_conn):
    stub, srv = stub_conn
    srv.run_autophysics(timeout_sec=10)
    stub.request.assert_called_once_with("autophysics_run", {"timeout_sec": 10})


def test_export_fbx_forwards_path(stub_conn):
    stub, srv = stub_conn
    srv.export_fbx(path="C:/tmp/out.fbx")
    stub.request.assert_called_once_with("fbx_export", {"path": "C:/tmp/out.fbx"})


def test_import_fbx_passes_target_default_scene(stub_conn):
    stub, srv = stub_conn
    srv.import_fbx(path="C:/in.fbx")
    stub.request.assert_called_once_with("fbx_import", {"path": "C:/in.fbx", "target": "scene"})


def test_import_fbx_passes_target_animation(stub_conn):
    stub, srv = stub_conn
    srv.import_fbx(path="C:/in.fbx", target="animation")
    stub.request.assert_called_once_with("fbx_import", {"path": "C:/in.fbx", "target": "animation"})


def test_save_scene_forwards(stub_conn):
    stub, srv = stub_conn
    srv.save_scene(path="C:/tmp/s.casc")
    stub.request.assert_called_once_with("save_scene", {"path": "C:/tmp/s.casc"})


def test_get_object_transform_defaults(stub_conn):
    stub, srv = stub_conn
    srv.get_object_transform(object_name="pelvis_Box")
    stub.request.assert_called_once_with(
        "object_transform_get",
        {"object_name": "pelvis_Box", "frame": 0, "local": True},
    )


def test_get_object_transform_explicit_frame_and_world(stub_conn):
    stub, srv = stub_conn
    srv.get_object_transform(object_name="head_Box", frame=24, local=False)
    stub.request.assert_called_once_with(
        "object_transform_get",
        {"object_name": "head_Box", "frame": 24, "local": False},
    )


def test_set_layer_visible_forwards_both_args(stub_conn):
    stub, srv = stub_conn
    srv.set_layer_visible(layer_id="abc-123", visible=False)
    stub.request.assert_called_once_with(
        "layer_visible_set", {"layer_id": "abc-123", "visible": False}
    )


def test_delete_object_forwards_name(stub_conn):
    stub, srv = stub_conn
    srv.delete_object(object_name="extra_cube")
    stub.request.assert_called_once_with("object_delete", {"object_name": "extra_cube"})


def test_screenshot_viewport_forwards_path(stub_conn):
    stub, srv = stub_conn
    srv.screenshot_viewport(path="C:/tmp/shot.png")
    stub.request.assert_called_once_with("viewport_screenshot", {"path": "C:/tmp/shot.png"})


@pytest.mark.parametrize(
    "tool_attr,command,kwargs",
    [
        ("get_selection", "selection_get", {}),
        ("clear_selection", "selection_clear", {}),
        ("list_layers", "layers_list", {}),
        ("get_current_frame", "frame_get", {}),
        ("set_current_frame", "frame_set", {"frame": 5}),
        ("execute_csc_code", "exec_csc", {"code": "1+1"}),
        ("call_action", "call_action", {"action_id": "Scene.Undo"}),
        ("run_autoposing", "autopose_run", {}),
        ("new_scene", "new_scene", {}),
        ("load_scene", "load_scene", {"path": "C:/in.casc"}),
        ("get_object_hierarchy", "object_hierarchy", {}),
        ("list_object_attributes", "object_attributes_list", {"object_name": "pelvis_Box"}),
        ("set_layer_locked", "layer_locked_set", {"layer_id": "abc", "locked": True}),
        ("duplicate_object", "object_duplicate", {"object_name": "pelvis_Box"}),
        # v0.3-style adds in same release
        ("undo", "undo", {}),
        ("redo", "redo", {}),
        ("add_layer", "layer_add", {"name": "Body", "parent_id": None}),
        ("delete_layer", "layer_delete", {"layer_id": "abc-123"}),
        (
            "bake_range",
            "bake_range",
            {"layer_id": "abc", "frame_start": 0, "frame_end": 30},
        ),
        # v0.3 round 2
        ("selection_filter", "selection_filter", {"pattern": "_Box", "mode": "suffix"}),
        ("get_active_layer", "active_layer_get", {}),
        ("set_active_layer", "active_layer_set", {"layer_id": "abc"}),
    ],
)
def test_simple_pass_through_tools(stub_conn, tool_attr, command, kwargs):
    stub, srv = stub_conn
    tool = getattr(srv, tool_attr)
    tool(**kwargs)
    # Some tools pass an empty dict; FastMCP-decorated funcs go through
    # server._call which always passes params as the second arg.
    assert stub.request.call_count == 1
    args, _ = stub.request.call_args
    assert args[0] == command
    assert args[1] == kwargs
