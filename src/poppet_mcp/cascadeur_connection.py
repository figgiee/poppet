"""Client for Cascadeur 2026.2+'s built-in MCP script server.

Cascadeur 2026.2 ships an in-app HTTP server (``Scripts -> MCP -> Start script
server``) that exposes one primitive: ``run_script`` — execute Python inside the
running Cascadeur on the next ``scene_idle`` event. That primitive makes Poppet's
old file-queue transport (and its Cascadeur-side install) unnecessary: the MCP
server now ships its in-app runtime to Cascadeur as *source text* on the first
tool call and talks to it over loopback HTTP.

Protocol, as implemented by ``scripts/mcp/script_server/server.py`` in the
Cascadeur install:

``GET /health``
    ``{"ok": true, "version": "...", "queued": 0, ...}``

``POST /run`` with ``{"code": "<python>"}``
    Executes the code on the next idle event and returns
    ``{"ok": bool, "value": str, "messages": [...], "error": str?}``.
    The server compiles ``code`` with ``mode="eval"`` first, so Poppet submits a
    single expression (see ``_expression.py``) and reads the result out of
    ``value``.

This module keeps the historical ``CascadeurConnection.request(command, params)``
API so the MCP tool layer does not have to change.
"""

from __future__ import annotations

import ast
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from typing import Any

from poppet_mcp import _expression
from poppet_mcp.runtime import load_source as load_runtime_source
from poppet_mcp.runtime import runtime_version, source_digest

DEFAULT_URL = "http://127.0.0.1:8765"
STATE_DIR_NAME = "poppet-mcp"
DEFAULT_TIMEOUT = 35.0

_NOT_RUNNING_HINT = (
    "Cascadeur's built-in script server is not reachable at {url}.\n"
    "Run Poppet's Cascadeur-side bootstrap once per Cascadeur session:\n"
    "  poppet-bootstrap        (prints the Python Console line to paste)\n"
    "It starts the server and keeps Cascadeur's interpreter ticking; without it,\n"
    "Cascadeur 2026.2's server thread starves while the app is idle."
)

_PORT_CONFLICT_HINT = (
    "Something other than Cascadeur's script server answered at {url}. Another "
    "program is holding that port; run poppet-bootstrap, which picks the next "
    "free port and writes %LOCALAPPDATA%\\poppet-mcp\\server.json so the client "
    "finds it automatically."
)


def _discovered_url() -> str | None:
    """Read the port chosen by poppet-bootstrap's ``server.json``, if present."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, STATE_DIR_NAME, "server.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        port = int(data.get("port"))
        if 0 < port < 65536:
            return f"http://127.0.0.1:{port}"
    except Exception:
        return None
    return None


class CascadeurConnectionError(RuntimeError):
    """Base class for transport-level failures talking to Cascadeur."""


class CascadeurNotRunning(CascadeurConnectionError):
    """The script server is not listening (Cascadeur closed or server stopped)."""


class CascadeurTimeout(CascadeurConnectionError):
    """Cascadeur accepted the request but did not run it before the deadline."""


class CascadeurScriptError(CascadeurConnectionError):
    """The in-app runtime raised; carries the traceback from inside Cascadeur."""

    def __init__(self, message: str, traceback_text: str | None = None):
        super().__init__(message)
        self.traceback_text = traceback_text

    def __str__(self) -> str:
        if self.traceback_text:
            return f"{super().__str__()}\n\nIn-app traceback:\n{self.traceback_text}"
        return super().__str__()


class CascadeurProtocolError(CascadeurConnectionError):
    """The server answered, but not with the protocol Poppet expects."""


def _opener() -> urllib.request.OpenerDirector:
    # Loopback traffic must never go through a system/enterprise proxy.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


class CascadeurConnection:
    """Loopback HTTP client for Cascadeur's built-in script server."""

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        url: str | None = None,
        *,
        runtime_source: str | None = None,
        runtime_version_str: str | None = None,
        poll_interval: float | None = None,  # accepted for backwards compatibility
    ):
        self.url = (url or os.environ.get("POPPET_URL") or _discovered_url() or DEFAULT_URL).rstrip(
            "/"
        )
        self.timeout = float(os.environ.get("POPPET_TIMEOUT", timeout))
        self._runtime_source = runtime_source
        self._runtime_version = runtime_version_str
        self._opener = _opener()

    # -- configuration -----------------------------------------------------

    @property
    def runtime_source(self) -> str:
        if self._runtime_source is None:
            self._runtime_source = load_runtime_source()
        return self._runtime_source

    @property
    def runtime_version(self) -> str:
        if self._runtime_version is None:
            self._runtime_version = runtime_version()
        return self._runtime_version

    @property
    def source_digest(self) -> str:
        """SHA-256 of the runtime source this client would ship."""
        return source_digest()

    # -- public API --------------------------------------------------------

    def health(self, timeout: float = 2.0) -> dict:
        """Return the script server's ``/health`` payload."""
        payload = self._request_json("GET", "/health", None, timeout)
        if not isinstance(payload, dict) or "ok" not in payload:
            raise CascadeurProtocolError(_PORT_CONFLICT_HINT.format(url=self.url))
        return payload

    def run_script(self, code: str, timeout: float | None = None) -> dict:
        """Submit raw Python to the script server and return its raw response.

        Exposed for debugging and for the ``run_script`` escape-hatch tool. The
        raw response is the script server's own dict:
        ``{"ok": bool, "value": str, "messages": [...], "error": str?}``.
        This never raises for in-app script failures — inspect ``ok``/``error``.
        """
        return self._post_run(
            code, self.timeout if timeout is None else timeout, raise_on_error=False
        )

    def request(self, command: str, params: dict[str, Any] | None = None) -> Any:
        """Dispatch one Poppet command through the in-app runtime."""
        request_json = json.dumps({"command": command, "params": params or {}}, ensure_ascii=False)
        payload = self._dispatch(request_json)
        if isinstance(payload, dict) and payload.get(_expression.BOOTSTRAP_MARKER):
            payload = self._bootstrap(request_json)
        if not isinstance(payload, dict):
            raise CascadeurProtocolError(
                f"expected a JSON object from the in-app runtime, got {type(payload).__name__}"
            )
        if payload.get("status") == "error":
            raise CascadeurScriptError(
                str(payload.get("message") or "in-app command failed"),
                payload.get("traceback"),
            )
        return payload.get("result")

    # -- internals ---------------------------------------------------------

    def _dispatch(self, request_json: str) -> Any:
        expression = _expression.dispatch_expression(request_json, self.source_digest)
        response = self._post_run(expression, self.timeout)
        return self._decode_value(response)

    def _bootstrap(self, request_json: str) -> Any:
        expression = _expression.bootstrap_expression(
            request_json, self.source_digest, self.runtime_source
        )
        response = self._post_run(expression, self.timeout)
        payload = self._decode_value(response)
        if isinstance(payload, dict) and payload.get(_expression.BOOTSTRAP_MARKER):
            raise CascadeurProtocolError(
                "in-app runtime failed to load; the script server returned the "
                "bootstrap marker again (unexpected)"
            )
        return payload

    @staticmethod
    def _decode_value(response: dict) -> Any:
        raw = response.get("value")
        if not isinstance(raw, str) or raw == "":
            raise CascadeurProtocolError(
                "script server returned an empty 'value'; the submitted code was "
                "executed as statements instead of as a single expression"
            )
        try:
            text = ast.literal_eval(raw)
        except (ValueError, SyntaxError) as exc:
            raise CascadeurProtocolError(
                f"could not decode script server value {raw[:200]!r}: {exc}"
            ) from exc
        if not isinstance(text, str):
            raise CascadeurProtocolError(
                f"expected a JSON string from the in-app runtime, got {type(text).__name__}"
            )
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise CascadeurProtocolError(f"in-app runtime returned invalid JSON: {exc}") from exc

    def _post_run(self, code: str, timeout: float, *, raise_on_error: bool = True) -> dict:
        payload = self._request_json("POST", "/run", {"code": code}, timeout)
        if not isinstance(payload, dict):
            raise CascadeurProtocolError(
                f"script server /run returned {type(payload).__name__}, expected an object"
            )
        if payload.get("ok") or not raise_on_error:
            return payload
        error = str(payload.get("error") or "unknown script server error")
        if "Timed out waiting for Cascadeur idle event" in error:
            raise CascadeurTimeout(
                "Cascadeur accepted the request but never reached an idle event "
                "(is a modal dialog open, or is the app busy?). The script server "
                "drops requests after ~30s."
            )
        raise CascadeurScriptError(f"script server failed to run the script: {error}")

    def _request_json(self, method: str, path: str, payload: dict | None, timeout: float) -> Any:
        url = self.url + path
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            raise CascadeurProtocolError(self._describe_http_error(url, exc, body)) from exc
        except urllib.error.URLError as exc:
            raise self._describe_url_error(url, exc) from exc
        except TimeoutError as exc:
            raise CascadeurTimeout(
                f"Cascadeur did not answer {url} within {timeout:.0f}s."
            ) from exc
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CascadeurProtocolError(
                f"{url} returned non-JSON content: {body[:200]!r}"
            ) from exc

    def _describe_url_error(self, url: str, exc: urllib.error.URLError) -> CascadeurConnectionError:
        reason = exc.reason
        refused = isinstance(reason, (ConnectionRefusedError, ConnectionResetError)) or getattr(
            reason, "winerror", None
        ) in (10061, 10054)
        timed_out = isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason)
        if refused or timed_out:
            detail = "connection attempt timed out" if timed_out else "connection refused"
            return CascadeurNotRunning(_NOT_RUNNING_HINT.format(url=self.url) + f"\n({detail})")
        return CascadeurConnectionError(f"could not reach {url}: {reason}")

    @staticmethod
    def _describe_http_error(url: str, exc: urllib.error.HTTPError, body: bytes) -> str:
        detail = ""
        try:
            parsed = json.loads(body.decode("utf-8"))
            if isinstance(parsed, dict) and "error" in parsed:
                detail = f" server said: {parsed['error']}"
        except Exception:
            detail = f" body: {body[:200]!r}"
        if exc.code == 404:
            return _PORT_CONFLICT_HINT.format(url=url) + detail
        return f"{url} returned HTTP {exc.code}.{detail}"


def main_probe(url: str | None = None) -> int:
    """CLI helper: print health + ping as JSON; exit non-zero if unreachable."""
    connection = CascadeurConnection(url=url)
    try:
        report = {
            "health": connection.health(),
            "ping": connection.request("ping"),
        }
    except CascadeurConnectionError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({"ok": True, **report}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main_probe())
