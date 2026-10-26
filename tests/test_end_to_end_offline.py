"""Full-stack offline test: MCP tool -> client -> Cascadeur's shipped server -> runtime.

Nothing here hits the network beyond loopback, and no Cascadeur GUI is involved.
The chain under test is the production one:

* ``poppet_mcp.server`` (FastMCP tool function)
* ``poppet_mcp.cascadeur_connection`` (HTTP + expression building)
* Cascadeur's **shipped** ``scripts/mcp/script_server/server.py`` (loaded by the
  harness with fake ``csc``/``events``)
* ``poppet_rt`` (the real in-app runtime source)
* mocked ``csc`` / ``scene`` objects

This is the layer that caught the ``{"transform": ...}`` envelope mismatch: unit
tests can pass while the tool layer and the handler disagree on parameter shape.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from poppet_mcp.cascadeur_connection import CascadeurConnection

from .native_server_harness import available, native_server

pytestmark = pytest.mark.skipif(
    not available(), reason="Cascadeur 2026.2 script server is not installed locally"
)


def _scene() -> MagicMock:
    """csc.domain.Scene-shaped mock with the defaults poppet's handlers read."""
    scene = MagicMock(name="scene")
    scene.get_current_frame.return_value = 7
    scene.model_viewer.return_value.get_objects.return_value = []
    scene.model_viewer.return_value.get_object_name.return_value = "x"
    scene.layers_viewer.return_value.all_layer_ids.return_value = []
    scene.selector.return_value.selected.return_value.ids = []
    # csc.domain.Scene.modify* -> bool; True means the callback ran.
    scene.modify.return_value = True
    scene.modify_update.return_value = True
    scene.modify_with_session.return_value = True
    scene.modify_update_with_session.return_value = True
    return scene


@pytest.fixture()
def stack():
    """Yield (server, client) over the real transport and shipped host server."""
    scene = _scene()
    with native_server(scene=scene) as server:
        yield server, CascadeurConnection(url=server.url, timeout=15.0), scene


def test_tool_layer_round_trip_through_real_transport(stack):
    """The FastMCP tool wrappers reach real handlers through the whole chain."""
    _, client, _ = stack

    from poppet_mcp import server as srv

    original = srv._connection
    srv._connection = lambda: client
    try:
        info = srv.get_scene_info()
    finally:
        srv._connection = original

    assert info["has_scene"] is True
    assert info["current_frame"] == 7
    assert info["object_count"] == 0
    assert info["layer_count"] == 0


def test_read_commands_round_trip(stack):
    _, client, _ = stack
    assert client.request("ping")["pong"] is True
    assert client.request("objects_list", {"name_contains": None})["count"] == 0
    assert client.request("selection_get")["count"] == 0
    assert client.request("frame_get")["current_frame"] == 7


def test_exec_escape_hatch_runs_inside_the_host(stack):
    _, client, _ = stack
    result = client.request("exec_csc", {"code": "1 + 1"})
    assert result == 2 or "2" in str(result)


def test_frame_set_calls_scene_method(stack):
    _, client, scene = stack
    out = client.request("frame_set", {"frame": 12})
    assert out["requested"] == 12
    scene.set_current_frame.assert_called_once_with(12)


def test_keyframe_transform_envelope_reaches_the_handler(stack):
    """The MCP layer nests params under ``transform``; the handler must parse it."""
    _, client, _ = stack
    with pytest.raises(Exception) as excinfo:
        client.request(
            "keyframe_set",
            {"controller_id": "ghost", "frame": 0, "transform": {"position": [1.0, 2.0, 3.0]}},
        )
    # Parsed the envelope (no "at least one of position" error), failed later
    # only because the controller does not exist in the mocked scene.
    message = str(excinfo.value)
    assert "controller not found" in message
    assert "at least one of position" not in message
