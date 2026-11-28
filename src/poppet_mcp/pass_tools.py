"""take_audit: the checks a take must pass before it leaves Cascadeur.

Numbers that match a source clip do not make a take physical. This audit looks for
what Brandon sees first in the game: a blade or a foot going through the floor, a
planted foot skating, keys that hold and then jump, and a clip whose last frame is
not keyed (it loops back to the first pose and AutoPhysics collapses it).
"""

from __future__ import annotations

from typing import Any

from poppet_mcp import pass_ledger
from poppet_mcp import pipeline_tools as pt
from poppet_mcp.server import mcp

FLOOR_POINTS = ["foot_l", "foot_r", "ball_l", "ball_r", "hand_l", "hand_r", "head", "pelvis"]
FEET = ["foot_l", "foot_r"]
MAX_SAMPLES = 2048


def _sample(names: list[str], first: int, last: int) -> dict[int, dict[str, dict]]:
    out: dict[int, dict[str, dict]] = {}
    per = max(1, MAX_SAMPLES // max(1, len(names)))
    start = first
    while start <= last:
        end = min(last, start + per - 1)
        data = pt._scall(
            "motion_sample",
            object_names=names,
            frame_start=start,
            frame_end=end,
            frame_step=1,
            local=False,
        )
        for row in data["frames"]:
            out[row["frame"]] = row["objects"]
        start = end + 1
    return out


def rotate(q: list[float], v: list[float]) -> list[float]:
    """Rotate ``v`` by the xyzw quaternion ``q``."""
    x, y, z, w = q
    vx, vy, vz = v
    # t = 2 * cross(q.xyz, v); v' = v + w * t + cross(q.xyz, t)
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    return [
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    ]


def blade_points(
    pos: list[float], rot: list[float], axis: list[float], length: float
) -> list[list[float]]:
    """Five points from the grip to the tip along the blade axis."""
    d = rotate(rot, axis)
    return [[p + d_i * length * t for p, d_i in zip(pos, d)] for t in (0.25, 0.5, 0.75, 0.9, 1.0)]


def floor_hits(heights: dict[int, float], floor: float, tolerance: float) -> list[list[float]]:
    """Runs of frames below ``floor - tolerance``: [[first, last, deepest_cm], ...]."""
    runs: list[list[float]] = []
    for f in sorted(heights):
        depth = floor - heights[f]
        if depth > tolerance:
            if runs and runs[-1][1] == f - 1:
                runs[-1][1] = f
                runs[-1][2] = max(runs[-1][2], round(depth, 2))
            else:
                runs.append([f, f, round(depth, 2)])
    return runs


def planted_slides(
    track: dict[int, list[float]], low_cm: float, still_cm: float, slide_tol: float
) -> list[dict]:
    """Find frames where a foot is planted (low and nearly still) and report spans that skate."""
    frames = sorted(track)
    if not frames:
        return []
    floor = min(track[f][1] for f in frames)
    planted = []
    for a, b in zip(frames, frames[1:]):
        pa, pb = track[a], track[b]
        speed = ((pa[0] - pb[0]) ** 2 + (pa[2] - pb[2]) ** 2) ** 0.5
        if pa[1] < floor + low_cm and pb[1] < floor + low_cm and speed < still_cm:
            planted.append(a)
    spans: list[list[int]] = []
    for f in planted:
        if spans and spans[-1][1] == f - 1:
            spans[-1][1] = f
        else:
            spans.append([f, f])
    out = []
    for s, e in spans:
        if e - s < 3:
            continue
        xs = [track[f][0] for f in range(s, e + 2) if f in track]
        zs = [track[f][2] for f in range(s, e + 2) if f in track]
        drift = ((max(xs) - min(xs)) ** 2 + (max(zs) - min(zs)) ** 2) ** 0.5
        if drift > slide_tol:
            out.append({"span": [s, e + 1], "slide_cm": round(drift, 2)})
    return out


def held_jumps(full_keys: dict) -> list[dict]:
    """Sections that hold a pose (STEP) for more than one frame and then jump to the next key."""
    out = []
    for layer in full_keys.get("layers", []):
        keys = layer.get("key_frames", [])
        interp = layer.get("interpolation", {})
        for a, b in zip(keys, keys[1:]):
            if str(interp.get(str(a), "")).endswith("STEP") and b - a > 1:
                out.append({"layer": layer.get("name"), "from": a, "to": b})
    return out


@mcp.tool()
def take_audit(
    frame_start: int = 0,
    frame_end: int | None = None,
    floor_height_cm: float = 0.0,
    floor_tolerance_cm: float = 1.0,
    weapon_joint: str | None = "weapon_r",
    blade_axis: list[float] | None = None,
    blade_length_cm: float = 176.0,
    blade_half_width_cm: float = 15.0,
    slide_tolerance_cm: float = 2.0,
) -> dict:
    """Check the visible take for what reads as wrong in the game, and record the result.

    Run it after the physics pass and before any export (the export tools require a
    passing audit newer than the last edit). It reports:

    - ``floor``: frames where a foot, hand, the head, the pelvis or the blade goes below
      the floor (blade checked at five points from grip to tip along ``blade_axis`` of
      ``weapon_joint``; on the UE5 Manny base rig the blade runs along local -Y, which is
      Unreal's +Y). The blade counts as touching when its centre line comes within
      ``blade_half_width_cm`` of the floor (the Krojyn greatsword at scale 1.4 is about
      30 cm wide). The floor is y = ``floor_height_cm``, the root plane in Unreal.
    - ``foot_slides``: planted spans (foot low and nearly still) where the foot skates
      more than ``slide_tolerance_cm``.
    - ``held_jumps``: STEP sections longer than a frame: the pose holds, then snaps.
    - ``last_frame_keyed``: an unkeyed last frame loops to the first pose.

    It cannot judge weight or timing: render with ``review_sheet`` and look.
    """
    timing = pt._scall("scene_timing")
    n = int(timing["frames"])
    last = n - 1 if frame_end is None else min(frame_end, n - 1)
    have = {o["name"] for o in pt._scall("objects_list")["objects"]}
    names = [p for p in FLOOR_POINTS if p in have]
    weapon = weapon_joint if weapon_joint and weapon_joint in have else None
    samples = _sample(names + ([weapon] if weapon else []), frame_start, last)
    problems: list[dict[str, Any]] = []

    floor: dict[str, list] = {}
    for p in names:
        runs = floor_hits(
            {f: samples[f][p]["position"][1] for f in samples}, floor_height_cm, floor_tolerance_cm
        )
        if runs:
            floor[p] = runs
    if weapon:
        axis = blade_axis or [0.0, -1.0, 0.0]
        lowest = {}
        for f in samples:
            obj = samples[f][weapon]
            if obj.get("rotation"):
                pts = blade_points(obj["position"], obj["rotation"], axis, blade_length_cm)
                lowest[f] = min(pt_[1] for pt_ in pts)
        # The blade has width: its edge reaches half the width below the centre line.
        runs = floor_hits(lowest, floor_height_cm + blade_half_width_cm, floor_tolerance_cm)
        if runs:
            floor["blade"] = runs
    for p, runs in floor.items():
        problems.append(
            {
                "kind": "floor",
                "object": p,
                "frames": runs,
                "why": f"{p} goes below the floor ([first, last, deepest cm])",
            }
        )

    slides = {}
    for foot in FEET:
        if foot in names:
            s = planted_slides(
                {f: samples[f][foot]["position"] for f in samples}, 3.0, 1.0, slide_tolerance_cm
            )
            if s:
                slides[foot] = s
                problems.append(
                    {
                        "kind": "foot_slide",
                        "object": foot,
                        "spans": s,
                        "why": f"{foot} skates while planted; pin it with setup_contacts",
                    }
                )

    full_keys = pt._scall("keys_report")
    jumps = held_jumps(full_keys)
    if jumps:
        problems.append(
            {
                "kind": "held_jump",
                "sections": jumps[:20],
                "count": len(jumps),
                "why": "STEP sections hold a pose then snap; use set_interpolation",
            }
        )
    key_frames = full_keys.get("key_frames", [])
    last_keyed = bool(key_frames) and key_frames[-1] >= n - 1
    if not last_keyed:
        problems.append(
            {
                "kind": "last_frame",
                "why": f"frame {n - 1} is not keyed; the clip loops to its first pose",
            }
        )

    passed = not problems
    scene = pt.scene_key()
    pass_ledger.mark(scene, "audit", {"passed": passed, "problems": len(problems)})
    return {
        "scene": scene,
        "frames": [frame_start, last],
        "passed": passed,
        "problems": problems,
        "floor": floor,
        "foot_slides": slides,
        "held_jumps": len(jumps),
        "last_frame_keyed": last_keyed,
        "pass_status": pass_ledger.status(scene),
        "note": "Passing means no floor, sliding or stepping faults. It does not mean "
        "the take reads well.",
    }
