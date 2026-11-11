"""Hands, feet, fingers, AutoPhysics settings and the full action catalogue.

Cascadeur's contact points (hands, feet, balls of the feet) each carry their own
physics and IK properties: FulcrumPoint (state, collision radius, max speed),
Fixation (pin), FulcrumGroup, AutoPhysicsApply (how much AutoPhysics may move the
point), SecondaryMotion, CompensationMotion, Ragdoll, CollisionPenetrationCleaning,
SeparationOfMotion and AngleConstraints. The Center of mass carries per-frame
AutoPhysics weights. Fingers are box controllers posed by local rotation. The
AutoPhysics modes and the scene's tool settings live in two QML panels.

These tools expose all of it. Everything here was first probed live on a test
tab of Cascadeur 2026.2.3 on 2026-11-11.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from poppet_mcp import pipeline_tools as pt
from poppet_mcp.server import mcp

FINGERS = ("index", "middle", "ring", "pinky")
# Local Z flexes (curls) every finger and the thumb on the UE5 Quinn rig, on both
# hands with the same sign; local Y spreads them. Found by rendering 40-degree
# test rotations on each axis.
FINGER_PRESETS: dict[str, dict[str, Any]] = {
    "flat": {"curl": (0, 0, 0), "thumb": (0, 0, 0), "spread": 0},
    "relaxed": {
        "curl": (12, 18, 10),
        "thumb": (5, 10, 5),
        "spread": 2,
        "per_finger_extra": {"index": -4, "middle": 0, "ring": 4, "pinky": 8},
    },
    "grip_edge": {"curl": (20, 55, 40), "thumb": (10, 20, 10), "spread": 0},
    "brace_flat": {"curl": (-5, 5, 5), "thumb": (0, 5, 0), "spread": 6},
    "fist": {"curl": (75, 95, 65), "thumb": (35, 30, 25), "spread": -3},
    "point": {"curl": (75, 95, 65), "thumb": (35, 30, 25), "spread": 0, "index": (0, 0, 0)},
}


def _load_actions() -> dict:
    return json.loads((pt.DATA_DIR / "cascadeur_actions.json").read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------
# Actions
# ----------------------------------------------------------------------------


@mcp.tool()
def list_actions(contains: str | None = None) -> dict:
    """Cascadeur's menu and toolbar actions (about 220), optionally filtered by substring.

    The catalogue was extracted from the 2026.2.3 install. Highlights: AutoPhysics
    (switch, snap, frozen physics, priority frame), FixFoot (Fulcrum Motion
    Cleaning), Inbetweening (``View.Inbetweening_Run``, motion generation), IK/FK
    and fulcrum keys on the timeline, cycles, ballistic trajectories, mirror,
    collision shapes, ghosts, hide/show selected, video/image binding.
    """
    data = _load_actions()
    actions = data["actions"]
    if contains:
        actions = [a for a in actions if contains.lower() in a.lower()]
    return {
        "count": len(actions),
        "actions": actions,
        "verified_live": data["verified_live"],
        "note": data["source"],
    }


@mcp.tool()
def run_action(
    action_id: str,
    select: list[str] | None = None,
    frames: list[int] | None = None,
    dialog_answers: dict[str, str] | None = None,
    wait_sec: float = 2.0,
) -> dict:
    """Run any Cascadeur action, optionally on a selection and at given frames.

    ``select`` replaces the selection first (actions act on the selection).
    ``frames`` runs the action once per frame with the playhead there (for
    per-frame actions such as ``Timeline.Change to IK key``).
    ``dialog_answers`` maps a dialog title to the button to press if that dialog
    opens (e.g. ``{"Apply AutoPhysics": "Only keys"}``). The reply lists dialogs
    still open and the Cascadeur log lines the action produced, which is how you
    tell whether an unverified action ID did anything.
    """
    offset = pt._log_offset()
    if select is not None:
        pt._scall("selection_set", object_names=select)
    runs = 0
    for frame in frames or [None]:
        if frame is not None:
            pt._scall("viewport_set", frame=int(frame))
        pt._scall("call_action", action_id=action_id)
        runs += 1
        deadline = time.monotonic() + wait_sec
        while dialog_answers and time.monotonic() < deadline:
            open_now = pt._scall("dialogs_list")["dialogs"]
            pressed = False
            for d in open_now:
                if d["title"] in dialog_answers:
                    pt._scall("dialog_answer", title=d["title"], button=dialog_answers[d["title"]])
                    pressed = True
            if pressed:
                break
            time.sleep(0.25)
    time.sleep(min(wait_sec, 1.0))
    raw = pt._log_since(offset)
    # Cascadeur logs "Action manager does not contain id: <id>" for unknown IDs;
    # call_action itself raises nothing.
    unknown = any(f"does not contain id: {action_id}" in line for line in raw)
    lines = [
        line
        for line in raw
        if line.strip()
        and "cascadeur-mcp" not in line
        and "Cascadeur MCP" not in line
        and "Backtrace" not in line
        and not line.strip().split("#")[0].isdigit()
    ]
    return {
        "action": action_id,
        "exists": not unknown,
        "runs": runs,
        "log": lines[-25:],
        "open_dialogs": pt._scall("dialogs_list")["dialogs"],
        "known_good": action_id in _load_actions()["verified_live"],
    }


# ----------------------------------------------------------------------------
# Per-point physics and IK
# ----------------------------------------------------------------------------


@mcp.tool()
def get_point_physics(
    points: list[str], frame: int = 0, behaviours: list[str] | None = None
) -> dict:
    """Physics and IK properties of controller points (hands, feet, balls) at ``frame``.

    Default behaviours: FulcrumPoint, Fixation, ToolFixation, FulcrumGroup,
    AutoPhysicsApply, SecondaryMotion, CompensationMotion, Ragdoll,
    CollisionPenetrationCleaning, SeparationOfMotion, AngleConstraints, and on the
    ``Center of mass`` object, AutoPhysics and CenterOfMass. Each value says whether
    it is a ``setting`` (one value) or ``data`` (animated per frame).
    """
    params: dict[str, Any] = {"object_names": points, "frame": frame}
    if behaviours:
        params["behaviours"] = behaviours
    return pt._scall("behaviours_get", **params)


@mcp.tool()
def set_point_physics(
    points: list[str],
    behaviour: str,
    property: str,
    value: Any,
    frames: list[int] | None = None,
    key_boundaries: bool = True,
) -> dict:
    """Set one physics/IK property on controller points.

    Examples: ``("FulcrumPoint", "collision_radius", 3.0)``,
    ``("Fixation", "fixed", True)`` to pin a point, ``("AutoPhysicsApply",
    "keep_global_translation", 1.0, frames=[12..16])`` so AutoPhysics leaves a
    planted hand where it is, ``("SecondaryMotion", "damping", 20)``.
    Animated (data) properties apply to ``frames`` (default: every frame). They only
    change at keys, so with ``key_boundaries`` the first frame and the frame after
    each run of frames get keys first, keeping the pose.
    """
    if frames and key_boundaries:
        fs = sorted(set(int(f) for f in frames))
        edges = {fs[0]}
        for a, b in zip(fs, fs[1:]):
            if b != a + 1:
                edges.update({a + 1, b})
        edges.add(fs[-1] + 1)
        pt._scall("keys_add", frames=sorted(edges))
    params: dict[str, Any] = {
        "object_names": points,
        "behaviour": behaviour,
        "property": property,
        "value": value,
    }
    if frames is not None:
        params["frames"] = [int(f) for f in frames]
    return pt._scall("behaviour_set", **params)


def _span_frames(spans: list[list[int]]) -> list[int]:
    return sorted({f for a, b in spans for f in range(int(a), int(b) + 1)})


@mcp.tool()
def setup_contacts(
    contacts: dict[str, list[list[int]]],
    keep_translation: float = 1.0,
    keep_rotation: float | None = None,
    collision_radius: float | None = None,
    max_speed: float | None = None,
) -> dict:
    """Set up hand and foot contacts for AutoPhysics in one call.

    For each point and its frame spans: fulcrum on during the spans (off
    elsewhere), AutoPhysicsApply ``keep_global_translation`` = ``keep_translation``
    during the spans (0 elsewhere) so the solver keeps the contact where you placed
    it, optional ``keep_rotation`` (feet flat on the floor, palms flat on a box),
    and optional fulcrum ``collision_radius``/``max_speed`` (how far and how fast
    the contact may slide). Span edges are keyed first.

    Typical feet: ``{"foot_MainPoint_l": [[0, 11]], "ball_MainPoint_l": [[0, 11]]}``
    (heel and toe together). Hands on a vault box: ``{"hand_MainPoint_l": [[25, 29]]}``.
    """
    report: dict[str, Any] = {"fulcrums": pt.set_fulcrum_spans(contacts)}
    all_frames = None
    for point, spans in contacts.items():
        on = _span_frames(spans)
        if all_frames is None:
            all_frames = pt._scall("scene_timing")["frames"]
        off = [f for f in range(all_frames) if f not in set(on)]
        pt._scall(
            "behaviour_set",
            object_names=[point],
            behaviour="AutoPhysicsApply",
            property="keep_global_translation",
            value=keep_translation,
            frames=on,
        )
        if off:
            pt._scall(
                "behaviour_set",
                object_names=[point],
                behaviour="AutoPhysicsApply",
                property="keep_global_translation",
                value=0.0,
                frames=off,
            )
        if keep_rotation is not None:
            pt._scall(
                "behaviour_set",
                object_names=[point],
                behaviour="AutoPhysicsApply",
                property="keep_global_rotation",
                value=keep_rotation,
                frames=on,
            )
        for prop, val in (("collision_radius", collision_radius), ("max_speed", max_speed)):
            if val is not None:
                pt._scall(
                    "behaviour_set",
                    object_names=[point],
                    behaviour="FulcrumPoint",
                    property=prop,
                    value=val,
                    frames=on,
                )
    report["readback"] = {
        p: pt._scall(
            "behaviours_get",
            object_names=[p],
            behaviours=["AutoPhysicsApply", "FulcrumPoint"],
            frame=_span_frames(s)[0],
        )["objects"][p]
        for p, s in contacts.items()
    }
    return report


@mcp.tool()
def set_autophysics_frames(
    frames: list[int],
    frame_weight: float | None = None,
    rotation_blending: float | None = None,
    vertical_jerk: float | None = None,
    horizontal_jerk: float | None = None,
    priority_frame: bool | None = None,
) -> dict:
    """Per-frame AutoPhysics weights on the rig's Center of mass.

    ``priority_frame`` keeps the pose on that frame (Cascadeur's "Set physics
    priority frame"), ``frame_weight`` raises how strongly the solver respects
    the keyed pose there, ``vertical_jerk``/``horizontal_jerk`` limit sudden
    changes of the centre of mass, ``rotation_blending`` blends physics rotation.
    """
    changes = {
        "frame_weight": frame_weight,
        "rotation_blending": rotation_blending,
        "vertical_jerk": vertical_jerk,
        "horizontal_jerk": horizontal_jerk,
        "priority_frame": priority_frame,
    }
    out = {}
    for prop, val in changes.items():
        if val is not None:
            out[prop] = set_point_physics(
                ["Center of mass"], "AutoPhysics", prop, val, frames=frames
            )["readback"]
    return out


# ----------------------------------------------------------------------------
# Fingers
# ----------------------------------------------------------------------------


def finger_keys(
    side: str,
    preset: str | None = None,
    curl: list[float] | None = None,
    thumb: list[float] | None = None,
    spread: float | None = None,
    per_finger: dict[str, list[float]] | None = None,
) -> dict[str, list[float]]:
    """Local-rotation degrees per finger box controller. Pure function for tests."""
    if side not in ("l", "r"):
        raise ValueError("side must be 'l' or 'r'")
    if preset and preset not in FINGER_PRESETS:
        raise ValueError(f"unknown preset {preset!r}; options: {sorted(FINGER_PRESETS)}")
    base = dict(FINGER_PRESETS[preset]) if preset else {}
    curl = list(curl or base.get("curl", (0, 0, 0)))
    thumb = list(thumb or base.get("thumb", (0, 0, 0)))
    spread = spread if spread is not None else base.get("spread", 0)
    extra = base.get("per_finger_extra", {})
    order = {"index": -1.5, "middle": -0.5, "ring": 0.5, "pinky": 1.5}
    out: dict[str, list[float]] = {}
    for finger in FINGERS:
        segs = (
            list(per_finger.get(finger))
            if per_finger and finger in per_finger
            else list(base.get(finger, curl))
        )
        for i, seg in enumerate(("01", "02", "03")):
            y = spread * order[finger] if seg == "01" else 0.0
            out[f"{finger}_{seg}_Box_{side}"] = [
                0.0,
                float(y),
                float(segs[i] + extra.get(finger, 0)),
            ]
    tseg = list(per_finger.get("thumb")) if per_finger and "thumb" in per_finger else thumb
    for i, seg in enumerate(("01", "02", "03")):
        out[f"thumb_{seg}_Box_{side}"] = [0.0, 0.0, float(tseg[i])]
    return out


@mcp.tool()
def pose_fingers(
    side: str,
    frames: list[int],
    preset: str | None = None,
    curl: list[float] | None = None,
    thumb: list[float] | None = None,
    spread: float | None = None,
    per_finger: dict[str, list[float]] | None = None,
    rest_file: str | None = "ue5_quinn",
    base_frame: int = 0,
) -> dict:
    """Key a hand shape on ``side`` (``"l"``/``"r"``) at ``frames``.

    Presets: ``flat``, ``relaxed``, ``grip_edge`` (wrapping a vault box edge),
    ``brace_flat`` (palm pushing on a surface), ``fist``, ``point``. Or give
    ``curl`` = degrees for the three segments of every finger, ``thumb`` = degrees
    for the thumb's three segments, ``spread`` = degrees between neighbouring
    fingers, and ``per_finger`` = {"index": [a, b, c], ...} overrides.

    Angles are absolute from the open rest hand: ``rest_file`` names a captured
    finger rest pose (``"ue5_quinn"`` ships; capture another rig with
    ``capture_finger_rest``). With ``rest_file=None`` they are applied on top of
    the hand at ``base_frame``. Local Z flexes, local Y spreads.
    """
    keys = finger_keys(side, preset, curl, thumb, spread, per_finger)
    params: dict[str, Any] = {"keys": {str(int(f)): keys for f in frames}, "base_frame": base_frame}
    if rest_file:
        path = pt.DATA_DIR / f"{rest_file}_fingers_rest.json"
        data = json.loads((path if path.exists() else Path(rest_file)).read_text(encoding="utf-8"))
        params["base_quaternions"] = {n: q for n, q in data["quaternions"].items() if n in keys}
    result = pt._scall("local_rotation_keys_set", **params)
    result["controllers"] = len(keys)
    return result


@mcp.tool()
def capture_finger_rest(save_to: str, frame: int = 0) -> dict:
    """Save every finger controller's local rotation at ``frame`` as a rest pose for
    pose_fingers. Run it on a freshly loaded, unanimated rig."""
    names = [
        f"{f}_{s}_Box_{side}"
        for side in "lr"
        for f in ("thumb", *FINGERS)
        for s in ("01", "02", "03")
    ]
    q = pt._scall("local_rotations_get", object_names=names, frame=frame)["quaternions"]
    Path(save_to).write_text(json.dumps({"quaternions": q}, indent=1), encoding="utf-8")
    return {"saved_to": save_to, "controllers": len(q)}


# ----------------------------------------------------------------------------
# AutoPhysics modes and scene tool settings
# ----------------------------------------------------------------------------


@mcp.tool()
def get_physics_settings(panel: str = "physics") -> dict:
    """Read Cascadeur's settings panels for this scene.

    ``panel="physics"``: Gravity, Ragdoll, the AutoPhysics modes (Physics corrector,
    Smooth trajectory, Smooth rotation, Compensation motion, Separation of motion,
    Secondary motion, Penetration cleaning, each with its alpha) and every
    sub-setting (ballistics, surface friction, pin forces, jerk weights).
    ``panel="scene"``: FPS, Fulcrum Motion Cleaning, Inbetweening, Interval edit
    mode, Motion Generation, Mirror, Trajectory, Collision cleaning and more.
    """
    return pt._scall("settings_panel_get", panel=panel)


@mcp.tool()
def set_physics_setting(
    label: str, value: Any, group: str | None = None, panel: str = "physics"
) -> dict:
    """Change one row of the physics or scene settings panel for this scene.

    ``label`` and optional ``group`` are as listed by get_physics_settings, e.g.
    ``("Secondary motion", False, "AutoPhysics")``, ``("Secondary alpha", 30)``,
    ``("Friction coefficient", 12, "Physics corrector surface")``,
    ``("Mode", "Selected", "Interval edit mode", panel="scene")``.
    The value goes through the panel's own control, so Cascadeur applies it exactly
    as a click would; ``before``/``after`` show the change.
    """
    params: dict[str, Any] = {"panel": panel, "label": label, "value": value}
    if group:
        params["group"] = group
    return pt._scall("settings_panel_set", **params)
