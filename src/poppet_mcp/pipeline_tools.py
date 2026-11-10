"""Animation pipeline tools: the authoring loop as typed MCP tools.

These wrap the steps an animator repeats on every take: check the link, audit the
rig, block key poses from a spec, pin contacts with fulcrum spans, add obstacles as
collision geometry, run the physics pass with a before/after report, and render a
frame range to stills, an MP4 and a contact sheet without Cascadeur's crashing
video export.

Registered on the same FastMCP instance as ``server.py``.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from poppet_mcp.posing import Rig
from poppet_mcp.server import _call, _connection, mcp

DATA_DIR = Path(__file__).with_name("data")
CASCADEUR_LOG = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Nekki Limited"
    / "Cascadeur"
    / "logs"
    / "cascadeur_log.log"
)
LOGIN_ERROR = re.compile(
    r"invalid or expired JSON Web Token|token (?:has )?expired|unauthori[sz]ed", re.I
)
CONTACT_POINTS_UE = [
    "hand_MainPoint_l",
    "hand_MainPoint_r",
    "foot_MainPoint_l",
    "foot_MainPoint_r",
    "ball_MainPoint_l",
    "ball_MainPoint_r",
]
CONTACT_POINTS_CASCADEUR = [
    "hand_MainPoint_l",
    "hand_MainPoint_r",
    "foot_MainPoint_l",
    "foot_MainPoint_r",
    "toe_MainPoint_l",
    "toe_MainPoint_r",
]

_rig_cache: dict[str, Rig] = {}


# ----------------------------------------------------------------------------
# Preflight
# ----------------------------------------------------------------------------


def _scan_log(path: Path, max_bytes: int = 400_000) -> dict:
    if not path.exists():
        return {"log_found": False}
    size = path.stat().st_size
    with path.open("rb") as handle:
        handle.seek(max(0, size - max_bytes))
        tail = handle.read().decode("utf-8", errors="replace").splitlines()
    hits = [line.strip()[:300] for line in tail if LOGIN_ERROR.search(line)]
    return {
        "log_found": True,
        "log_path": str(path),
        "login_errors": hits[-3:],
        "login_error_count": len(hits),
    }


@mcp.tool()
def cascadeur_preflight() -> dict:
    """Run before any Cascadeur work: link, scene, runtime version and login state.

    Returns ``ready`` plus a ``problems`` list with the fix for each one. Checks:
    the script server answers; a scene is open; the in-app runtime matches this
    client; Cascadeur's log has no expired-login errors in its recent tail (video
    mocap and other account features fail silently when the token has expired).
    """
    problems: list[str] = []
    report: dict[str, Any] = {}
    connection = _connection()
    report["url"] = connection.url
    try:
        connection.health()
        report["connected"] = True
    except Exception as exc:
        report["connected"] = False
        problems.append(
            "Script server not reachable. In Cascadeur: Window > Python Console, run the "
            "cascadeur-bootstrap line (or install the autostart add-on). Detail: " + str(exc)
        )
    if report["connected"]:
        try:
            ping = connection.request("ping", {})
            report.update(ping)
            if not ping.get("has_scene"):
                problems.append("No scene is open in Cascadeur. Open or create one.")
        except Exception as exc:
            problems.append(f"Runtime ping failed: {exc}")
    log = _scan_log(CASCADEUR_LOG)
    report["log"] = log
    if log.get("login_error_count"):
        problems.append(
            "Cascadeur's log shows an expired or invalid login token. Sign in again "
            "(account menu, top right) before video mocap or other account features."
        )
    report["problems"] = problems
    report["ready"] = not problems
    return report


# ----------------------------------------------------------------------------
# Rig
# ----------------------------------------------------------------------------


def _expected_joints(expected: str | list[str] | None) -> list[str]:
    if expected is None or expected == "none":
        return []
    if isinstance(expected, list):
        return expected
    path = DATA_DIR / f"{expected}_joints.json"
    if not path.exists():
        options = sorted(
            p.name.removesuffix("_joints.json") for p in DATA_DIR.glob("*_joints.json")
        )
        raise ValueError(f"unknown joint reference {expected!r}; options: {options}")
    return json.loads(path.read_text(encoding="utf-8"))["joints"]


@mcp.tool()
def rig_audit(
    expected_joints: str | list[str] = "ue5_quinn", contact_points: list[str] | None = None
) -> dict:
    """Audit the open scene's rig before posing or exporting.

    Compares joint objects against a reference list (``"ue5_quinn"`` ships with the
    package; pass a list for other skeletons, or ``"none"``), counts objects by type,
    and checks that the hand and foot controllers carry FulcrumPoint behaviours so
    contacts can be pinned. ``passed`` is false when reference joints are missing
    or a contact point lacks its fulcrum behaviour. Extra joints (twist, corrective,
    facial) are listed but do not fail the audit.
    """
    expected = _expected_joints(expected_joints)
    points = contact_points
    if points is None:
        rest = _call("rig_rest_dump", types=["Point"])
        names = set(rest["points"])
        points = CONTACT_POINTS_UE if "ball_MainPoint_l" in names else CONTACT_POINTS_CASCADEUR
    result = _call("rig_audit", expected_joints=expected, contact_points=points)
    missing_fulcrum = [
        n
        for n, b in result["contact_point_behaviours"].items()
        if not b or not b.get("FulcrumPoint")
    ]
    result["contact_points_without_fulcrum"] = missing_fulcrum
    result["passed"] = not result["missing_joints"] and not missing_fulcrum
    return result


def _rig(rest_file: str | None = None, refresh: bool = False) -> tuple[Rig, str]:
    """Load the solver's rest pose: from a saved file, else frame 0 of the open scene."""
    if rest_file:
        shipped = DATA_DIR / f"{rest_file}_rest.json"
        path = shipped if shipped.exists() else Path(rest_file)
        data = json.loads(path.read_text(encoding="utf-8"))
        return Rig(data.get("points", data)), f"file:{rest_file}"
    scene = _call("scene_info").get("scene_name") or "scene"
    if refresh or scene not in _rig_cache:
        rest = _call("rig_rest_dump", types=["Point", "Limb Direction"], frame=0)
        _rig_cache[scene] = Rig(rest["points"])
    return _rig_cache[scene], f"frame 0 of {scene}"


@mcp.tool()
def get_rig_rest(frame: int = 0, include_joints: bool = False, save_to: str | None = None) -> dict:
    """World positions of the rig's controller points (and joints) at ``frame``.

    The pose solver needs the rig's true rest pose. Capture it once from a freshly
    loaded, unanimated rig with ``save_to`` (a .json path), then pass that file as
    ``rest_file`` to ``block_poses``. Frame 0 of a scene that already has keys is
    not a rest pose. Also reports the ankle and hip heights the solver uses, so
    specs can put soles on the floor.
    """
    types = ["Point", "Limb Direction"] + (["Joint"] if include_joints else [])
    rest = _call("rig_rest_dump", types=types, frame=frame)
    if save_to:
        Path(save_to).parent.mkdir(parents=True, exist_ok=True)
        Path(save_to).write_text(json.dumps(rest, indent=1), encoding="utf-8")
        rest["saved_to"] = save_to
    try:
        rig = Rig(rest["points"])
        rest["naming"] = rig.naming
        rest["ankle_height"] = rig.ankle_height
        rest["hip_height"] = rig.hip_height
    except ValueError as exc:
        rest["solver_error"] = str(exc)
    return rest


# ----------------------------------------------------------------------------
# Posing
# ----------------------------------------------------------------------------


@mcp.tool()
def set_pose_keys(keys: dict[str, dict[str, list[float]]], reset_frames: int | None = None) -> dict:
    """Key world positions for named controller points: ``{frame: {point: [x, y, z]}}``.

    Writes every value inside one undoable scene modification and sets a key on
    every animation layer at each frame. ``reset_frames`` clears all existing keys
    first and sets the clip length (use it when re-blocking a take from scratch).
    """
    params: dict[str, Any] = {"keys": keys}
    if reset_frames:
        params.update(reset=True, frames=int(reset_frames))
    return _call("pose_keys_set", **params)


@mcp.tool()
def block_poses(
    poses: list[dict],
    reset_frames: int | None = None,
    rest_file: str | None = None,
    refresh_rig: bool = False,
) -> dict:
    """Block key poses from compact specs and key them on the open rig.

    ``poses`` is a list of ``{"frame": int, "label": str, "pose": {...}}``. A pose
    gives the pelvis position and rotation, spine/neck/head rotations, and world
    targets for both hands and feet; the solver fills every other body controller
    keeping the rig's bone lengths. See ``poppet_mcp/posing.py`` for every key.
    Units are cm, Y up, the character faces +Z at rest, left is +X.

    Block from reference: read the athlete's key frames first, then write one pose
    per key moment (contact, down, passing, up, plant, takeoff, apex, landing).

    ``rest_file`` is a rest pose saved with ``get_rig_rest(save_to=...)``, or
    ``"ue5_quinn"`` for the shipped UE5 Quinn rest pose (Quinn, Manny-proportioned
    rigs need their own capture). Without
    it the solver reads frame 0 of the open scene, which is only correct while the
    rig is unanimated; the reply's ``rest_source`` says which was used.
    """
    rig, rest_source = _rig(rest_file=rest_file, refresh=refresh_rig)
    keys: dict[str, dict[str, list[float]]] = {}
    labels = {}
    for item in poses:
        frame = int(item["frame"])
        keys[str(frame)] = rig.solve(item["pose"])
        labels[frame] = item.get("label", "")
    result = set_pose_keys(keys, reset_frames=reset_frames)
    result.update(
        naming=rig.naming, ankle_height=rig.ankle_height, labels=labels, rest_source=rest_source
    )
    return result


# ----------------------------------------------------------------------------
# Contacts and obstacles
# ----------------------------------------------------------------------------


@mcp.tool()
def set_fulcrum_spans(spans: dict[str, list[list[int]]]) -> dict:
    """Pin contacts: turn each point's fulcrum on for the given frame spans, off elsewhere.

    ``spans`` maps a controller point to inclusive ``[first, last]`` frame ranges,
    e.g. ``{"foot_MainPoint_l": [[12, 16]], "hand_MainPoint_l": [[25, 29]]}``.
    AutoPhysics then treats those points as fixed supports. The reply reads the
    state back per frame so you can confirm what Cascadeur stored.
    """
    return _call("fulcrum_spans_set", spans=spans)


def _box_glb(path: Path, lo, hi, name: str) -> None:
    import struct

    import numpy as np

    lo, hi = np.array(lo, float), np.array(hi, float)
    faces = [
        ((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]),
        ((-1, 0, 0), [(0, 0, 1), (0, 1, 1), (0, 1, 0), (0, 0, 0)]),
        ((0, 1, 0), [(0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)]),
        ((0, -1, 0), [(0, 0, 1), (0, 0, 0), (1, 0, 0), (1, 0, 1)]),
        ((0, 0, 1), [(1, 0, 1), (1, 1, 1), (0, 1, 1), (0, 0, 1)]),
        ((0, 0, -1), [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)]),
    ]
    pos, nrm, idx = [], [], []
    for n, corners in faces:
        base = len(pos)
        for c in corners:
            pos.append(lo + (hi - lo) * np.array(c))
            nrm.append(n)
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    pos = np.array(pos, np.float32)
    nrm = np.array(nrm, np.float32)
    idx = np.array(idx, np.uint16)
    blob = pos.tobytes() + nrm.tobytes() + idx.tobytes()
    blob += b"\0" * (-len(blob) % 4)
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": name}],
        "meshes": [
            {
                "name": name,
                "primitives": [
                    {"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0}
                ],
            }
        ],
        "materials": [
            {
                "name": name,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.85, 0.6, 0.45, 1],
                    "metallicFactor": 0,
                    "roughnessFactor": 0.9,
                },
            }
        ],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": pos.nbytes, "target": 34962},
            {"buffer": 0, "byteOffset": pos.nbytes, "byteLength": nrm.nbytes, "target": 34962},
            {
                "buffer": 0,
                "byteOffset": pos.nbytes + nrm.nbytes,
                "byteLength": idx.nbytes,
                "target": 34963,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 24,
                "type": "VEC3",
                "min": pos.min(0).tolist(),
                "max": pos.max(0).tolist(),
            },
            {"bufferView": 1, "componentType": 5126, "count": 24, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5123, "count": 36, "type": "SCALAR"},
        ],
    }
    js = json.dumps(gltf).encode()
    js += b" " * (-len(js) % 4)
    with path.open("wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(js) + 8 + len(blob)))
        f.write(struct.pack("<I4s", len(js), b"JSON") + js)
        f.write(struct.pack("<I4s", len(blob), b"BIN\0") + blob)


@mcp.tool()
def add_box_obstacle(
    min_cm: list[float],
    max_cm: list[float],
    name: str = "Obstacle",
    make_kinematic_collision: bool = True,
) -> dict:
    """Add a box obstacle (vault box, wall, rail block) to the scene, in cm.

    ``min_cm``/``max_cm`` are opposite corners in world space (Y up). With
    ``make_kinematic_collision`` the new mesh is selected and Cascadeur's
    ``Collision.Add kinematic mesh`` action runs, so AutoPhysics and collision
    cleaning treat it as solid. Verify by eye: the action is fire-and-forget.
    """
    folder = Path(os.environ.get("LOCALAPPDATA", ".")) / "cascadeur-mcp" / "obstacles"
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    path = folder / f"{safe}.glb"
    _box_glb(path, [v / 100 for v in min_cm], [v / 100 for v in max_cm], safe)
    imported = _call("glb_import", path=str(path), scale_factor=100.0)["imported"]
    result: dict[str, Any] = {"glb": str(path), "imported": imported}
    if make_kinematic_collision and imported:
        meshes = [o["name"] for o in imported if o.get("type") and "mesh" in o["type"].lower()] or [
            imported[0]["name"]
        ]
        _call("selection_set", object_names=meshes)
        _call("call_action", action_id="Collision.Add kinematic mesh")
        result["kinematic_collision_requested_for"] = meshes
    return result


# ----------------------------------------------------------------------------
# Physics pass
# ----------------------------------------------------------------------------

PHYSICS_ACTIONS = {
    "autophysics_on": "AutoPhysicsTool.Switch Auto Physics",
    "autophysics_snap": "AutoPhysicsTool.Snap to Auto Physics",
    "collision_cleaning": "FixCollisionsTool.Collision Penetration Cleaning",
    "autoposing": "AutoPosingTool.AutoPosing",
}


def _sample(objects: list[str], start: int, end: int, step: int) -> dict[str, list]:
    data = _call(
        "motion_sample",
        object_names=objects,
        frame_start=start,
        frame_end=end,
        frame_step=step,
        local=False,
    )
    out: dict[str, list] = {n: [] for n in objects}
    for row in data["frames"]:
        for name in objects:
            out[name].append(row["objects"][name]["position"])
    return out


def _max_delta(a: dict[str, list], b: dict[str, list]) -> dict[str, float]:
    return {n: round(max((math.dist(p, q) for p, q in zip(a[n], b[n])), default=0.0), 3) for n in a}


@mcp.tool()
def physics_pass(
    objects: list[str],
    frame_start: int,
    frame_end: int,
    steps: list[str] | None = None,
    frame_step: int = 1,
    settle_timeout_sec: float = 20.0,
) -> dict:
    """Run Cascadeur's physics tools and report what they changed.

    ``steps`` are run in order from: ``autophysics_on`` (toggle AutoPhysics),
    ``autophysics_snap`` (bake the physics result into keys), ``collision_cleaning``
    and ``autoposing``. Defaults to ``["autophysics_snap", "collision_cleaning"]``.

    ``objects`` (up to 32 controller points, e.g. pelvis, hands, feet) are sampled
    over the range before and after. The native actions have no completion signal,
    so the tool re-samples until two reads match or the timeout passes and reports
    ``settled``. Per-object ``max_change_cm`` says how far physics moved each
    point. A change is not proof of quality: render the range and look.

    Prerequisites set in the UI: the frame interval AutoPhysics works on and its
    strength. The Python API exposes no setter for those panels in 2026.2.3.
    """
    steps = steps or ["autophysics_snap", "collision_cleaning"]
    unknown = [s for s in steps if s not in PHYSICS_ACTIONS]
    if unknown:
        raise ValueError(f"unknown steps {unknown}; options: {sorted(PHYSICS_ACTIONS)}")
    before = _sample(objects, frame_start, frame_end, frame_step)
    invoked = []
    for step in steps:
        _call("call_action", action_id=PHYSICS_ACTIONS[step])
        invoked.append(PHYSICS_ACTIONS[step])
    deadline = time.monotonic() + settle_timeout_sec
    previous = None
    settled = False
    after = before
    while time.monotonic() < deadline:
        time.sleep(1.0)
        after = _sample(objects, frame_start, frame_end, frame_step)
        if previous is not None and all(v == 0 for v in _max_delta(previous, after).values()):
            settled = True
            break
        previous = after
    change = _max_delta(before, after)
    return {
        "invoked": invoked,
        "settled": settled,
        "max_change_cm": change,
        "changed": any(v > 0.01 for v in change.values()),
        "note": (
            "Settled means two consecutive samples matched; "
            "it does not certify convergence or balance."
        ),
    }


# ----------------------------------------------------------------------------
# Viewport and rendering
# ----------------------------------------------------------------------------

CAMERA_PRESETS = {
    # offset from the followed point, in cm (character faces +Z, left is +X)
    "side_left": (520.0, 15.0, 0.0),
    "side_right": (-520.0, 15.0, 0.0),
    "three_quarter": (330.0, 65.0, 270.0),
    "front": (0.0, 15.0, 520.0),
    "back": (0.0, 40.0, -520.0),
}


@mcp.tool()
def set_viewport(
    mode: str | None = None,
    camera_position: list[float] | None = None,
    camera_target: list[float] | None = None,
    frame: int | None = None,
) -> dict:
    """Set the active viewport's visualiser mode, camera and current frame.

    ``mode`` is a ``csc.view.ViewportMode`` name: ``View`` (clean, mesh only),
    ``Controller``, ``PointController``, ``Joint``, ``Mesh``, ``AutoPosing``,
    ``Rigging``. Use ``View`` for review renders so controllers don't hide the body.
    """
    params: dict[str, Any] = {}
    if mode:
        params["mode"] = mode
    if camera_position and camera_target:
        params["camera"] = {"position": camera_position, "target": camera_target}
    if frame is not None:
        params["frame"] = frame
    return _call("viewport_set", **params)


def _wait_file(path: Path, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    last = -1
    while time.monotonic() < deadline:
        if path.exists():
            size = path.stat().st_size
            if size > 1000 and size == last:
                return True
            last = size
        time.sleep(0.1)
    return path.exists()


def _camera_for(preset: str, focus: list[float], distance: float | None) -> dict:
    if preset not in CAMERA_PRESETS:
        raise ValueError(f"unknown camera preset {preset!r}; options: {sorted(CAMERA_PRESETS)}")
    off = CAMERA_PRESETS[preset]
    if distance:
        norm = math.hypot(off[0], off[2]) or 1.0
        off = (off[0] / norm * distance, off[1], off[2] / norm * distance)
    target = [focus[0], focus[1] - 10.0, focus[2]]
    return {"position": [focus[0] + off[0], focus[1] + off[1], focus[2] + off[2]], "target": target}


def make_contact_sheet_file(
    images: list[Path],
    out_path: Path,
    cols: int = 4,
    labels: list[str] | None = None,
    cell_width: int = 480,
) -> Path:
    from PIL import Image, ImageDraw

    opened = [Image.open(p).convert("RGB") for p in images]
    if not opened:
        raise ValueError("no images for the contact sheet")
    w0, h0 = opened[0].size
    cell_h = int(cell_width * h0 / w0)
    rows = math.ceil(len(opened) / cols)
    sheet = Image.new("RGB", (cols * cell_width, rows * cell_h), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    for i, img in enumerate(opened):
        x, y = (i % cols) * cell_width, (i // cols) * cell_h
        sheet.paste(img.resize((cell_width, cell_h)), (x, y))
        if labels and i < len(labels) and labels[i]:
            draw.rectangle([x, y, x + 8 * len(labels[i]) + 10, y + 18], fill=(0, 0, 0))
            draw.text((x + 5, y + 3), labels[i], fill=(255, 255, 255))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


@mcp.tool()
def make_contact_sheet(
    images: list[str],
    out_path: str,
    cols: int = 4,
    labels: list[str] | None = None,
    cell_width: int = 480,
) -> dict:
    """Tile images into one contact sheet PNG, read left to right, top row first."""
    path = make_contact_sheet_file(
        [Path(p) for p in images], Path(out_path), cols, labels, cell_width
    )
    return {"path": str(path), "count": len(images)}


@mcp.tool()
def render_frames(
    frame_start: int,
    frame_end: int,
    out_dir: str,
    frame_step: int = 1,
    width: int = 1280,
    height: int = 720,
    mode: str = "View",
    camera_preset: str | None = "three_quarter",
    follow_point: str | None = "pelvis_MainPoint",
    track_camera: bool = False,
    camera_distance: float | None = None,
    camera_position: list[float] | None = None,
    camera_target: list[float] | None = None,
    fps: int = 30,
    encode_mp4: bool = True,
    contact_sheet_every: int = 0,
    frame_timeout_sec: float = 15.0,
) -> dict:
    """Render a frame range to PNG stills, then an MP4 and a contact sheet, outside Cascadeur.

    The safe replacement for Cascadeur's ``play_to_video_file`` (which crashed the
    app from script on 2026.2.3). Each frame is one still render; the client waits
    for each PNG before moving on, then ffmpeg encodes ``<out_dir>/take.mp4`` at
    ``fps`` (use the scene's frame rate for real-time playback).

    Camera: either an explicit ``camera_position``/``camera_target``, or a
    ``camera_preset`` (``side_left``, ``side_right``, ``three_quarter``, ``front``,
    ``back``) placed relative to ``follow_point``. The camera stays fixed at the
    first frame's framing unless ``track_camera`` is set. Fixed framing is the
    honest review shot: the body travels through the frame and feet stay visible.

    ``contact_sheet_every`` > 0 also writes ``sheet.png`` from every Nth frame.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames = list(range(frame_start, frame_end + 1, frame_step))
    focus_track: dict[int, list[float]] = {}
    if not (camera_position and camera_target) and camera_preset and follow_point:
        samples = _sample([follow_point], frame_start, frame_end, frame_step)[follow_point]
        focus_track = dict(zip(frames, samples))
    _call("viewport_set", mode=mode)
    written: list[str] = []
    failed: list[int] = []
    for i, frame in enumerate(frames):
        params: dict[str, Any] = {"frame": frame}
        if camera_position and camera_target:
            if i == 0:
                params["camera"] = {"position": camera_position, "target": camera_target}
        elif focus_track and (track_camera or i == 0):
            params["camera"] = _camera_for(camera_preset, focus_track[frame], camera_distance)
        _call("viewport_set", **params)
        path = out / f"{frame:04d}.png"
        if path.exists():
            path.unlink()
        _call("viewport_screenshot", path=str(path), width=width, height=height)
        if i == 0:  # the first render after a camera move can show the old view; render it twice
            _wait_file(path, frame_timeout_sec)
            path.unlink(missing_ok=True)
            _call("viewport_screenshot", path=str(path), width=width, height=height)
        if _wait_file(path, frame_timeout_sec):
            written.append(str(path))
        else:
            failed.append(frame)
    result: dict[str, Any] = {
        "out_dir": str(out),
        "frames_written": len(written),
        "frames_failed": failed,
    }
    if encode_mp4 and written and not failed:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            mp4 = out / "take.mp4"
            cmd = [
                ffmpeg,
                "-v",
                "error",
                "-y",
                "-framerate",
                str(fps / frame_step),
                "-start_number",
                str(frame_start),
                "-i",
                str(out / "%04d.png"),
                "-vf",
                f"scale={width}:-2",
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                str(mp4),
            ]
            if frame_step != 1:
                listing = out / "frames.txt"
                listing.write_text(
                    "".join(
                        f"file '{Path(p).name}'\nduration {frame_step / fps}\n" for p in written
                    )
                )
                cmd = [
                    ffmpeg,
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(listing),
                    "-c:v",
                    "libx264",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-r",
                    str(fps),
                    str(mp4),
                ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            result["mp4"] = str(mp4) if proc.returncode == 0 else None
            if proc.returncode:
                result["mp4_error"] = proc.stderr[-800:]
        else:
            result["mp4_error"] = "ffmpeg not found on PATH"
    if contact_sheet_every and written:
        picks = written[::contact_sheet_every]
        labels = [f"f{Path(p).stem.lstrip('0') or '0'}" for p in picks]
        result["contact_sheet"] = str(
            make_contact_sheet_file([Path(p) for p in picks], out / "sheet.png", 4, labels)
        )
    return result
