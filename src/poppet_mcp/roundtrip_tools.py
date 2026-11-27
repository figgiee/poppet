"""Unreal round trip: bring an Unreal clip in upright, unbake it into key poses, review it
from the game camera, and check it against Unreal's own bone positions.

The Unreal side writes a readback JSON (component-space bone positions per frame, in
Unreal axes: X, Y forward, Z up). On a Cascadeur Unreal rig, Cascadeur X = Unreal X,
Cascadeur Y (up) = Unreal Z, and Cascadeur Z (forward) = Unreal Y.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from poppet_mcp import fbx_axis
from poppet_mcp import pipeline_tools as pt
from poppet_mcp.server import _call, mcp

CHECK_JOINTS = [
    "pelvis",
    "foot_l",
    "foot_r",
    "ball_l",
    "ball_r",
    "head",
    "hand_l",
    "hand_r",
    "weapon_r",
]
HEIGHT_JOINTS = ["pelvis", "foot_l", "foot_r"]
MAX_SAMPLES = 2048


JSON_MARK = "@@poppet-json@@"


def _exec_json(code: str) -> Any:
    """Run in-app code that prints ``JSON_MARK`` + a JSON document; return the decoded value.

    The value goes through stdout rather than ``result`` because the runtime shortens
    long reprs.
    """
    out = _call("exec_csc", code=code)
    text = out.get("stdout", "") if isinstance(out, dict) else ""
    if JSON_MARK not in text:
        raise RuntimeError(f"in-app code printed no result: {out!r}")
    return json.loads(text.rsplit(JSON_MARK, 1)[1].strip().splitlines()[0])


def sample_positions(
    names: list[str], frames: int, step: int = 1
) -> dict[int, dict[str, list[float]]]:
    """World positions of ``names`` for frames 0..frames-1 (every ``step``)."""
    out: dict[int, dict[str, list[float]]] = {}
    per_call = max(1, MAX_SAMPLES // max(1, len(names)))
    start = 0
    while start < frames:
        end = min(frames - 1, start + (per_call - 1) * step)
        data = pt._scall(
            "motion_sample",
            object_names=names,
            frame_start=start,
            frame_end=end,
            frame_step=step,
            local=False,
        )
        for row in data["frames"]:
            out[row["frame"]] = {n: row["objects"][n]["position"] for n in names}
        start = end + step
    return out


def unreal_to_cascadeur(p: list[float]) -> list[float]:
    return [p[0], p[2], p[1]]


def compare_to_unreal(
    casc: dict[int, dict[str, list[float]]], readback: dict, tolerance_cm: float = 1.0
) -> dict[str, Any]:
    """Compare Cascadeur joint positions with an Unreal readback of the same clip.

    Frames are matched by time, so a 60 fps Unreal clip imported at 30 fps compares
    Cascadeur frame f with Unreal frame 2f. ``passed`` is the brief's check: pelvis and
    both foot heights at frame 0 within ``tolerance_cm``. The whole-clip maxima are
    reported next to it.
    """
    ue = readback["positions"]
    c_frames = sorted(casc)
    c_last = max(c_frames) if c_frames else 0
    ratio = (len(ue) - 1) / c_last if c_last else 1.0
    bones = [b for b in readback["bones"] if c_frames and b in casc[c_frames[0]]]
    worst: dict[str, dict[str, Any]] = {}
    for f in c_frames:
        g = min(len(ue) - 1, round(f * ratio))
        for b in bones:
            cp = casc[f][b]
            up = unreal_to_cascadeur(ue[g][b])
            dh = abs(cp[1] - up[1])
            d3 = sum((a - c) ** 2 for a, c in zip(cp, up)) ** 0.5
            w = worst.setdefault(
                b, {"height_cm": 0.0, "height_frame": f, "dist_cm": 0.0, "dist_frame": f}
            )
            if dh > w["height_cm"]:
                w["height_cm"], w["height_frame"] = dh, f
            if d3 > w["dist_cm"]:
                w["dist_cm"], w["dist_frame"] = d3, f
    first = c_frames[0] if c_frames else 0
    frame0 = {}
    for b in HEIGHT_JOINTS:
        if b in bones:
            c_h = casc[first][b][1]
            u_h = ue[0][b][2]
            frame0[b] = {
                "cascadeur_cm": round(c_h, 3),
                "unreal_cm": round(u_h, 3),
                "diff_cm": round(c_h - u_h, 3),
            }
    for w in worst.values():
        w["height_cm"] = round(w["height_cm"], 3)
        w["dist_cm"] = round(w["dist_cm"], 3)
    return {
        "unreal_frames": len(ue),
        "cascadeur_frames": c_last + 1,
        "frame_ratio": round(ratio, 4),
        "frame0_heights": frame0,
        "passed": bool(frame0) and all(abs(v["diff_cm"]) <= tolerance_cm for v in frame0.values()),
        "tolerance_cm": tolerance_cm,
        "worst_over_clip": worst,
    }


def _present(names: list[str]) -> list[str]:
    """The subset of ``names`` that are objects in the scene, in the given order."""
    have = {o["name"] for o in pt._scall("objects_list")["objects"]}
    return [n for n in names if n in have]


def _scene_frames() -> int:
    info = pt._scall("scene_timing")
    return int(info["frames"])


@mcp.tool()
def import_ue_clip(
    fbx_path: str,
    base_scene: str | None = None,
    save_as: str | None = None,
    readback_json: str | None = None,
    tolerance_cm: float = 1.0,
) -> dict:
    """Import an Unreal-exported animation FBX onto an Unreal rig so it lands upright.

    Unreal writes Z-up FBX files; Cascadeur's Unreal rigs already hold that turn in
    their root joint, so a plain ``import_fbx`` converts twice and the body lies on its
    back. This tool imports a copy of the file declared Y-up instead.

    ``base_scene``: a rig scene to open first (in a new tab). It is saved straight away
    to ``save_as`` (required with ``base_scene``) so the base file is never edited; keep
    base files read-only anyway, since autosave writes every open scene.
    Without ``base_scene`` the clip goes onto the current scene.

    ``readback_json``: the file written by the Unreal readback script for the same clip.
    The reply then compares pelvis and foot heights at frame 0 (``passed`` within
    ``tolerance_cm``) and the worst difference per bone over the whole clip.
    Cascadeur resamples the clip to the scene frame rate (30 fps by default).
    """
    src = Path(fbx_path)
    if not src.is_file():
        raise ValueError(f"FBX not found: {fbx_path}")
    report: dict[str, Any] = {}
    if base_scene:
        if not save_as:
            raise ValueError(
                "save_as is required with base_scene, so the base file is never edited"
            )
        report["base_scene"] = _call("load_scene", path=base_scene).get("path")
        report["scene"] = _call("save_scene", path=save_as).get("path")
    prepared = Path(tempfile.gettempdir()) / "poppet-ue-import" / src.name
    report["axes"] = fbx_axis.prepare_unreal_fbx(src, prepared)
    pt._scall("fbx_import", path=str(prepared), target="animation")
    frames = _scene_frames()
    report["frames"] = frames
    joints = _present(CHECK_JOINTS)
    casc = sample_positions(joints, frames)
    first = casc.get(0, {})
    report["frame0_heights_cm"] = {n: round(first[n][1], 3) for n in HEIGHT_JOINTS if n in first}
    upright = all(
        first.get("head", [0, 0, 0])[1] > first.get(n, [0, 0, 0])[1] for n in ("foot_l", "foot_r")
    )
    report["upright"] = upright
    if readback_json:
        rb = json.loads(Path(readback_json).read_text())
        report["readback"] = compare_to_unreal(casc, rb, tolerance_cm)
    if save_as and base_scene:
        report["saved"] = _call("save_scene", path=save_as).get("exists")
    return report


_UNBAKE_CODE = """
import csc, json, time
import ml.editable_animation as ea
lv = scene.layers_viewer()
ids = [lid for lid in lv.all_layer_ids() if not lid.is_null()]
n = int(scene.data_viewer().get_animation_size())
keep = set(int(f) for f in {keep!r} if 0 <= int(f) < n) | {{0, n - 1}}
FIX = csc.layers.layer.Interpolation.FIXED
before = sum(len(list(lv.layer(l).key_frame_indices())) for l in ids)

def _prep(model, update, scene_updater):
    le = model.layers_editor()
    for lid in ids:
        layer = lv.layer(lid)
        frames = list(layer.key_frame_indices())
        for f in frames:
            s = layer.sections[f]
            s.interval.interpolation = FIX
            le.set_section(s, f, lid)
        for f in frames:
            if f not in keep:
                le.unset_section(f, lid)

ok = scene.modify_update('cascadeur-mcp: unbake prepare', _prep)
if ok is False:
    raise RuntimeError('prepare step failed; see the Cascadeur event log')
scene.get_layers_selector().set_full_selection_by_parts(ids, 0, n - 1)
defaults = ea.get_parameters()
params = tuple(d if v is None else v for d, v in zip(defaults, {params!r}))
_orig = ea.get_parameters
ea.get_parameters = lambda: params
t0 = time.time()
try:
    ea.run(scene)
finally:
    ea.get_parameters = _orig
layers = []
union = set()
interp = {{}}
for lid in ids:
    layer = lv.layer(lid)
    fr = [int(f) for f in layer.key_frame_indices()]
    union.update(fr)
    layers.append([str(layer.header.name), len(fr)])
    for f in fr:
        k = str(layer.sections[f].interval.interpolation).split('.')[-1]
        interp[k] = interp.get(k, 0) + 1
print({mark!r} + json.dumps({{
    'frames': n, 'keys_before': before, 'keys_after': sum(c for _, c in layers),
    'key_frames': sorted(union), 'keys_per_layer': layers, 'interpolation': interp,
    'parameters': {{'threshold_cm': params[0], 'fingers_threshold': params[1],
                    'ik_preference': params[2], 'clamp_preference': params[3]}},
    'seconds': round(time.time() - t0, 1),
}}))
"""


def fast_frames(positions: dict[int, dict[str, list[float]]], threshold_cm: float) -> list[int]:
    """Frames where a joint leaves the straight line between its two neighbouring frames by
    more than ``threshold_cm``: the peak of a fast swing.

    Cascadeur's unbaking never adds a key inside a span of three frames or fewer, so a swing
    that crosses a metre in two frames (attack 01's hit frame) has to be seeded with a key.
    """
    out = []
    frames = sorted(positions)
    for prev, f, nxt in zip(frames, frames[1:], frames[2:]):
        for name, p in positions[f].items():
            a, b = positions[prev][name], positions[nxt][name]
            mid = [(x + y) / 2 for x, y in zip(a, b)]
            if sum((u - v) ** 2 for u, v in zip(p, mid)) ** 0.5 > threshold_cm:
                out.append(f)
                break
    return out


@mcp.tool()
def unbake_take(
    threshold_cm: float | None = None,
    keep_frames: list[int] | None = None,
    keep_every: int = 0,
    keep_fast: bool = True,
    fingers_threshold: float | None = None,
    ik_preference: float | None = None,
    clamp_preference: float | None = None,
) -> dict:
    """Turn a baked take (a key on every frame) into a few key poses with interpolation.

    Runs Cascadeur's Animation Unbaking: the take is first held as fixed interpolation
    between ``keep_frames`` (plus every ``keep_every``-th frame, plus the first and last
    frame), then Cascadeur picks interpolation per section and adds keys wherever the
    curve drifts more than ``threshold_cm`` from the original motion. Unset parameters
    use the scene's Animation unbaking settings (difference 5 cm by default).

    ``keep_fast`` (on by default) also keeps every frame where a checked joint (hands,
    feet, weapon) bends away from its neighbours by more than the threshold. Cascadeur
    never adds keys inside short spans, so without this a fast swing is cut straight and
    the hands can miss the original path by tens of centimetres at the hit frame.

    Acts on the visible tab. Run it on a saved copy: it replaces the take's keys. The
    reply gives keys before and after, the kept key frames, the interpolation counts,
    and the largest drift per checked joint, measured against the take before unbaking.
    """
    frames = _scene_frames()
    joints = _present(CHECK_JOINTS)
    before = sample_positions(joints, frames)
    keep = set(keep_frames or [])
    if keep_every and keep_every > 0:
        keep.update(range(0, frames, keep_every))
    seeded = fast_frames(before, threshold_cm or 5.0) if keep_fast else []
    keep.update(seeded)
    params = [threshold_cm, fingers_threshold, ik_preference, clamp_preference]
    report = _exec_json(_UNBAKE_CODE.format(keep=sorted(keep), params=params, mark=JSON_MARK))
    after = sample_positions(joints, frames)
    drift: dict[str, Any] = {}
    for f in before:
        for n in joints:
            d = sum((a - b) ** 2 for a, b in zip(before[f][n], after[f][n])) ** 0.5
            if d > drift.get(n, {}).get("cm", -1):
                drift[n] = {"cm": round(d, 3), "frame": f}
    report["seeded_fast_frames"] = seeded
    report["drift"] = drift
    report["max_drift_cm"] = max((v["cm"] for v in drift.values()), default=0.0)
    return report


@mcp.tool()
def review_sheet(
    frame_start: int,
    frame_end: int,
    out_dir: str,
    frame_step: int = 5,
    side_preset: str = "side_left",
    width: int = 960,
    height: int = 540,
) -> dict:
    """Paired review sheet: the game's top-down camera on the top row, a side view below.

    Renders every ``frame_step``-th frame twice (``game_topdown`` preset, then
    ``side_preset``), both fixed at the first frame's framing, and tiles them into
    ``<out_dir>/review.png`` with one column per frame. Judge from the top row first.
    """
    out = Path(out_dir)
    game = pt.render_frames(
        frame_start,
        frame_end,
        str(out / "game"),
        frame_step=frame_step,
        width=width,
        height=height,
        camera_preset="game_topdown",
        encode_mp4=False,
    )
    side = pt.render_frames(
        frame_start,
        frame_end,
        str(out / "side"),
        frame_step=frame_step,
        width=width,
        height=height,
        camera_preset=side_preset,
        encode_mp4=False,
    )
    g_imgs = sorted((out / "game").glob("*.png"))
    s_imgs = sorted((out / "side").glob("*.png"))
    count = min(len(g_imgs), len(s_imgs))
    if not count:
        raise RuntimeError(f"no frames rendered: {game} {side}")
    labels = [f"game f{int(p.stem)}" for p in g_imgs[:count]] + [
        f"side f{int(p.stem)}" for p in s_imgs[:count]
    ]
    sheet = pt.make_contact_sheet_file(
        g_imgs[:count] + s_imgs[:count],
        out / "review.png",
        cols=count,
        labels=labels,
        cell_width=320,
    )
    return {
        "review": str(sheet),
        "frames": count,
        "game_dir": str(out / "game"),
        "side_dir": str(out / "side"),
    }


def remap_frames(keys: list[int], anchors: list[list[int]]) -> dict[int, int]:
    """Map key frames through a piecewise-linear time warp given as ``[[src, dst], ...]``.

    Frames before the first anchor or after the last one shift with that anchor.
    Raises when two keys would land on the same frame.
    """
    pts = sorted((int(s), int(d)) for s, d in anchors)
    if not pts:
        raise ValueError("anchors must hold at least one [source, destination] pair")
    for (s0, d0), (s1, d1) in zip(pts, pts[1:]):
        if s1 <= s0 or d1 < d0:
            raise ValueError("anchors must increase in both source and destination")

    def warp(f: int) -> int:
        if f <= pts[0][0]:
            return f + pts[0][1] - pts[0][0]
        if f >= pts[-1][0]:
            return f + pts[-1][1] - pts[-1][0]
        for (s0, d0), (s1, d1) in zip(pts, pts[1:]):
            if s0 <= f <= s1:
                return round(d0 + (f - s0) * (d1 - d0) / (s1 - s0))
        raise AssertionError("unreachable")

    out = {int(f): warp(int(f)) for f in keys}
    landed: dict[int, int] = {}
    for f, g in sorted(out.items()):
        if g < 0:
            raise ValueError(f"key {f} would move to negative frame {g}")
        if g in landed:
            raise ValueError(
                f"keys {landed[g]} and {f} would both land on frame {g}; drop one first"
            )
        landed[g] = f
    return out


_RETIME_CODE = """
import csc, json
lv = scene.layers_viewer()
dv = scene.data_viewer()
ids = [lid for lid in lv.all_layer_ids() if not lid.is_null()]
mapping = {{int(k): int(v) for k, v in {mapping!r}.items()}}
n_before = int(dv.get_animation_size())
plan = []
for lid in ids:
    layer = lv.layer(lid)
    keys = [int(f) for f in layer.key_frame_indices()]
    missing = [f for f in keys if f not in mapping]
    if missing:
        raise RuntimeError('layer %s has keys without a target: %s' % (layer.header.name, missing))
    sections = {{f: layer.sections[f] for f in keys}}
    FIXED = csc.layers.layer.Interpolation.FIXED
    held = [f for f in keys[:-1] if sections[f].interval.interpolation == FIXED]
    if held:
        raise RuntimeError('layer %s holds baked (FIXED) sections after keys %s; '
                           'run unbake_take first' % (layer.header.name, held[:10]))
    data = []
    settings = []
    for oid in layer.obj_ids:
        for did in dv.get_all_data_id(oid):
            if dv.get_data(did).mode == csc.model.DataMode.Static:
                continue
            data.append((did, {{f: dv.get_data_value(did, f) for f in keys}}))
        for sid in dv.get_all_settings_id(oid):
            try:
                animated = dv.get_setting(sid).mode == csc.model.DataMode.Animation
            except Exception:
                animated = True
            if animated:
                settings.append((sid, {{f: dv.get_setting_value(sid, f) for f in keys}}))
    plan.append((lid, keys, sections, data, settings))

def _apply(model, update, scene_updater):
    le = model.layers_editor()
    de = model.data_editor()
    for lid, keys, sections, data, settings in plan:
        targets = set(mapping[f] for f in keys)
        for f in keys:
            le.set_section(sections[f], mapping[f], lid)
        for f in keys:
            if f not in targets:
                le.unset_section(f, lid)
        for did, values in data:
            for f in keys:
                de.set_data_value(did, mapping[f], values[f])
        for sid, values in settings:
            for f in keys:
                de.set_setting_value(sid, mapping[f], values[f])
    model.fit_animation_size_by_layers()

ok = scene.modify_update('cascadeur-mcp: retime keys', _apply)
if ok is False:
    raise RuntimeError('retime failed; see the Cascadeur event log')
n_after = int(dv.get_animation_size())
print({mark!r} + json.dumps({{'frames_before': n_before, 'frames_after': n_after,
    'layers': len(plan), 'data_channels': sum(len(p[3]) for p in plan)}}))
"""


@mcp.tool()
def retime_keys(anchors: list[list[int]]) -> dict:
    """Move the take's key frames through a time warp, keeping every key's pose.

    ``anchors`` is a list of ``[source_frame, destination_frame]`` pairs. Keys between two
    anchors are spread linearly; keys past the last anchor shift with it. Example: shorten
    a wind-up from 21 frames to 13 and keep the rest of the clip intact:
    ``[[0, 0], [21, 13], [80, 72]]``. Works on unbaked takes (run ``unbake_take`` first):
    the in-between frames follow from the keys and their interpolation. The clip length
    is trimmed to the last key. Acts on the visible tab; run it on a saved copy.
    """
    keys = sorted(set(pt._scall("keys_report")["key_frames"]))
    mapping = remap_frames(keys, anchors)
    report = _exec_json(_RETIME_CODE.format(mapping=mapping, mark=JSON_MARK))
    report["moved"] = {str(f): g for f, g in mapping.items() if f != g}
    report["key_frames_after"] = sorted(set(mapping.values()))
    return report


_EXPORT_JOINTS_CODE = """
import csc, json, os
from csc import fbx
app = csc.app.get_application()
loader = app.get_tools_manager().get_tool('FbxSceneLoader').get_fbx_loader(
    app.get_scene_manager().current_scene())
settings = fbx.FbxSettings()
settings.mode = fbx.FbxSettingsMode.Binary
settings.up_axis = fbx.FbxSettingsAxis.Y
settings.bake_animation = True
settings.apply_euler_filter = True
loader.set_settings(settings)
path = {path!r}
os.makedirs(os.path.dirname(path), exist_ok=True)
loader.export_joints(path)
print({mark!r} + json.dumps({{'path': path, 'exists': os.path.exists(path),
    'frames': int(scene.data_viewer().get_animation_size())}}))
"""


@mcp.tool()
def export_ue_clip(path: str) -> dict:
    """Export the visible tab's skeleton animation (joints only) to a binary FBX for Unreal.

    Joints only: no controllers, meshes or props (a sword stand-in stays out of the file),
    so Unreal can import it as an animation onto its own skeleton. Includes ``weapon_r``
    when the rig has it. Follow with the Unreal import script and a readback.
    """
    if not Path(path).is_absolute():
        raise ValueError("path must be absolute")
    report = _exec_json(
        _EXPORT_JOINTS_CODE.format(path=str(Path(path)).replace("\\", "/"), mark=JSON_MARK)
    )
    target = Path(path)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not (target.exists() and target.stat().st_size > 1000):
        time.sleep(0.2)
    report["exists"] = target.exists()
    report["size_bytes"] = target.stat().st_size if target.exists() else 0
    if target.exists():
        report["axes"] = fbx_axis.axis_report(target)
    return report
