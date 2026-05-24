"""Auto-drain Poppet's request queue on scene_opened.

Same handler as scene_activated, just routed off scene_opened for broader
coverage. Cascadeur fires scene_opened when a .casc file finishes loading
into the application — this lets queued requests run immediately after
load_scene completes (handy for the load -> tweak -> save workflow).
"""

import csc  # noqa: F401


def run(scene: "csc.domain.Scene") -> None:
    try:
        from poppet import process_pending
    except Exception as e:
        print("[poppet-events] could not import process_pending:", e)
        return

    try:
        process_pending.run(scene)
    except Exception as e:
        print("[poppet-events] scene_opened drain failed:", e)
