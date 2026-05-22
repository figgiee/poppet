"""Cascadeur command: Poppet → Start Server.

Toggle the singleton Poppet listener. Re-running the command stops it.

The listener uses a non-blocking socket + QTimer driven against Cascadeur's
embedded PySide event loop — so the Cascadeur UI stays responsive even with
the server running.
"""

import configparser
import os

from ._listener import PoppetListener


def command_name():
    return "Poppet.Start Server"


def run(scene):
    if PoppetListener.is_running():
        PoppetListener.instance().stop()
        print("[poppet] server stopped (re-run command to start)")
        return

    host, port, tick_ms = _load_settings()

    # scene_provider lets each request grab the current scene at dispatch time,
    # not the scene that was active when run() was first invoked.
    import csc

    def scene_provider():
        try:
            return csc.app.get_application().current_scene()
        except Exception:
            return scene

    listener = PoppetListener(host=host, port=port, tick_ms=tick_ms, scene_provider=scene_provider)
    listener.start()
    print("[poppet] server started — re-run command to stop")


def _load_settings():
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.cfg")
    cfg = configparser.ConfigParser()
    cfg.read(cfg_path)
    host = cfg.get("server", "host", fallback="127.0.0.1")
    port = cfg.getint("server", "port", fallback=53145)
    tick_ms = cfg.getint("server", "tick_ms", fallback=50)
    return host, port, tick_ms
