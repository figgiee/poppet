"""File-sync client to the Cascadeur-side Poppet dispatcher.

Architecture pivot away from sockets — see the project plan. Cascadeur 2025.3.3's
embedded Python can't run a background socket listener (no PySide bundled, no csc
main-thread scheduler, and background Python threads only get one GIL slice).

Protocol:
  - We write `%LOCALAPPDATA%\\poppet-mcp\\requests\\<uuid>.json` with {type, params}.
  - User clicks "Commands -> Poppet -> Process Pending" in Cascadeur (or we nudge
    Cascadeur via Windows-API key-send — see _nudge.py once implemented).
  - The Cascadeur command dispatches and writes the response to
    `%LOCALAPPDATA%\\poppet-mcp\\responses\\<uuid>.json` (atomic via .tmp + rename).
  - We poll the response file and return the result.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any


def _base_dir() -> str:
    if sys.platform == "win32":
        return os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "poppet-mcp",
        )
    return os.path.expanduser("~/.local/share/poppet-mcp")


class CascadeurConnection:
    """File-sync client (kept named CascadeurConnection so server.py imports unchanged)."""

    def __init__(self, timeout: float = 60.0, poll_interval: float = 0.1):
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.base = _base_dir()
        self.req_dir = os.path.join(self.base, "requests")
        self.resp_dir = os.path.join(self.base, "responses")
        os.makedirs(self.req_dir, exist_ok=True)
        os.makedirs(self.resp_dir, exist_ok=True)

    def request(self, command: str, params: dict[str, Any] | None = None) -> Any:
        """Write request, optionally nudge Cascadeur, poll response. Raise on timeout/error."""
        req_id = str(uuid.uuid4())
        req_path = os.path.join(self.req_dir, req_id + ".json")
        resp_path = os.path.join(self.resp_dir, req_id + ".json")
        tmp_path = req_path + ".tmp"

        body = {"type": command, "params": params or {}}
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False)
        os.replace(tmp_path, req_path)

        # Best-effort nudge — the user can also click manually.
        try:
            from poppet_mcp import _nudge
            _nudge.try_nudge_cascadeur()
        except Exception:
            pass

        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if os.path.exists(resp_path):
                try:
                    with open(resp_path, "r", encoding="utf-8") as f:
                        response = json.load(f)
                except Exception:
                    # Response is mid-write — retry next tick.
                    time.sleep(self.poll_interval)
                    continue
                try:
                    os.remove(resp_path)
                except Exception:
                    pass
                if response.get("status") == "error":
                    msg = response.get("message", "unknown error from Cascadeur")
                    if response.get("traceback"):
                        msg = msg + "\n" + response["traceback"]
                    raise RuntimeError(msg)
                return response.get("result")
            time.sleep(self.poll_interval)

        # Timeout — clean up the request file so we don't leave it for a stale drain.
        try:
            os.remove(req_path)
        except Exception:
            pass
        raise TimeoutError(
            "Cascadeur did not respond within {}s. Is Cascadeur running and did "
            "'Commands -> Poppet -> Process Pending' get clicked? (Or is auto-nudge "
            "failing to find Cascadeur's window?)".format(self.timeout)
        )
