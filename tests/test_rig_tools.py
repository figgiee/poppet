"""Offline tests for hands, feet, fingers, settings panels and the action catalogue."""

from __future__ import annotations

import pytest

from poppet_mcp import pipeline_tools as pt
from poppet_mcp import rig_tools as rt


class Recorder:
    def __init__(self, replies=None):
        self.calls = []
        self.replies = replies or {}

    def __call__(self, command, **params):
        self.calls.append((command, params))
        reply = self.replies.get(command, {})
        return reply(params) if callable(reply) else reply


def test_finger_keys_shapes():
    keys = rt.finger_keys("l", "fist")
    assert len(keys) == 15
    assert keys["index_02_Box_l"] == [0.0, 0.0, 95.0]
    assert keys["thumb_01_Box_l"] == [0.0, 0.0, 35.0]
    spread = rt.finger_keys("r", curl=[0, 0, 0], spread=10)
    assert spread["index_01_Box_r"][1] == -15.0 and spread["pinky_01_Box_r"][1] == 15.0
    assert spread["index_02_Box_r"][1] == 0.0
    point = rt.finger_keys("l", "point")
    assert point["index_02_Box_l"][2] == 0.0 and point["middle_02_Box_l"][2] == 95.0


def test_finger_keys_rejects_bad_input():
    with pytest.raises(ValueError, match="side"):
        rt.finger_keys("x", "fist")
    with pytest.raises(ValueError, match="grip_edge"):
        rt.finger_keys("l", "claw")


def test_pose_fingers_uses_shipped_rest(monkeypatch):
    rec = Recorder({"local_rotation_keys_set": {"frames": 1, "values": 15}})
    monkeypatch.setattr(pt, "_call", rec)
    out = rt.pose_fingers("l", [4], preset="relaxed")
    _, params = rec.calls[0]
    assert set(params["keys"]) == {"4"} and len(params["base_quaternions"]) == 15
    assert out["controllers"] == 15


def test_action_catalogue_and_filter():
    data = rt.list_actions("FixFoot")
    assert "View.FixFoot" in data["actions"]
    assert all("fixfoot" in a.lower() for a in data["actions"])
    assert rt.list_actions()["count"] > 150


def test_run_action_reports_unknown_id(monkeypatch, tmp_path):
    log = tmp_path / "cascadeur_log.log"
    log.write_text("start\n")
    monkeypatch.setattr(pt, "CASCADEUR_LOG", log)

    def call_action(params):
        with log.open("a") as f:
            message = "Action manager does not contain id: " + params["action_id"]
            f.write(f"ERROR [action_manager.cpp:31] {message}\n")
            f.write(
                " =============== Backtrace: =================\n 9# PyMapping_Check in python311\n"
            )
        return {}

    rec = Recorder({"call_action": call_action, "dialogs_list": {"dialogs": []}})
    monkeypatch.setattr(pt, "_call", rec)
    out = rt.run_action("Nope.Missing", wait_sec=0)
    assert out["exists"] is False
    assert all("Backtrace" not in line and "#" not in line.split()[0] for line in out["log"])


def test_set_point_physics_keys_run_edges(monkeypatch):
    rec = Recorder({"behaviour_set": {"written": {}, "readback": {}}})
    monkeypatch.setattr(pt, "_call", rec)
    rt.set_point_physics(
        ["hand_MainPoint_l"],
        "AutoPhysicsApply",
        "keep_global_translation",
        1.0,
        frames=[3, 4, 5, 9, 10],
    )
    assert rec.calls[0] == ("keys_add", {"frames": [3, 6, 9, 11]})
    assert rec.calls[1][1]["frames"] == [3, 4, 5, 9, 10]


def test_setup_contacts_sets_keep_weights_on_and_off(monkeypatch):
    replies = {
        "fulcrum_spans_set": {
            "frames": 10,
            "readback": {"foot_MainPoint_l": [[2, 4]]},
            "no_fulcrum_behaviour": [],
        },
        "scene_timing": {"frames": 10},
        "behaviours_get": lambda p: {"objects": {p["object_names"][0]: {}}},
        "behaviour_set": {"written": {}, "readback": {}},
    }
    rec = Recorder(replies)
    monkeypatch.setattr(pt, "_call", rec)
    rt.setup_contacts({"foot_MainPoint_l": [[2, 4]]}, keep_rotation=1.0, collision_radius=3.0)
    sets = [p for c, p in rec.calls if c == "behaviour_set"]
    on = [p for p in sets if p["property"] == "keep_global_translation" and p["value"] == 1.0][0]
    off = [p for p in sets if p["property"] == "keep_global_translation" and p["value"] == 0.0][0]
    assert on["frames"] == [2, 3, 4] and off["frames"] == [0, 1, 5, 6, 7, 8, 9]
    assert any(p["property"] == "keep_global_rotation" for p in sets)
    assert any(
        p["behaviour"] == "FulcrumPoint" and p["property"] == "collision_radius" for p in sets
    )


def test_inapp_new_handlers_registered():
    from tests.runtime_loader import runtime

    for name in (
        "behaviours_get",
        "behaviour_set",
        "local_rotation_keys_set",
        "local_rotations_get",
        "settings_panel_get",
        "settings_panel_set",
        "timeline_select",
        "dialogs_list",
        "dialog_answer",
        "keys_add",
    ):
        assert name in runtime._HANDLERS
