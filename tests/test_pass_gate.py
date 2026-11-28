"""Offline tests for the pass ledger, the export gate and take_audit's checks."""

from __future__ import annotations

import time

import pytest

from poppet_mcp import pass_ledger
from poppet_mcp.pass_tools import blade_points, floor_hits, held_jumps, planted_slides, rotate

pytestmark = pytest.mark.ledger


def test_export_refused_until_every_step_is_newer_than_the_last_edit():
    pass_ledger.mark("take.casc", "edited", "pose_keys_set")
    with pytest.raises(RuntimeError, match="contacts.*physics.*audit"):
        pass_ledger.gate("take.casc", None)
    time.sleep(0.01)
    pass_ledger.mark("take.casc", "contacts", {"points": ["foot_MainPoint_l"]})
    pass_ledger.mark("take.casc", "physics", {"complete": True})
    pass_ledger.mark("take.casc", "audit", {"passed": True})
    assert pass_ledger.gate("take.casc", None) == {"pass_gate": "passed"}
    time.sleep(0.01)
    pass_ledger.mark("take.casc", "edited", "retime")
    assert set(pass_ledger.status("take.casc")["missing"]) == {"contacts", "physics", "audit"}


def test_incomplete_physics_and_failed_audit_do_not_count():
    pass_ledger.mark("t.casc", "contacts", {})
    pass_ledger.mark("t.casc", "physics", {"complete": False})
    pass_ledger.mark("t.casc", "audit", {"passed": False})
    missing = pass_ledger.status("t.casc")["missing"]
    assert set(missing) == {"physics", "audit"}


def test_override_is_reported_back():
    out = pass_ledger.gate("never.casc", "pose library, no motion")
    assert out["pass_gate"] == "overridden"
    assert out["reason"] == "pose library, no motion"
    assert set(out["skipped"]) == {"contacts", "physics", "audit"}


def test_rotate_and_blade_tip():
    # 90 degrees about X turns -Y into -Z
    q = [2**-0.5, 0.0, 0.0, 2**-0.5]
    assert rotate(q, [0, -1, 0]) == pytest.approx([0, 0, -1])
    tip = blade_points([0, 100, 0], [0, 0, 0, 1], [0, -1, 0], 170)[-1]
    assert tip == pytest.approx([0, -70, 0])


def test_floor_runs_report_depth():
    heights = {0: 5.0, 1: -0.5, 2: -3.0, 3: -4.0, 4: 2.0, 5: -2.0}
    assert floor_hits(heights, 0.0, 1.0) == [[2, 3, 4.0], [5, 5, 2.0]]


def test_planted_foot_that_skates_is_found():
    track = {f: [0.0, 8.0, 0.0] for f in range(10)}
    for f in range(10):
        track[f] = [0.0, 8.0, 0.5 * f]  # creeps 0.5 cm a frame while low
    slides = planted_slides(track, 3.0, 1.0, 2.0)
    assert slides and slides[0]["slide_cm"] == pytest.approx(4.5)
    still = {f: [0.0, 8.0, 0.0] for f in range(10)}
    assert planted_slides(still, 3.0, 1.0, 2.0) == []


def test_held_jumps_ignore_adjacent_steps():
    full = {
        "layers": [
            {
                "name": "Arm_R",
                "key_frames": [0, 1, 5, 6],
                "interpolation": {
                    "0": "STEP",
                    "1": "Interpolation.STEP",
                    "5": "BEZIER",
                    "6": "STEP",
                },
            }
        ]
    }
    assert held_jumps(full) == [{"layer": "Arm_R", "from": 1, "to": 5}]


def test_audit_must_be_newer_than_the_physics_pass():
    pass_ledger.mark("a.casc", "contacts", {})
    pass_ledger.mark("a.casc", "audit", {"passed": True})
    time.sleep(0.01)
    pass_ledger.mark("a.casc", "physics", {"complete": True})
    assert set(pass_ledger.status("a.casc")["missing"]) == {"audit"}
