"""Persistent TCP connection to the Cascadeur-side Poppet server.

Length-prefixed JSON framing (matches cascadeur_side/poppet/_framing.py).
Auto-reconnects on transient failures, raises a friendly error if the
Cascadeur-side server isn't running.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any

HEADER_LEN = 64


class CascadeurConnection:
    """Mirrors blender-mcp's BlenderConnection: persistent socket + auto-reconnect."""

    def __init__(self, host: str = "127.0.0.1", port: int = 53145, timeout: float = 180.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()

    def _connect(self) -> None:
        if self._sock is not None:
            return
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect((self.host, self.port))
        self._sock = s

    def _close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _send(self, message: dict[str, Any]) -> None:
        assert self._sock is not None
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        header = str(len(body)).encode("ascii")
        header += b" " * (HEADER_LEN - len(header))
        self._sock.sendall(header + body)

    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("peer closed mid-message")
            buf += chunk
        return buf

    def _recv(self) -> dict[str, Any]:
        header = self._recv_exact(HEADER_LEN)
        length = int(header.decode("ascii").strip())
        body = self._recv_exact(length)
        return json.loads(body.decode("utf-8"))

    def request(self, command: str, params: dict[str, Any] | None = None) -> Any:
        """Send a command, return the result. Raises on transport or command error."""
        with self._lock:
            last_err: Exception | None = None
            for attempt in (1, 2):
                try:
                    self._connect()
                    self._send({"type": command, "params": params or {}})
                    response = self._recv()
                except (ConnectionError, ConnectionResetError, OSError, socket.timeout) as e:
                    self._close()
                    last_err = e
                    if attempt == 1:
                        time.sleep(0.2)
                        continue
                    raise ConnectionError(
                        f"Could not reach Cascadeur Poppet server at {self.host}:{self.port} "
                        f"({type(e).__name__}: {e}). "
                        "Is Cascadeur running with 'Commands → Poppet → Start Server' active?"
                    ) from e

                if response.get("status") == "error":
                    raise RuntimeError(
                        response.get("message", "unknown error from Cascadeur")
                        + (("\n" + response["traceback"]) if response.get("traceback") else "")
                    )
                return response.get("result")
            raise RuntimeError(f"unreachable; last error: {last_err}")
