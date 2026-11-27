"""Autosave: every command that can change a scene is followed by a save of all open scenes."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def stub(monkeypatch):
    from poppet_mcp import server as srv

    conn = MagicMock(name="conn")
    conn.request = MagicMock(return_value={"repr": "[]"})
    monkeypatch.setattr(srv, "_connection", lambda: conn)
    return conn, srv


@pytest.mark.autosave
def test_mutating_command_is_followed_by_autosave(stub):
    conn, srv = stub
    srv._call("pose_keys_set", keys={})
    commands = [c.args[0] for c in conn.request.call_args_list]
    assert commands == ["pose_keys_set", "exec_csc"]
    code = conn.request.call_args_list[1].args[1]["code"]
    assert ".save(" in code and "get_path_name" in code


@pytest.mark.autosave
def test_read_only_command_does_not_autosave(stub):
    conn, srv = stub
    srv._call("scene_info")
    assert [c.args[0] for c in conn.request.call_args_list] == ["scene_info"]


@pytest.mark.autosave
def test_failed_autosave_does_not_fail_the_tool(stub):
    conn, srv = stub

    def request(command, params):
        if command == "exec_csc":
            raise RuntimeError("Cascadeur went away")
        return {"ok": True}

    conn.request = MagicMock(side_effect=request)
    assert srv._call("keyframe_add", layer_id="x", frame=1) == {"ok": True}


def test_autosave_can_be_switched_off(stub):
    conn, srv = stub  # the autouse fixture sets POPPET_AUTOSAVE=0
    srv._call("pose_keys_set", keys={})
    assert [c.args[0] for c in conn.request.call_args_list] == ["pose_keys_set"]


@pytest.mark.autosave
def test_close_spare_tabs_saves_before_closing(stub):
    conn, srv = stub
    srv.close_spare_tabs()
    codes = [c.args[1]["code"] for c in conn.request.call_args_list]
    assert ".save(" in codes[0]
    assert "remove_application_scene" in codes[1]
