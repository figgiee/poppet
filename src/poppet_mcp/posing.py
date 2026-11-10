"""Pose solver for Cascadeur point-controller rigs.

Turns a compact pose spec (pelvis position, a few rotations, hand and foot targets)
into a world position for every body controller point, keeping every segment length
exactly as in the rig's rest pose. The result is what ``set_pose_keys`` writes.

Conventions match Cascadeur's viewport: Y up, the character faces +Z in its rest
pose, the character's left side is +X, units are centimetres.

Rigs: Cascadeur's stock rig names (``chest_``, ``forearm_``, ``toe_``) are used
internally. UE5 rigs (Quinn, Manny, MetaHuman bodies rigged with Cascadeur's UE
template) name the same points ``spine_04_``, ``lowerarm_``, ``ball_`` and so on;
``naming="ue"`` maps between the two.

Pose spec keys (all optional except ``pelvis``, ``hand_l/r``, ``foot_l/r``):

- ``pelvis``: [x, y, z] world position of the pelvis main point.
- ``pelvis_rot``, ``stomach_rot``, ``chest_rot``, ``neck_rot``, ``head_rot``:
  [yaw, pitch, roll] in degrees, each relative to its parent.
  Yaw turns to the character's left, positive pitch leans forward.
- ``head_world``: [yaw, pitch, roll] absolute head rotation (overrides the chain).
- ``clav_l/r``: clavicle rotation relative to the chest.
- ``hand_l/r``, ``foot_l/r``: world positions of wrist and ankle.
- ``elbow_l/r``, ``knee_l/r``: pole vectors for the elbow and knee direction.
- ``hand_rot_l/r`` (relative to forearm) or ``hand_world_l/r`` (absolute).
- ``foot_rot_l/r``: absolute foot rotation. ``toe_l/r``: toe bend in degrees.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# internal (Cascadeur stock) prefix -> UE prefix
UE_NAMES = [
    ("forearm_", "lowerarm_"),
    ("arm_MainPoint", "upperarm_MainPoint"),
    ("stomach_", "spine_02_"),
    ("chest_", "spine_04_"),
    ("neck_", "neck_01_"),
    ("toe_", "ball_"),
]

POINT_TYPES = ("Point", "Limb Direction")


def _rx(d: float) -> np.ndarray:
    a = math.radians(d)
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(d: float) -> np.ndarray:
    a = math.radians(d)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rz(d: float) -> np.ndarray:
    a = math.radians(d)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def euler(ypr) -> np.ndarray:
    y, p, r = (list(ypr) + [0, 0, 0])[:3]
    return _ry(y) @ _rx(p) @ _rz(r)


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def _frame(axis: np.ndarray, pole: np.ndarray) -> np.ndarray:
    a = _unit(axis)
    p = pole - np.dot(pole, a) * a
    if np.linalg.norm(p) < 1e-6:
        p = np.cross(a, [1, 0, 0])
    p = _unit(p)
    return np.column_stack([a, p, np.cross(a, p)])


def _two_bone(root, target, l1, l2, pole):
    d = target - root
    dist = float(np.linalg.norm(d))
    dist = min(max(dist, abs(l1 - l2) + 0.5), l1 + l2 - 0.2)
    dn = _unit(d)
    target = root + dn * dist
    a = (l1 * l1 - l2 * l2 + dist * dist) / (2 * dist)
    h = math.sqrt(max(l1 * l1 - a * a, 0.0))
    p = pole - np.dot(pole, dn) * dn
    if np.linalg.norm(p) < 1e-6:
        p = np.array([0, 0, 1.0])
    p = _unit(p)
    return root + dn * a + p * h, target, p


def detect_naming(rest: dict[str, Any]) -> str:
    """Return ``"ue"`` when the rig uses UE5 point names, else ``"cascadeur"``."""
    return "ue" if "lowerarm_MainPoint_l" in rest or "spine_04_MainPoint" in rest else "cascadeur"


class Rig:
    """A rig's rest pose, from ``rig_rest_dump`` (``{name: [type, x, y, z]}``)."""

    def __init__(self, rest: dict[str, list], naming: str | None = None):
        self.naming = naming or detect_naming(rest)
        self.r0 = {
            self.from_rig(n): np.array(v[1:4], dtype=float)
            for n, v in rest.items()
            if v and v[0] in POINT_TYPES
        }
        missing = [n for n in REQUIRED if n not in self.r0]
        if missing:
            raise ValueError(
                "rig is missing controller points the solver needs: "
                + ", ".join(self.to_rig(n) for n in missing)
            )

    def to_rig(self, name: str) -> str:
        if self.naming != "ue":
            return name
        for a, b in UE_NAMES:
            if name.startswith(a):
                return b + name[len(a) :]
        return name

    def from_rig(self, name: str) -> str:
        if self.naming != "ue":
            return name
        for a, b in UE_NAMES:
            if name.startswith(b):
                return a + name[len(b) :]
        return name

    @property
    def ankle_height(self) -> float:
        return float(self.r0["foot_MainPoint_l"][1])

    @property
    def hip_height(self) -> float:
        return float(self.r0["pelvis_MainPoint"][1])

    def rest_pose(self) -> dict:
        r = self.r0
        return {
            "pelvis": r["pelvis_MainPoint"].tolist(),
            "hand_l": r["hand_MainPoint_l"].tolist(),
            "hand_r": r["hand_MainPoint_r"].tolist(),
            "foot_l": r["foot_MainPoint_l"].tolist(),
            "foot_r": r["foot_MainPoint_r"].tolist(),
        }

    def solve(self, pose: dict) -> dict[str, list[float]]:
        """Return ``{rig_point_name: [x, y, z]}`` for every body controller point."""
        r0 = self.r0
        out: dict[str, np.ndarray] = {}

        def place(names, pivot0, pivot, rot):
            for n in names:
                if n in r0:
                    out[n] = pivot + rot @ (r0[n] - pivot0)

        rp = euler(pose.get("pelvis_rot", [0, 0, 0]))
        pel = np.array(pose["pelvis"], dtype=float)
        place(
            [
                "pelvis_MainPoint",
                "pelvis_AdditionalPoint",
                "thigh_MainPoint_l",
                "thigh_MainPoint_r",
                "stomach_MainPoint",
            ],
            r0["pelvis_MainPoint"],
            pel,
            rp,
        )
        rs = rp @ euler(pose.get("stomach_rot", [0, 0, 0]))
        place(
            ["stomach_AdditionalPoint", "chest_MainPoint"],
            r0["stomach_MainPoint"],
            out["stomach_MainPoint"],
            rs,
        )
        rc = rs @ euler(pose.get("chest_rot", [0, 0, 0]))
        place(
            [
                "chest_AdditionalPoint",
                "clavicle_MainPoint_l",
                "clavicle_MainPoint_r",
                "neck_MainPoint",
            ],
            r0["chest_MainPoint"],
            out["chest_MainPoint"],
            rc,
        )
        rn = rc @ euler(pose.get("neck_rot", [0, 0, 0]))
        place(
            ["neck_AdditionalPoint", "head_MainPoint"],
            r0["neck_MainPoint"],
            out["neck_MainPoint"],
            rn,
        )
        rh = rn @ euler(pose.get("head_rot", [0, 0, 0]))
        if "head_world" in pose:
            rh = euler(pose["head_world"])
        place(
            ["head_AdditionalPoint", "head_DirectionPoint"],
            r0["head_MainPoint"],
            out["head_MainPoint"],
            rh,
        )

        for s in ("l", "r"):
            rcl = rc @ euler(pose.get("clav_" + s, [0, 0, 0]))
            cm = "clavicle_MainPoint_" + s
            place(["clavicle_AdditionalPoint_" + s, "arm_MainPoint_" + s], r0[cm], out[cm], rcl)
            sh = out["arm_MainPoint_" + s]
            e0, w0, s0 = (
                r0["forearm_MainPoint_" + s],
                r0["hand_MainPoint_" + s],
                r0["arm_MainPoint_" + s],
            )
            pole0 = r0["forearm_LimbDir_" + s] - e0
            l1, l2 = np.linalg.norm(e0 - s0), np.linalg.norm(w0 - e0)
            # default: keep the rest-pose elbow direction, carried by the chest
            pole = np.array(pose.get("elbow_" + s, rc @ _unit(pole0)), dtype=float)
            el, wr, pd = _two_bone(sh, np.array(pose["hand_" + s], dtype=float), l1, l2, pole)
            rua = _frame(el - sh, pd) @ _frame(e0 - s0, pole0).T
            place(["forearm_AdditionalPoint_" + s], s0, sh, rua)
            out["forearm_MainPoint_" + s] = el
            out["hand_MainPoint_" + s] = wr
            out["forearm_LimbDir_" + s] = el + pd * np.linalg.norm(pole0)
            rfa = _frame(wr - el, pd) @ _frame(w0 - e0, pole0).T
            rhand = rfa @ euler(pose.get("hand_rot_" + s, [0, 0, 0]))
            if ("hand_world_" + s) in pose:
                rhand = euler(pose["hand_world_" + s])
            place(["hand_AdditionalPoint_" + s, "hand_DirectionPoint_" + s], w0, wr, rhand)

            hip = out["thigh_MainPoint_" + s]
            h0, k0, a0 = (
                r0["thigh_MainPoint_" + s],
                r0["calf_MainPoint_" + s],
                r0["foot_MainPoint_" + s],
            )
            kp0 = r0["calf_LimbDir_" + s] - k0
            l1, l2 = np.linalg.norm(k0 - h0), np.linalg.norm(a0 - k0)
            # default: keep the rest-pose knee direction, carried by the pelvis
            pole = np.array(pose.get("knee_" + s, rp @ _unit(kp0)), dtype=float)
            kn, an, pd = _two_bone(hip, np.array(pose["foot_" + s], dtype=float), l1, l2, pole)
            rth = _frame(kn - hip, pd) @ _frame(k0 - h0, kp0).T
            place(["calf_AdditionalPoint_" + s], h0, hip, rth)
            out["calf_MainPoint_" + s] = kn
            out["foot_MainPoint_" + s] = an
            out["calf_LimbDir_" + s] = kn + pd * np.linalg.norm(kp0)
            rf = euler(pose.get("foot_rot_" + s, [0, 0, 0]))
            place(
                ["foot_Self0Point_" + s, "toe_MainPoint_" + s, "toe_AdditionalPoint_" + s],
                a0,
                an,
                rf,
            )
            if "toe_MainPoint_" + s in out:
                rt = rf @ _rx(-pose.get("toe_" + s, 0))
                place(
                    ["toe_DirectionPoint_" + s],
                    r0["toe_MainPoint_" + s],
                    out["toe_MainPoint_" + s],
                    rt,
                )

        return {self.to_rig(k): [round(float(x), 4) for x in v] for k, v in out.items()}


REQUIRED = [
    "pelvis_MainPoint",
    "stomach_MainPoint",
    "chest_MainPoint",
    "neck_MainPoint",
    "head_MainPoint",
    *(
        f"{p}_{s}"
        for s in ("l", "r")
        for p in (
            "clavicle_MainPoint",
            "arm_MainPoint",
            "forearm_MainPoint",
            "forearm_LimbDir",
            "hand_MainPoint",
            "thigh_MainPoint",
            "calf_MainPoint",
            "calf_LimbDir",
            "foot_MainPoint",
        )
    ),
]
