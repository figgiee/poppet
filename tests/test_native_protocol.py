"""Integration tests against Cascadeur's *shipped* MCP script server.

The harness loads the real ``scripts/mcp/script_server/server.py`` from the local
Cascadeur 2026.2 install, substitutes small fakes for ``csc``/``events``, and
drives the server's ``scene_idle`` subscription from a thread. That exercises the
actual protocol peer Poppet talks to in production — without the GUI.
"""

from __future__ import annotations

import socket
import sys

import pytest

from poppet_mcp import _expression
from poppet_mcp.cascadeur_connection import (
    CascadeurConnection,
    CascadeurNotRunning,
    CascadeurProtocolError,
    CascadeurScriptError,
)
from poppet_mcp.runtime import runtime_version

from .native_server_harness import available, native_server

pytestmark = pytest.mark.skipif(
    not available(), reason="Cascadeur 2026.2 script server is not installed locally"
)


@pytest.fixture()
def server():
    with native_server() as running:
        yield running


@pytest.fixture()
def client(server):
    return CascadeurConnection(url=server.url, timeout=15.0)


def test_health_reports_the_native_server(client):
    health = client.health()
    assert health["ok"] is True
    assert "version" in health


def test_ping_bootstraps_runtime_inside_the_host(client):
    payload = client.request("ping")
    assert payload["pong"] is True
    assert payload["runtime_version"] == runtime_version()
    assert payload["has_scene"] is True


def test_repeated_calls_reuse_the_loaded_runtime(client):
    assert client.request("ping")["pong"] is True
    assert client.request("ping")["pong"] is True


def test_runtime_is_rebootstrapped_after_module_loss(client):
    assert client.request("ping")["pong"] is True
    # Simulates a Cascadeur restart / script-reload clearing the private module.
    sys.modules.pop(_expression.RUNTIME_MODULE, None)
    assert client.request("ping")["pong"] is True


def test_unknown_command_raises_actionable_error(client):
    with pytest.raises(CascadeurScriptError) as excinfo:
        client.request("definitely_not_a_command")
    assert "unknown command" in str(excinfo.value)


def test_handler_exception_carries_in_app_traceback(client):
    with pytest.raises(CascadeurScriptError) as excinfo:
        client.request("exec_csc", {"code": "raise ValueError('boom')"})
    assert "ValueError: boom" in str(excinfo.value)
    assert "Traceback" in (excinfo.value.traceback_text or "")


def test_run_script_passthrough_returns_raw_response(client):
    raw = client.run_script("1 + 1")
    assert raw["ok"] is True
    assert raw["value"] == "2"


def test_errors_inside_submitted_code_are_surfaced(client):
    raw = client.run_script("raise ValueError('boom')")
    assert raw["ok"] is False
    assert "ValueError: boom" in raw["error"]


def test_connection_refused_is_actionable():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    connection = CascadeurConnection(url=f"http://127.0.0.1:{port}", timeout=1.0)
    with pytest.raises(CascadeurNotRunning) as excinfo:
        connection.health()
    assert "Scripts -> MCP -> Start script server" in str(excinfo.value)


def test_port_conflict_is_diagnosed():
    """A foreign HTTP server on 8765 is reported as a port conflict."""
    import http.server
    import json
    import threading

    class ForeignHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"error": {"code": "not_found"}}).encode()
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            return

    foreign = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ForeignHandler)
    thread = threading.Thread(target=foreign.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{foreign.server_address[1]}"
        connection = CascadeurConnection(url=url, timeout=5.0)
        with pytest.raises(CascadeurProtocolError) as excinfo:
            connection.health()
        assert "port 8765" in str(excinfo.value)
    finally:
        foreign.shutdown()
        foreign.server_close()
