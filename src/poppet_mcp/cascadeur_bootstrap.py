"""cascadeur-mcp's Cascadeur-side bootstrap — run once per Cascadeur 2026.2 session.

Cascadeur 2026.2's embedded interpreter keeps the GIL in its Qt idle loop, so the
built-in MCP script server's background HTTP thread starves whenever Cascadeur is
sitting idle. This bootstrap fixes that from inside Cascadeur, without installing
anything:

1. starts (or restarts) Cascadeur's built-in script server on a free port,
2. installs a 10 ms PySide ``QTimer`` that keeps the interpreter ticking and
   drives ``scene_idle`` events, which both unblocks the server thread and lets
   queued ``run_script`` calls execute,
3. records the chosen port in ``%LOCALAPPDATA%\\cascadeur-mcp\\server.json`` so the
   ``cascadeur-mcp`` client can find it without configuration.

Usage — in Cascadeur: **Window → Python Console**, paste and Execute::

    exec(open(r"C:\\path\\to\\cascadeur_bootstrap.py").read())

``cascadeur-bootstrap`` writes this file for you and prints the exact line.

The script is executed *inside* Cascadeur: it must only import Cascadeur's own
modules (``csc``, ``scripts.*``, ``events``, ``PySide6``) and the standard library.
It is never imported by the MCP server process.
"""

import json
import os
import time
import traceback

DEFAULT_PORT = 8765
PORT_CANDIDATES = 10
STATE_DIR_NAME = "cascadeur-mcp"


def _state_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, STATE_DIR_NAME)
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def _domain_scene():
    """Return the current csc.domain.Scene, or None when no scene is open."""
    import csc

    app = csc.app.get_application()
    if app is None:
        return None
    view = app.current_scene()
    if view is None:
        return None
    return view.domain_scene() if hasattr(view, "domain_scene") else view


def _stop_existing(server_module):
    if server_module.is_running():
        try:
            server_module.stop(_domain_scene())
            print("[cascadeur-mcp] stopped previous script server")
        except Exception:
            traceback.print_exc()


def _start_on_free_port(server_module, preferred):
    last_error = None
    for candidate in range(preferred, preferred + PORT_CANDIDATES):
        try:
            server_module.start(_domain_scene(), "127.0.0.1", candidate)
            return candidate
        except OSError as exc:  # port already in use
            last_error = exc
            print(f"[cascadeur-mcp] port {candidate} unavailable: {exc}")
        except Exception as exc:  # noqa: BLE001 - report and try the next port
            last_error = exc
            traceback.print_exc()
    raise RuntimeError(f"could not start the Cascadeur script server: {last_error}")


def _install_keeper():
    """Keep Python ticking on the Qt main thread (GIL + scene_idle dispatch)."""
    from events import scene_idle_manager
    from PySide6.QtCore import QTimer

    global _poppet_keeper
    try:
        _poppet_keeper.stop()
    except Exception:
        pass

    def _tick():
        try:
            scene = _domain_scene()
            if scene is not None:
                scene_idle_manager.run(scene)
        except Exception:
            pass

    _poppet_keeper = QTimer()
    _poppet_keeper.setInterval(10)
    _poppet_keeper.timeout.connect(_tick)
    _poppet_keeper.start()
    return _poppet_keeper


def main():
    import scripts.mcp.script_server.server as server_module

    ready = {"ok": False, "python": None, "port": None}
    try:
        _stop_existing(server_module)

        preferred = DEFAULT_PORT
        env_port = os.environ.get("POPPET_SERVER_PORT")
        if env_port:
            try:
                preferred = int(env_port)
            except ValueError:
                print(f"[cascadeur-mcp] ignoring invalid POPPET_SERVER_PORT={env_port!r}")

        port = _start_on_free_port(server_module, preferred)
        _install_keeper()

        ready.update(
            {
                "ok": True,
                "port": port,
                "python": ".".join(str(part) for part in __import__("sys").version_info[:3]),
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        )
        with open(os.path.join(_state_dir(), "server.json"), "w", encoding="utf-8") as handle:
            json.dump(ready, handle, indent=2)

        print(f"[cascadeur-mcp] script server ready at http://127.0.0.1:{port}/mcp")
        print("[cascadeur-mcp] interpreter keeper installed (10 ms); keep Cascadeur open")
        if port != preferred:
            print(
                f"[cascadeur-mcp] set POPPET_URL=http://127.0.0.1:{port} for the MCP client "
                f"(default port {preferred} was busy)"
            )
    except Exception:
        ready["error"] = traceback.format_exc()
        try:
            with open(os.path.join(_state_dir(), "server.json"), "w", encoding="utf-8") as handle:
                json.dump(ready, handle, indent=2)
        except Exception:
            pass
        print("[cascadeur-mcp] bootstrap failed:")
        traceback.print_exc()


main()
