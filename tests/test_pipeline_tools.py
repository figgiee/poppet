"""Offline tests for the animation pipeline tools and the pose solver."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from poppet_mcp import pipeline_tools as pt
from poppet_mcp.posing import Rig, detect_naming

FIXTURE = Path(__file__).with_name("fixtures_quinn_rest.json")


@pytest.fixture
def quinn_rest():
    return json.loads(FIXTURE.read_text())


class FakeCascadeur:
    """Records commands and answers the few the pipeline tools read."""

    def __init__(self, rest):
        self.rest = rest
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, command, **params):
        self.calls.append((command, params))
        if command == "rig_rest_dump":
            types = params.get("types") or ["Point", "Limb Direction", "Joint"]
            pts = {k: v for k, v in self.rest.items() if v[0] in types}
            return {"frame": 0, "count": len(pts), "points": pts, "errors": {}}
        if command == "scene_info":
            return {"name": "Quinn"}
        if command == "pose_keys_set":
            keys = params["keys"]
            return {"frames": len(keys), "values": sum(len(v) for v in keys.values())}
        if command == "rig_audit":
            joints = {k for k, v in self.rest.items() if v[0] == "Joint"}
            return {
                "missing_joints": sorted(set(params["expected_joints"]) - joints),
                "extra_joints": [],
                "contact_point_behaviours": {
                    n: {"FulcrumPoint": True, "Transform": True} for n in params["contact_points"]
                },
            }
        if command == "motion_sample":
            frames = range(params["frame_start"], params["frame_end"] + 1, params["frame_step"])
            return {
                "frames": [
                    {
                        "frame": f,
                        "objects": {
                            n: {"position": [0.0, 90.0, float(f)]} for n in params["object_names"]
                        },
                    }
                    for f in frames
                ]
            }
        if command == "glb_import":
            return {"imported": [{"name": "Box", "type": "Mesh"}]}
        return {"ok": True}


@pytest.fixture
def fake(monkeypatch, quinn_rest):
    f = FakeCascadeur(quinn_rest)
    monkeypatch.setattr(pt, "_call", f)
    pt._rig_cache.clear()
    return f


def test_solver_reproduces_rest_pose(quinn_rest):
    rig = Rig(quinn_rest)
    assert rig.naming == "ue" == detect_naming(quinn_rest)
    solved = rig.solve(rig.rest_pose())
    errors = {
        n: np.linalg.norm(np.array(p) - np.array(quinn_rest[n][1:])) for n, p in solved.items()
    }
    assert max(errors.values()) < 0.5, {n: e for n, e in errors.items() if e >= 0.5}
    assert "lowerarm_MainPoint_l" in solved and "forearm_MainPoint_l" not in solved


def test_solver_keeps_bone_lengths(quinn_rest):
    rig = Rig(quinn_rest)
    pose = rig.rest_pose()
    pose.update(pelvis=[0, 80, 20], foot_l=[10, rig.ankle_height, 60], hand_r=[-30, 120, 40])
    out = rig.solve(pose)
    for a, b in (
        ("thigh_MainPoint_l", "calf_MainPoint_l"),
        ("calf_MainPoint_l", "foot_MainPoint_l"),
        ("upperarm_MainPoint_r", "lowerarm_MainPoint_r"),
    ):
        rest_len = np.linalg.norm(np.array(quinn_rest[a][1:]) - np.array(quinn_rest[b][1:]))
        assert abs(np.linalg.norm(np.array(out[a]) - np.array(out[b])) - rest_len) < 0.05


def test_rig_rejects_missing_points(quinn_rest):
    partial = {k: v for k, v in quinn_rest.items() if not k.startswith("calf_")}
    with pytest.raises(ValueError, match="calf_MainPoint"):
        Rig(partial)


def test_block_poses_keys_every_solved_point(fake):
    rig = Rig(fake.rest)
    result = pt.block_poses(
        [{"frame": 4, "label": "plant", "pose": rig.rest_pose()}], reset_frames=40
    )
    command, params = [c for c in fake.calls if c[0] == "pose_keys_set"][0]
    assert params["reset"] is True and params["frames"] == 40
    assert set(params["keys"]) == {"4"}
    assert result["labels"] == {4: "plant"} and result["naming"] == "ue"


def test_rig_audit_uses_shipped_quinn_reference(fake):
    result = pt.rig_audit()
    _, params = [c for c in fake.calls if c[0] == "rig_audit"][0]
    assert "ball_MainPoint_l" in params["contact_points"]
    assert len(params["expected_joints"]) == 89
    assert result["passed"] is True


def test_rig_audit_fails_without_fulcrum(fake, monkeypatch):
    original = fake.__call__

    def no_fulcrum(command, **params):
        out = original(command, **params)
        if command == "rig_audit":
            out["contact_point_behaviours"]["hand_MainPoint_l"] = {"FulcrumPoint": False}
        return out

    monkeypatch.setattr(pt, "_call", no_fulcrum)
    result = pt.rig_audit()
    assert result["passed"] is False
    assert result["contact_points_without_fulcrum"] == ["hand_MainPoint_l"]


def test_unknown_joint_reference(fake):
    with pytest.raises(ValueError, match="ue5_quinn"):
        pt.rig_audit(expected_joints="nope")


def test_add_box_obstacle_writes_glb_and_requests_collision(fake, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    result = pt.add_box_obstacle([-80, 0, 0], [80, 88, 45], name="Vault Box")
    glb = Path(result["glb"])
    assert glb.read_bytes()[:4] == b"glTF"
    assert ("call_action", {"action_id": "Collision.Add kinematic mesh"}) in fake.calls
    assert ("selection_set", {"object_names": ["Box"]}) in fake.calls


def test_physics_pass_reports_no_change_and_settles(fake):
    result = pt.physics_pass(["pelvis_MainPoint"], 0, 4, settle_timeout_sec=3)
    assert result["invoked"] == [
        "AutoPhysicsTool.Snap to Auto Physics",
        "FixCollisionsTool.Collision Penetration Cleaning",
    ]
    assert result["settled"] is True and result["changed"] is False


def test_physics_pass_rejects_unknown_step(fake):
    with pytest.raises(ValueError, match="autophysics_snap"):
        pt.physics_pass(["pelvis_MainPoint"], 0, 4, steps=["magic"])


def test_camera_presets():
    cam = pt._camera_for("side_left", [0, 90, 100], None)
    assert cam["position"][0] == 520.0 and cam["position"][2] == 100
    with pytest.raises(ValueError):
        pt._camera_for("orbit", [0, 0, 0], None)


def test_contact_sheet(tmp_path):
    from PIL import Image

    paths = []
    for i in range(5):
        p = tmp_path / f"{i}.png"
        Image.new("RGB", (160, 90), (i * 40, 0, 0)).save(p)
        paths.append(str(p))
    result = pt.make_contact_sheet(
        paths, str(tmp_path / "sheet.png"), cols=3, labels=["a", "b", "c", "d", "e"], cell_width=160
    )
    sheet = Image.open(result["path"])
    assert sheet.size == (480, 180)


def test_preflight_flags_expired_login(monkeypatch, tmp_path):
    log = tmp_path / "cascadeur_log.log"
    log.write_text("ok\n[auth] invalid or expired JSON Web Token\n")
    monkeypatch.setattr(pt, "CASCADEUR_LOG", log)

    class Conn:
        url = "http://127.0.0.1:8766"

        def health(self):
            return {"ok": True}

        def request(self, command, params):
            return {"pong": True, "has_scene": True}

    monkeypatch.setattr(pt, "_connection", lambda: Conn())
    report = pt.cascadeur_preflight()
    assert report["ready"] is False
    assert any("login" in p for p in report["problems"])


def test_run_script_refuses_video_export(monkeypatch):
    from poppet_mcp import server

    with pytest.raises(ValueError, match="render_frames"):
        server.run_script("r.play_to_video_file(sv, p, 'x.mp4')")


def test_inapp_exec_refuses_video_export():
    from tests.runtime_loader import runtime

    reply = runtime._dispatch_legacy(
        {"type": "exec_csc", "params": {"code": "x.play_to_video_file()"}}, None
    )
    assert reply["status"] == "error" and "render_frames" in reply["message"]


def test_inapp_frames_to_spans():
    from tests.runtime_loader import runtime

    assert runtime._frames_to_spans([1, 2, 3, 7, 8, 10]) == [[1, 3], [7, 8], [10, 10]]


def test_inapp_pipeline_handlers_registered():
    from tests.runtime_loader import runtime

    for name in (
        "rig_rest_dump",
        "rig_audit",
        "pose_keys_set",
        "fulcrum_spans_set",
        "glb_import",
        "viewport_set",
    ):
        assert name in runtime._HANDLERS


def test_block_poses_with_shipped_rest_file(fake):
    rig = Rig(json.loads(FIXTURE.read_text()))
    result = pt.block_poses([{"frame": 0, "pose": rig.rest_pose()}], rest_file="ue5_quinn")
    assert result["rest_source"] == "file:ue5_quinn"
    assert not [c for c in fake.calls if c[0] == "rig_rest_dump"]


def test_block_poses_passes_interpolation(fake):
    rig = Rig(json.loads(FIXTURE.read_text()))
    pt.block_poses(
        [{"frame": 0, "pose": rig.rest_pose()}], rest_file="ue5_quinn", interpolation="STEP"
    )
    _, params = [c for c in fake.calls if c[0] == "pose_keys_set"][0]
    assert params["interpolation"] == "STEP"


def test_inapp_interpolation_enum_rejects_unknown(csc_mock):
    from tests.runtime_loader import runtime

    csc_mock.layers.layer.Interpolation = type("Interp", (), {"BEZIER": 1, "STEP": 2})
    assert runtime._interpolation_enum("bezier") == 1
    with pytest.raises(ValueError, match="BEZIER"):
        runtime._interpolation_enum("smooth")


def _ballistic_tracks(frames, g, rise_scale=1.0, foot_slide=0.0):
    """Pelvis thrown at frame 10 and caught at frame 20; foot planted 0-9 and 21-30."""
    pelvis, foot = [], []
    for f in frames:
        if 10 <= f <= 20:
            t = f - 9  # frames since the last support frame
            y = 90 + rise_scale * (g * t * (12 - t) / 2)
        else:
            y = 90.0
        pelvis.append([0.0, y, float(f * 10)])
        foot.append([0.0, 8.0, 100.0 + (foot_slide * f if f <= 9 else 0.0)])
    return {"pelvis_MainPoint": pelvis, "foot_MainPoint_l": foot}


def test_lint_accepts_ballistic_arc():
    from poppet_mcp.motion_checks import lint_tracks

    frames = list(range(31))
    g = 1.0889
    problems = lint_tracks(
        _ballistic_tracks(frames, g),
        frames,
        {"foot_MainPoint_l": [[0, 9], [21, 30]]},
        "pelvis_MainPoint",
        g,
    )
    airborne = [p for p in problems if p["kind"] == "airborne_phase"]
    assert len(airborne) == 1 and "why" not in airborne[0]
    assert abs(airborne[0]["ratio"] - 1) < 0.1


def test_lint_flags_floaty_flight_and_sliding_foot():
    from poppet_mcp.motion_checks import lint_tracks

    frames = list(range(31))
    g = 1.0889
    problems = lint_tracks(
        _ballistic_tracks(frames, g, rise_scale=0.3, foot_slide=10.0),
        frames,
        {"foot_MainPoint_l": [[0, 9], [21, 30]]},
        "pelvis_MainPoint",
        g,
    )
    kinds = {p["kind"] for p in problems if "why" in p}
    assert kinds == {"planted_point_slides", "airborne_phase"}


def test_use_scene_routes_data_and_guards_ui(fake, monkeypatch):
    original = fake.__call__

    def with_tabs(command, **params):
        if command == "scene_info":
            fake.calls.append((command, params))
            return {
                "scene_name": params.get("scene_name"),
                "current_tab": "Other.casc",
                "object_count": 3,
            }
        return original(command, **params)

    monkeypatch.setattr(pt, "_call", with_tabs)
    try:
        pt.use_scene("Quinn-Copy")
        pt.set_fulcrum_spans({"foot_MainPoint_l": [[1, 2]]})
        assert (
            "fulcrum_spans_set",
            {"spans": {"foot_MainPoint_l": [[1, 2]]}, "scene_name": "Quinn-Copy"},
        ) in fake.calls
        with pytest.raises(RuntimeError, match="visible tab"):
            pt.set_viewport(mode="View")
    finally:
        pt.use_scene(None)


def test_fulcrum_mismatch_warns(fake, monkeypatch):
    original = fake.__call__

    def collapsed(command, **params):
        if command == "fulcrum_spans_set":
            return {
                "frames": 40,
                "readback": {"foot_MainPoint_l": [[0, 14]]},
                "no_fulcrum_behaviour": [],
            }
        return original(command, **params)

    monkeypatch.setattr(pt, "_call", collapsed)
    result = pt.set_fulcrum_spans({"foot_MainPoint_l": [[12, 16]]})
    assert "foot_MainPoint_l" in result["mismatched"] and "keys" in result["warning"]


def test_inapp_exec_captures_stdout():
    from tests.runtime_loader import runtime

    code = "print('hi')\nresult = 42"
    reply = runtime._dispatch_legacy({"type": "exec_csc", "params": {"code": code}}, None)
    assert reply["status"] == "success"
    assert reply["result"]["stdout"] == "hi\n"
    assert reply["result"]["repr"] == "42"


def test_retime_moves_keys_and_resamples():
    from poppet_mcp.take_tools import retime_positions

    take = {0: {"p": [0.0, 0.0, 0.0]}, 10: {"p": [0.0, 0.0, 100.0]}}
    assert sorted(retime_positions(take, 2.0, every_frame=False)) == [0, 20]
    dense = {f: {"p": [0.0, 0.0, float(f)]} for f in range(0, 9)}
    out = retime_positions(dense, 0.25, every_frame=True)
    assert sorted(out) == [0, 1, 2] and out[1]["p"][2] == 4.0


def test_mirror_swaps_sides_and_reflects():
    from poppet_mcp.take_tools import mirror_positions

    take = {
        0: {
            "hand_MainPoint_l": [20.0, 90.0, 5.0],
            "hand_MainPoint_r": [-30.0, 100.0, 0.0],
            "pelvis_MainPoint": [2.0, 95.0, 0.0],
        }
    }
    out = mirror_positions(take)[0]
    assert out["hand_MainPoint_l"] == [30.0, 100.0, 0.0]
    assert out["hand_MainPoint_r"] == [-20.0, 90.0, 5.0]
    assert out["pelvis_MainPoint"] == [-2.0, 95.0, 0.0]


def test_scale_spans():
    from poppet_mcp.take_tools import _scale_spans

    assert _scale_spans({"foot": [[4, 8]], "hand": []}, 0.5, 0) == {"foot": [[2, 4]]}
