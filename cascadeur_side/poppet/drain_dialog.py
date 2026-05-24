"""Cascadeur command: Poppet -> Status / Drain Dialog.

Opens a Cascadeur dialog showing the current Poppet queue depth and offering
a one-click drain (plus a "drain forever" toggle hint). Useful when running
without the auto-drain events handler, or when you want a visible queue
inspector before draining.

Mirrors the dialog pattern used by Cascadeur's bundled
commands/animation_scripts/add_noise_to_selected_objs.py:
    csc.view.DialogManager.instance().show_buttons_dialog(title, body, buttons)
where buttons is a dict mapping label -> callback.
"""

import os

import csc

from . import _paths, process_pending


def command_name():
    return "Poppet.Status / Drain Dialog"


def _count_pending():
    try:
        req_dir = _paths.requests_dir()
        return sum(1 for f in os.listdir(req_dir) if f.endswith(".json"))
    except Exception:
        return 0


def _show_info(title, body):
    try:
        csc.view.DialogManager.instance().show_info(title, body)
    except Exception:
        print(f"[poppet] {title}: {body}")


def run(scene):
    pending = _count_pending()
    log_path = _paths.dispatcher_log_path()

    body_lines = [
        f"Pending requests: {pending}",
        f"Queue dir: {_paths.requests_dir()}",
        f"Log: {log_path}",
        "",
        "Drain Now = process all pending and write responses.",
        "Open Queue Dir = open the requests folder in Explorer.",
        "Close = do nothing.",
    ]
    body = "\n".join(body_lines)

    def on_drain():
        try:
            process_pending.run(scene)
            after = _count_pending()
            _show_info("Poppet", f"Drained. {after} request(s) remaining.")
        except Exception as e:
            _show_info("Poppet drain error", f"{type(e).__name__}: {e}")

    def on_open_dir():
        try:
            import subprocess
            import sys

            req = _paths.requests_dir()
            if sys.platform == "win32":
                subprocess.Popen(["explorer", req])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", req])
            else:
                subprocess.Popen(["xdg-open", req])
        except Exception as e:
            _show_info("Poppet", f"Couldn't open dir: {e}")

    def on_close():
        pass

    buttons = {
        "Drain Now": on_drain,
        "Open Queue Dir": on_open_dir,
        "Close": on_close,
    }

    try:
        csc.view.DialogManager.instance().show_buttons_dialog(
            "Poppet — Status",
            body,
            buttons,
        )
    except Exception as e:
        # Headless fallback — log + drain.
        print(f"[poppet] dialog unavailable ({e}), draining inline")
        on_drain()
