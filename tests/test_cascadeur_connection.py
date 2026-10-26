"""Unit tests for the loopback client's decoding, error mapping, and config.

End-to-end behaviour against Cascadeur's real script server is covered by
``test_native_protocol.py``; these tests pin down the failure modes that make
tool calls pleasant to diagnose.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from poppet_mcp import _expression
from poppet_mcp.cascadeur_connection import (
    CascadeurConnection,
    CascadeurNotRunning,
    CascadeurProtocolError,
    CascadeurScriptError,
    CascadeurTimeout,
)
from poppet_mcp.runtime import load_source, runtime_version, source_digest


def test_runtime_source_declares_version_once():
    source = load_source()
    assert source.count("\nRUNTIME_VERSION = ") == 1
    assert runtime_version() in source


def test_decode_value_round_trips_json_string():
    value = json.dumps({"status": "success", "result": {"x": 1}})
    assert CascadeurConnection._decode_value({"value": repr(value)}) == {
        "status": "success",
        "result": {"x": 1},
    }


def test_decode_value_rejects_empty_value():
    with pytest.raises(CascadeurProtocolError):
        CascadeurConnection._decode_value({"value": ""})


def test_decode_value_rejects_non_json_string():
    with pytest.raises(CascadeurProtocolError):
        CascadeurConnection._decode_value({"value": "not json"})


def test_script_error_includes_traceback_in_message():
    error = CascadeurScriptError("boom", "Traceback (most recent call last): ...")
    assert "boom" in str(error)
    assert "Traceback" in str(error)


def test_url_error_is_reported_as_not_running():
    connection = CascadeurConnection(timeout=1.0)
    exc = urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
    mapped = connection._describe_url_error(connection.url + "/health", exc)
    assert isinstance(mapped, CascadeurNotRunning)
    assert "poppet-bootstrap" in str(mapped)


def test_connection_defaults_track_environment(monkeypatch):
    monkeypatch.setenv("POPPET_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("POPPET_TIMEOUT", "12.5")
    connection = CascadeurConnection()
    assert connection.url == "http://127.0.0.1:9999"
    assert connection.timeout == 12.5


def test_timeout_payload_is_classified(monkeypatch):
    connection = CascadeurConnection(url="http://127.0.0.1:1", timeout=1.0)
    payload = {"ok": False, "error": "Timed out waiting for Cascadeur idle event"}
    monkeypatch.setattr(connection, "_request_json", lambda *a, **k: payload)
    with pytest.raises(CascadeurTimeout):
        connection._post_run("1+1", 1.0)


def test_run_script_returns_raw_failure_instead_of_raising(monkeypatch):
    connection = CascadeurConnection(url="http://127.0.0.1:1", timeout=1.0)
    payload = {"ok": False, "error": "ValueError: boom"}
    monkeypatch.setattr(connection, "_request_json", lambda *a, **k: payload)
    assert connection.run_script("raise ValueError") == payload


def test_request_raises_script_error_with_traceback(monkeypatch):
    connection = CascadeurConnection(url="http://127.0.0.1:1", timeout=1.0)
    inner = json.dumps({"status": "error", "message": "KeyError: 'nope'", "traceback": "tb-line"})
    monkeypatch.setattr(
        connection,
        "_request_json",
        lambda *a, **k: {"ok": True, "value": repr(inner), "messages": []},
    )
    with pytest.raises(CascadeurScriptError) as excinfo:
        connection.request("nope")
    assert "KeyError" in str(excinfo.value)
    assert "tb-line" in str(excinfo.value)


def test_bootstrap_marker_is_defined_and_used_by_expression():
    assert _expression.BOOTSTRAP_MARKER.startswith("__poppet")
    expression = _expression.dispatch_expression("{}", source_digest())
    assert _expression.BOOTSTRAP_MARKER in expression
