"""Which parts of a full Cascadeur pass have run on each scene since its animation last changed.

A take is not done when its keys look right in one view. Brandon's standing rule is that
every take and every edit of a library clip goes through contacts, AutoPhysics with
collision cleaning, and a floor and weapon check before it leaves Cascadeur. This ledger
records those steps per scene, and the export tools refuse to run until they are newer
than the last edit (or the caller states why one is skipped, which the reply repeats).

The ledger is a small JSON file so it survives MCP server restarts:
``%LOCALAPPDATA%\\poppet\\pass-ledger.json`` (override with ``POPPET_LEDGER``).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# Commands that change a take's animation. exec_csc counts because it can do anything;
# tools that run in-app code only to read or export pass ``_ledger_edit=False``, and so does
# physics_pass (it is the step being recorded; take_audit must then be newer than it).
EDIT_COMMANDS = frozenset(
    {
        "autopose_run",
        "bake_range",
        "behaviour_set",
        "call_action",
        "controller_scale_set",
        "exec_csc",
        "fbx_import",
        "fulcrum_spans_set",
        "glb_import",
        "interpolation_set",
        "keyframe_add",
        "keyframe_remove",
        "keyframe_set",
        "keys_add",
        "layer_add",
        "layer_delete",
        "local_rotation_keys_set",
        "object_delete",
        "object_duplicate",
        "pose_keys_set",
        "redo",
        "undo",
    }
)

REQUIRED = {
    "contacts": "setup_contacts (pin planted feet and loaded hands with fulcrums)",
    "physics": "physics_pass with autophysics_on, autophysics_snap and collision_cleaning",
    "audit": "take_audit (floor penetration of feet, hands and the weapon, sliding contacts, "
    "hold-then-jump keys, unkeyed last frame)",
}


def enabled() -> bool:
    return os.environ.get("POPPET_LEDGER", "").lower() not in ("off", "0", "false")


def _path() -> Path:
    env = os.environ.get("POPPET_LEDGER")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "poppet" / "pass-ledger.json"


def _load() -> dict[str, Any]:
    try:
        return json.loads(_path().read_text())
    except Exception:
        return {}


def _save(data: dict[str, Any]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1))


def mark(scene: str | None, step: str, detail: Any = None) -> None:
    """Record ``step`` (``edited``, ``contacts``, ``physics``, ``audit``) for ``scene`` now."""
    if not scene or not enabled():
        return
    data = _load()
    entry = data.setdefault(scene, {})
    entry[step] = {"at": time.time(), "detail": detail}
    _save(data)


def status(scene: str | None) -> dict[str, Any]:
    """What is missing for ``scene``: each required step must be newer than the last edit."""
    entry = _load().get(scene or "", {})
    edited = entry.get("edited", {}).get("at", 0.0)
    missing = {}
    for step, why in REQUIRED.items():
        rec = entry.get(step)
        if not rec:
            missing[step] = f"never run: {why}"
        elif rec["at"] < edited:
            missing[step] = f"older than the last edit: run {why} again"
        elif step == "audit" and rec["at"] < entry.get("physics", {}).get("at", 0.0):
            missing[step] = "older than the physics pass: run take_audit on the result"
        elif step == "audit" and not (rec.get("detail") or {}).get("passed"):
            missing[step] = "the last take_audit found problems; fix them and run it again"
        elif step == "physics" and not (rec.get("detail") or {}).get("complete"):
            missing[step] = f"incomplete: {why}"
    return {"scene": scene, "missing": missing, "ready": not missing, "steps": entry}


def gate(scene: str | None, skip_reason: str | None) -> dict[str, Any]:
    """Raise unless the full pass is current, or return the override record."""
    if not enabled():
        return {"pass_gate": "ledger off (POPPET_LEDGER=off)"}
    st = status(scene)
    if st["ready"]:
        return {"pass_gate": "passed"}
    if skip_reason and skip_reason.strip():
        return {
            "pass_gate": "overridden",
            "skipped": st["missing"],
            "reason": skip_reason.strip(),
            "tell_the_user": "This export skipped part of the required Cascadeur pass. "
            "Say which steps and why when you report it.",
        }
    lines = "; ".join(f"{k}: {v}" for k, v in st["missing"].items())
    raise RuntimeError(
        f"Export refused for {scene!r}: the full Cascadeur pass is not current ({lines}). "
        "A take is done only after contacts, AutoPhysics with collision cleaning, and "
        "take_audit, all after the last edit. If a step truly does not apply, pass "
        "skip_pass_reason and tell the user what was skipped."
    )
