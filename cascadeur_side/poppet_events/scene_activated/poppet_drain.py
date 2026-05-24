"""Auto-drain Poppet's request queue on scene_activated.

Cascadeur fires the `scene_activated` event when a scene tab gains focus —
including when the Cascadeur window itself is re-focused while a scene is
open. We hook that event as a heartbeat for the Poppet file-sync protocol
so callers don't have to manually click Commands -> Poppet -> Process
Pending every time.

Caveats:
  - The event fires on focus changes, NOT on a wall-clock tick. If the
    Cascadeur window is already focused and idle, no drain happens. The
    MCP server's _nudge module pokes the window to force a focus event.
  - We catch every exception inside the drain so a bad request never
    wedges the focus machinery.

Registration: events_rule.py walks
  poppet_events/scene_activated/<module>.run(scene)
on startup once `poppet_events` is listed in settings.json `Python.Events`.

Install: scripts/install.ps1 copies cascadeur_side/poppet_events/ into
%LOCALAPPDATA%/Nekki Limited/Cascadeur/user_scripts/poppet_events/ and
appends "poppet_events" to Python.Events.
"""

import csc  # noqa: F401  (Cascadeur convention — every event/command module imports csc top-level)


def run(scene: "csc.domain.Scene") -> None:
    try:
        from poppet import process_pending
    except Exception as e:
        print("[poppet-events] could not import process_pending:", e)
        return

    try:
        process_pending.run(scene)
    except Exception as e:
        print("[poppet-events] scene_activated drain failed:", e)
