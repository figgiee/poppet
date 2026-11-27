"""Offline tests for the Unreal round-trip tools: FBX axis patch, readback compare, keys summary."""

from __future__ import annotations

import struct

import pytest

from poppet_mcp import fbx_axis
from poppet_mcp.roundtrip_tools import compare_to_unreal, fast_frames
from poppet_mcp.take_tools import summarize_keys


def _node(name: str, props: list[tuple[str, object]], children: list[bytes], offset: int) -> bytes:
    body = b""
    for kind, value in props:
        if kind == "S":
            raw = value.encode()
            body += b"S" + struct.pack("<I", len(raw)) + raw
        elif kind == "I":
            body += b"I" + struct.pack("<i", value)
        elif kind == "D":
            body += b"D" + struct.pack("<d", value)
    head_len = 13 + len(name)
    start = offset + head_len + len(body)
    kids = b""
    for build in children:
        kids += build(start + len(kids))
    tail = b"\x00" * 13 if children else b""
    end = offset + head_len + len(body) + len(kids) + len(tail)
    head = struct.pack("<III", end, len(props), len(body)) + bytes([len(name)]) + name.encode()
    return head + body + kids + tail


def _fake_unreal_fbx(path):
    def p(key, kind, value):
        return lambda off: _node(
            "P", [("S", key), ("S", "int"), ("S", "Integer"), ("S", ""), (kind, value)], [], off
        )

    props = [
        p("UpAxis", "I", 2),
        p("UpAxisSign", "I", 1),
        p("FrontAxis", "I", 1),
        p("FrontAxisSign", "I", -1),
        p("CoordAxis", "I", 0),
        p("CoordAxisSign", "I", 1),
        p("UnitScaleFactor", "D", 1.0),
    ]
    header = fbx_axis.MAGIC + b"\x00\x1a\x00" + struct.pack("<I", 7400)
    p70 = lambda off: _node("Properties70", [], props, off)  # noqa: E731
    gs = _node("GlobalSettings", [], [p70], len(header))
    path.write_bytes(header + gs + b"\x00" * 13 + b"\x00" * 200)


def test_unreal_fbx_is_declared_y_up(tmp_path):
    src = tmp_path / "clip.fbx"
    _fake_unreal_fbx(src)
    assert fbx_axis.axis_report(src)["UpAxis"] == 2
    out = fbx_axis.prepare_unreal_fbx(src, tmp_path / "out" / "clip.fbx")
    assert out["patched"] is True
    assert out["after"]["UpAxis"] == 1
    assert out["after"]["FrontAxis"] == 2
    assert out["after"]["FrontAxisSign"] == 1
    assert out["after"]["UnitScaleFactor"] == 1.0
    assert (tmp_path / "out" / "clip.fbx").stat().st_size == src.stat().st_size


def test_y_up_file_is_copied_unchanged(tmp_path):
    src = tmp_path / "clip.fbx"
    _fake_unreal_fbx(src)
    fbx_axis.patch_axes(src, src, {"UpAxis": 1})
    out = fbx_axis.prepare_unreal_fbx(src, tmp_path / "copy.fbx")
    assert out["patched"] is False
    assert (tmp_path / "copy.fbx").read_bytes() == src.read_bytes()


def test_ascii_fbx_is_refused(tmp_path):
    src = tmp_path / "ascii.fbx"
    src.write_text("; FBX 7.4.0 project file")
    with pytest.raises(ValueError):
        fbx_axis.axis_report(src)


def test_compare_matches_frames_by_time_and_axes():
    # Unreal at 60 fps (5 frames), Cascadeur at 30 fps (3 frames).
    ue = [
        {
            "pelvis": [1.0, 10.0 * g, 90.0],
            "foot_l": [5.0, 10.0 * g, 10.0],
            "foot_r": [-5.0, 0.0, 10.0],
        }
        for g in range(5)
    ]
    readback = {"bones": ["pelvis", "foot_l", "foot_r"], "positions": ue}
    casc = {
        f: {
            "pelvis": [1.0, 90.3, 20.0 * f],
            "foot_l": [5.0, 10.0, 20.0 * f],
            "foot_r": [-5.0, 10.0, 0.0],
        }
        for f in range(3)
    }
    res = compare_to_unreal(casc, readback, tolerance_cm=0.5)
    assert res["frame_ratio"] == 2.0
    assert res["passed"] is True
    assert res["frame0_heights"]["pelvis"]["diff_cm"] == pytest.approx(0.3)
    assert res["worst_over_clip"]["foot_l"]["dist_cm"] == pytest.approx(0.0)
    casc[0]["foot_r"][1] = 12.0
    assert compare_to_unreal(casc, readback, tolerance_cm=1.0)["passed"] is False


def test_keys_summary_does_not_list_every_baked_frame():
    frames = list(range(81))
    full = {
        "frames_count": 81,
        "key_frames": frames,
        "layers": [
            {
                "name": n,
                "key_frames": frames,
                "interpolation": {str(f): "Interpolation.STEP" for f in frames},
            }
            for n in ("Pelvis", "Torso")
        ],
    }
    short = summarize_keys(full)
    assert short["keys_total"] == 162
    assert short["interpolation"] == {"STEP": 162}
    assert "key_frames" not in short
    assert short["layers"][0] == {
        "name": "Pelvis",
        "keys": 81,
        "range": [0, 80],
        "interpolation": {"STEP": 81},
    }
    few = summarize_keys({**full, "key_frames": [0, 40, 80]})
    assert few["key_frames"] == [0, 40, 80]


def test_fast_frames_marks_the_peak_of_a_swing():
    path = {
        0: [0, 0, 0],
        1: [10, 0, 0],
        2: [20, 0, 0],
        3: [60, 40, 0],
        4: [100, 0, 0],
        5: [110, 0, 0],
    }
    positions = {f: {"hand_r": p} for f, p in path.items()}
    assert fast_frames(positions, 5.0) == [2, 3, 4]
    assert fast_frames(positions, 30.0) == [3]
    assert fast_frames(positions, 50.0) == []


def test_remap_frames_compresses_a_windup_and_shifts_the_rest():
    from poppet_mcp.roundtrip_tools import remap_frames

    keys = [0, 7, 14, 21, 30, 80]
    m = remap_frames(keys, [[0, 0], [21, 13], [80, 72]])
    assert m[0] == 0 and m[21] == 13 and m[80] == 72
    assert m[7] == 4 and m[14] == 9
    assert m[30] == 22
    with pytest.raises(ValueError):
        remap_frames([0, 1, 2], [[0, 0], [2, 0]])
