"""Edit whole takes: keys report, retime, mirror, and copy between rigs.

All three edits work on controller point positions, which fully define a
Cascadeur point rig's pose. They read the take, transform it in Python, and write
it back as keys with ``set_pose_keys`` (one undoable modification). Run them on a
saved copy of the scene: they replace the take's keys.
"""

from __future__ import annotations

from typing import Any

from poppet_mcp import pipeline_tools as pt
from poppet_mcp.server import mcp

MAX_SAMPLES = 2048
POINT_TYPES = ["Point", "Limb Direction"]


@mcp.tool()
def keys_report() -> dict:
    """Key frames per layer and the interpolation after each key, plus the clip length.

    Use it to confirm keys landed where you expect and that sections are BEZIER
    (smooth) rather than held, before physics or review.
    """
    return pt._scall("keys_report")


def _controller_names(scene_name: str | None = None) -> list[str]:
    params: dict[str, Any] = {"types": POINT_TYPES}
    rest = (
        pt._call("rig_rest_dump", scene_name=scene_name, **params)
        if scene_name
        else pt._scall("rig_rest_dump", **params)
    )
    return sorted(rest["points"])


def read_take(
    frames: list[int], names: list[str], scene_name: str | None = None
) -> dict[int, dict[str, list[float]]]:
    """World positions of ``names`` at each of ``frames``: {frame: {name: [x, y, z]}}."""
    out: dict[int, dict[str, list[float]]] = {f: {} for f in frames}
    frames = sorted(frames)
    for i in range(0, len(names), 32):
        chunk = names[i : i + 32]
        per_call = max(1, MAX_SAMPLES // len(chunk))
        # sample contiguous runs so frame_step=1 calls stay under the sample cap
        start = 0
        while start < len(frames):
            run = [frames[start]]
            while (
                start + len(run) < len(frames)
                and len(run) < per_call
                and frames[start + len(run)] == run[-1] + 1
            ):
                run.append(frames[start + len(run)])
            params = dict(
                object_names=chunk, frame_start=run[0], frame_end=run[-1], frame_step=1, local=False
            )
            data = (
                pt._call("motion_sample", scene_name=scene_name, **params)
                if scene_name
                else pt._scall("motion_sample", **params)
            )
            for row in data["frames"]:
                for name in chunk:
                    out[row["frame"]][name] = row["objects"][name]["position"]
            start += len(run)
    return out


def _lerp(a: list[float], b: list[float], t: float) -> list[float]:
    return [x + (y - x) * t for x, y in zip(a, b)]


def retime_positions(
    take: dict[int, dict[str, list[float]]], factor: float, every_frame: bool
) -> dict[int, dict[str, list[float]]]:
    """Scale timing by ``factor`` (2.0 = twice as long). Pure function for tests."""
    frames = sorted(take)
    first = frames[0]
    if not every_frame:
        return {first + round((f - first) * factor): take[f] for f in frames}
    last_new = first + round((frames[-1] - first) * factor)
    out = {}
    for nf in range(first, last_new + 1):
        src = first + (nf - first) / factor
        lo = max(f for f in frames if f <= src) if src >= first else first
        hi = min((f for f in frames if f >= src), default=frames[-1])
        t = 0.0 if hi == lo else (src - lo) / (hi - lo)
        out[nf] = {n: _lerp(take[lo][n], take[hi][n], t) for n in take[lo]}
    return out


def mirror_positions(
    take: dict[int, dict[str, list[float]]], plane_x: float = 0.0
) -> dict[int, dict[str, list[float]]]:
    """Swap left and right and reflect across the plane x = ``plane_x``."""

    def partner(name: str) -> str:
        if name.endswith("_l"):
            return name[:-2] + "_r"
        if name.endswith("_r"):
            return name[:-2] + "_l"
        return name

    out = {}
    for f, pose in take.items():
        out[f] = {}
        for name in pose:
            src = pose.get(partner(name), pose[name])
            out[f][name] = [2 * plane_x - src[0], src[1], src[2]]
    return out


def _scale_spans(
    spans: dict[str, list[list[int]]], factor: float, first: int
) -> dict[str, list[list[int]]]:
    return {
        n: [
            [first + round((a - first) * factor), first + round((b - first) * factor)]
            for a, b in rs
        ]
        for n, rs in spans.items()
        if rs
    }


def _frames_for(every_frame: bool, frame_start: int | None, frame_end: int | None) -> list[int]:
    report = pt._scall("keys_report")
    if every_frame:
        start = frame_start if frame_start is not None else 0
        end = frame_end if frame_end is not None else report["frames_count"] - 1
        return list(range(start, end + 1))
    keys = report["key_frames"]
    return [
        f
        for f in keys
        if (frame_start is None or f >= frame_start) and (frame_end is None or f <= frame_end)
    ]


@mcp.tool()
def retime_take(
    factor: float, every_frame: bool = False, fulcrum_points: list[str] | None = None
) -> dict:
    """Stretch or compress the whole take's timing; fulcrum spans move with it.

    ``factor`` 2.0 makes the take twice as long, 0.25 turns a 4x slow-motion mocap
    take into real time. ``every_frame=False`` moves the existing keys (blocked
    takes); ``True`` resamples every frame (mocap, where every frame is a key).
    ``fulcrum_points`` are read before the retime and written back scaled.
    """
    if factor <= 0:
        raise ValueError("factor must be positive")
    frames = _frames_for(every_frame, None, None)
    names = _controller_names()
    take = read_take(frames, names)
    spans = {}
    if fulcrum_points:
        spans = pt._scall("fulcrum_spans_get", points=fulcrum_points)["spans"]
    new = retime_positions(take, factor, every_frame)
    length = max(new) + 1
    result = pt.set_pose_keys({str(f): p for f, p in new.items()}, reset_frames=length)
    if spans:
        result["fulcrums"] = pt.set_fulcrum_spans(
            _scale_spans({k: v for k, v in spans.items() if v}, factor, frames[0])
        )
    result.update(old_frames=[frames[0], frames[-1]], new_length=length)
    return result


@mcp.tool()
def mirror_take(plane_x: float = 0.0, fulcrum_points: list[str] | None = None) -> dict:
    """Mirror the take left to right: lead foot and hand swap sides.

    Reflects every controller across the plane x = ``plane_x`` (the travel line)
    and swaps ``_l``/``_r`` names at every key. Fulcrum spans swap sides too when
    ``fulcrum_points`` lists both sides' points.
    """
    frames = _frames_for(False, None, None)
    names = _controller_names()
    take = read_take(frames, names)
    spans = pt._scall("fulcrum_spans_get", points=fulcrum_points)["spans"] if fulcrum_points else {}
    result = pt.set_pose_keys({str(f): p for f, p in mirror_positions(take, plane_x).items()})
    if spans:
        swapped = {}
        for n, rs in spans.items():
            other = n[:-2] + ("_r" if n.endswith("_l") else "_l") if n[-2:] in ("_l", "_r") else n
            swapped[other] = rs or []
        result["fulcrums"] = pt.set_fulcrum_spans({k: v for k, v in swapped.items() if v})
    result["mirrored_keys"] = len(frames)
    return result


@mcp.tool()
def copy_take(
    source_scene: str,
    target_scene: str,
    every_frame: bool = False,
    scale: float | str = "auto",
    fulcrum_points: list[str] | None = None,
) -> dict:
    """Copy a take from one open scene's rig onto another's (for example Quinn to Ada).

    Point names must match (UE5-named rigs do). ``scale="auto"`` scales positions
    by the ratio of the two rigs' pelvis heights at frame 0 around the source's
    starting floor point, so stride length follows leg length; pass a number to
    override or 1.0 to copy as is. Contacts will need re-pinning: run lint_take
    and set_fulcrum_spans on the target afterwards.
    """
    report = pt._call("keys_report", scene_name=source_scene)
    frames = list(range(report["frames_count"])) if every_frame else report["key_frames"]
    src_names = set(_controller_names(source_scene))
    dst_names = set(_controller_names(target_scene))
    names = sorted(src_names & dst_names)
    missing = sorted(dst_names - src_names)
    take = read_take(frames, names, scene_name=source_scene)
    if scale == "auto":
        src_rest = pt._call(
            "rig_rest_dump", scene_name=source_scene, types=["Point"], frame=frames[0]
        )["points"]
        dst_rest = pt._call("rig_rest_dump", scene_name=target_scene, types=["Point"], frame=0)[
            "points"
        ]
        factor = dst_rest["pelvis_MainPoint"][2] / src_rest["pelvis_MainPoint"][2]
    else:
        factor = float(scale)
    origin = take[frames[0]].get("pelvis_MainPoint", [0, 0, 0])
    scaled = {
        f: {
            n: [
                origin[0] + (p[0] - origin[0]) * factor,
                p[1] * factor,
                origin[2] + (p[2] - origin[2]) * factor,
            ]
            for n, p in pose.items()
        }
        for f, pose in take.items()
    }
    params = {
        "keys": {str(f): p for f, p in scaled.items()},
        "reset": True,
        "frames": report["frames_count"],
        "interpolation": "BEZIER",
    }
    result = pt._call("pose_keys_set", scene_name=target_scene, **params)
    if fulcrum_points:
        spans = pt._call("fulcrum_spans_get", scene_name=source_scene, points=fulcrum_points)[
            "spans"
        ]
        result["fulcrums"] = pt._call(
            "fulcrum_spans_set",
            scene_name=target_scene,
            spans={k: v for k, v in spans.items() if v},
        )
    result.update(
        scale=round(factor, 4), copied_points=len(names), target_points_not_in_source=missing
    )
    return result
