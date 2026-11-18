"""Measure a take and lint it before the physics pass.

The Ada dash vault failed its first AutoPhysics run because the keyed poses were
not physically possible: the planted foot moved 90 cm between two keys and the
airborne phase did not match the height gained. These tools catch that from
numbers before a solve, and say why.
"""

from __future__ import annotations

import math
from typing import Any

from poppet_mcp.pipeline_tools import _sample, _scall
from poppet_mcp.server import mcp

GRAVITY_CM_S2 = 981.0


def _speeds(track: list[list[float]], fps: float, step: int) -> list[float]:
    dt = step / fps
    return [round(math.dist(a, b) / dt, 1) for a, b in zip(track, track[1:])]


@mcp.tool()
def measure_motion(
    points: list[str],
    frame_start: int,
    frame_end: int,
    frame_step: int = 1,
    fps: float = 30.0,
    contact_height_cm: float | None = None,
) -> dict:
    """Per-frame world positions and speeds of named points, plus ground contact.

    ``points``: up to 32 objects (controller points, joints, ``Center of Mass``).
    Speeds are cm/s at ``fps``. With ``contact_height_cm`` (for feet, the rig's
    ankle height plus 2-3 cm), each point also reports the frame spans where it is
    at or below that height, which is how the take's supports and airborne phases
    look from the numbers.
    """
    tracks = _sample(points, frame_start, frame_end, frame_step)
    frames = list(range(frame_start, frame_end + 1, frame_step))
    out: dict[str, Any] = {"frames": frames, "fps": fps, "points": {}}
    for name, track in tracks.items():
        speeds = _speeds(track, fps, frame_step)
        entry: dict[str, Any] = {
            "positions": [[round(c, 2) for c in p] for p in track],
            "speed_cm_s": speeds,
            "peak_speed_cm_s": max(speeds, default=0.0),
            "min_height_cm": round(min(p[1] for p in track), 2),
            "max_height_cm": round(max(p[1] for p in track), 2),
        }
        if contact_height_cm is not None:
            low = [f for f, p in zip(frames, track) if p[1] <= contact_height_cm]
            entry["low_spans"] = _spans(low, frame_step)
        out["points"][name] = entry
    return out


def _spans(frames: list[int], step: int = 1) -> list[list[int]]:
    spans: list[list[int]] = []
    for f in frames:
        if spans and f - spans[-1][1] <= step:
            spans[-1][1] = f
        else:
            spans.append([f, f])
    return spans


def lint_tracks(
    tracks: dict[str, list[list[float]]],
    frames: list[int],
    contacts: dict[str, list[list[int]]],
    com_point: str,
    gravity_per_frame: float,
    slide_tolerance_cm: float = 2.0,
    ballistic_tolerance: float = 0.35,
) -> list[dict]:
    """Pure check over sampled tracks; returns a list of problems with reasons."""
    problems: list[dict] = []
    index = {f: i for i, f in enumerate(frames)}

    for name, spans in contacts.items():
        if name not in tracks:
            continue
        for a, b in spans:
            idx = [index[f] for f in range(a, b + 1) if f in index]
            if len(idx) < 2:
                continue
            anchor = tracks[name][idx[0]]
            drift = max(math.dist(anchor, tracks[name][i]) for i in idx)
            if drift > slide_tolerance_cm:
                problems.append(
                    {
                        "kind": "planted_point_slides",
                        "point": name,
                        "span": [a, b],
                        "drift_cm": round(drift, 2),
                        "why": f"{name} is a support from {a} to {b} but moves {drift:.1f} cm. "
                        "Hold its world position across the span (same position on both keys).",
                    }
                )

    supported = set()
    for spans in contacts.values():
        for a, b in spans:
            supported.update(range(a, b + 1))
    airborne = _spans(
        [f for f in frames if f not in supported], frames[1] - frames[0] if len(frames) > 1 else 1
    )
    if com_point in tracks:
        com = tracks[com_point]
        for a, b in airborne:
            if a == frames[0] or b == frames[-1]:
                continue  # clip edges: no takeoff or landing inside the range
            t = b - a + 2  # frames between the last support frame and the next one
            i0, i1 = index[a], index[b]
            takeoff = com[index[a - 1]] if (a - 1) in index else com[i0]
            landing = com[index[b + 1]] if (b + 1) in index else com[i1]
            heights = [p[1] for p in com[i0 : i1 + 1]]
            rise = max(heights) - takeoff[1]
            # ballistic launch that leaves at the takeoff height and arrives at the landing
            # height after t frames: v0 = dy / t + g t / 2, apex rise = v0^2 / 2g
            v0 = (landing[1] - takeoff[1]) / t + gravity_per_frame * t / 2.0
            expected = max(v0, 0.0) ** 2 / (2.0 * gravity_per_frame)
            ratio = rise / expected if expected else float("inf")
            entry = {
                "kind": "airborne_phase",
                "span": [a, b],
                "frames": t,
                "rise_cm": round(rise, 2),
                "ballistic_rise_cm": round(expected, 2),
                "ratio": round(ratio, 2),
            }
            if abs(ratio - 1) > ballistic_tolerance:
                entry["why"] = (
                    f"Airborne for {t} frames from this takeoff to this landing height, a "
                    f"ballistic body peaks {expected:.1f} cm above takeoff; {com_point} peaks "
                    f"{rise:.1f} cm above it. "
                    + (
                        "The flight is too long for the height: shorten it or raise the arc."
                        if ratio < 1
                        else "The arc is too high for the flight time: "
                        "lengthen it or lower the arc."
                    )
                )
            problems.append(entry)
    return problems


@mcp.tool()
def lint_take(
    frame_start: int,
    frame_end: int,
    contacts: dict[str, list[list[int]]],
    com_point: str = "pelvis_MainPoint",
    slide_tolerance_cm: float = 2.0,
    ballistic_tolerance: float = 0.35,
) -> dict:
    """Check a blocked take for physically impossible motion before running physics.

    ``contacts`` maps support points to the frame spans they carry weight, the same
    spans you give ``set_fulcrum_spans``. The lint reports:

    - ``planted_point_slides``: a support point that moves more than
      ``slide_tolerance_cm`` during its span (feet skating between keys).
    - ``airborne_phase``: for each span with no support, how far ``com_point``
      rises compared with a ballistic arc under the scene's gravity. A ratio far
      from 1 means AutoPhysics cannot follow the keys.

    The pelvis is a stand-in for the centre of mass; pass ``"Center of Mass"`` if
    the rig has that object. Passing the lint does not mean the take reads well.
    """
    timing = _scall("scene_timing")
    g = timing.get("gravity_per_frame") or GRAVITY_CM_S2 / 900.0
    names = sorted(set(contacts) | {com_point})
    tracks = _sample(names, frame_start, frame_end, 1)
    frames = list(range(frame_start, frame_end + 1))
    problems = lint_tracks(
        tracks, frames, contacts, com_point, g, slide_tolerance_cm, ballistic_tolerance
    )
    return {
        "gravity_per_frame_cm": g,
        "clip_frames": timing.get("frames"),
        "problems": [p for p in problems if "why" in p],
        "airborne_phases": [p for p in problems if p["kind"] == "airborne_phase"],
        "passed": not any("why" in p for p in problems),
    }
