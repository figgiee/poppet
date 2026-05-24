"""Tests for the Process Pending drain loop.

cascadeur_side/poppet/process_pending.py is the heart of the file-sync
protocol: it walks the requests dir, dispatches each request, writes a
response file, and removes the request. Failures must not wedge the loop —
a bad request should produce an error response, NOT crash the drain.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest
from poppet import _paths, process_pending


@pytest.fixture
def isolated_queue(tmp_path, monkeypatch):
    """Redirect _paths to a tmp_path so we don't touch the real queue."""
    base = tmp_path / "poppet-mcp"
    req = base / "requests"
    resp = base / "responses"
    req.mkdir(parents=True)
    resp.mkdir(parents=True)

    monkeypatch.setattr(_paths, "requests_dir", lambda: str(req))
    monkeypatch.setattr(_paths, "responses_dir", lambda: str(resp))
    monkeypatch.setattr(_paths, "dispatcher_log_path", lambda: str(base / "log.txt"))
    return req, resp


def _queue_request(req_dir, uuid, cmd, params=None):
    p = req_dir / f"{uuid}.json"
    p.write_text(json.dumps({"type": cmd, "params": params or {}}))
    return p


def test_drain_empty_queue_is_noop(isolated_queue, fake_scene):
    req, resp = isolated_queue
    process_pending.run(fake_scene)
    assert list(resp.iterdir()) == []


def test_drain_processes_echo_request(isolated_queue, fake_scene):
    req, resp = isolated_queue
    _queue_request(req, "test-echo", "echo", {"hello": "world"})

    process_pending.run(fake_scene)

    # Response file appears with success status; request is removed.
    resp_files = list(resp.iterdir())
    assert len(resp_files) == 1
    assert resp_files[0].name == "test-echo.json"
    body = json.loads(resp_files[0].read_text())
    assert body["status"] == "success"
    assert body["result"] == {"hello": "world"}
    assert list(req.iterdir()) == []


def test_drain_handles_malformed_request_without_crashing(isolated_queue, fake_scene):
    req, resp = isolated_queue
    (req / "broken.json").write_text("{not valid json")

    # Must not raise.
    process_pending.run(fake_scene)

    resp_files = list(resp.iterdir())
    assert len(resp_files) == 1
    body = json.loads(resp_files[0].read_text())
    assert body["status"] == "error"
    assert "could not read request" in body["message"]


def test_drain_handles_unknown_command(isolated_queue, fake_scene):
    req, resp = isolated_queue
    _queue_request(req, "test-unknown", "nonexistent_command")

    process_pending.run(fake_scene)

    body = json.loads((resp / "test-unknown.json").read_text())
    assert body["status"] == "error"
    assert "unknown command" in body["message"]


def test_drain_handles_dispatcher_exception(isolated_queue, fake_scene):
    req, resp = isolated_queue
    _queue_request(req, "test-crash", "exec_csc", {"code": "1/0"})

    process_pending.run(fake_scene)

    body = json.loads((resp / "test-crash.json").read_text())
    assert body["status"] == "error"
    assert "ZeroDivisionError" in body["message"]
    assert "traceback" in body


def test_drain_processes_multiple_requests_in_order(isolated_queue, fake_scene):
    req, resp = isolated_queue
    for i in range(5):
        _queue_request(req, f"test-{i:02d}", "echo", {"index": i})

    process_pending.run(fake_scene)

    resp_files = sorted(resp.iterdir())
    assert len(resp_files) == 5
    for i, rf in enumerate(resp_files):
        body = json.loads(rf.read_text())
        assert body["status"] == "success"
        assert body["result"]["index"] == i


def test_drain_writes_response_atomically(isolated_queue, fake_scene):
    """Atomic write means: response.tmp never lingers if the rename succeeds."""
    req, resp = isolated_queue
    _queue_request(req, "test-atomic", "echo", {"x": 1})

    process_pending.run(fake_scene)

    # No leftover .tmp files.
    leftovers = [p for p in resp.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == [], f"found stale .tmp files: {leftovers}"


def test_drain_continues_after_one_bad_request(isolated_queue, fake_scene):
    req, resp = isolated_queue
    _queue_request(req, "a-ok", "echo", {"order": "first"})
    (req / "b-broken.json").write_text("not json at all")
    _queue_request(req, "c-ok", "echo", {"order": "third"})

    process_pending.run(fake_scene)

    resp_files = {p.name for p in resp.iterdir()}
    assert resp_files == {"a-ok.json", "b-broken.json", "c-ok.json"}

    # All three responses written; both ok requests succeeded.
    a = json.loads((resp / "a-ok.json").read_text())
    b = json.loads((resp / "b-broken.json").read_text())
    c = json.loads((resp / "c-ok.json").read_text())
    assert a["status"] == "success"
    assert b["status"] == "error"
    assert c["status"] == "success"


def test_drain_removes_request_even_on_response_write_failure(isolated_queue, fake_scene):
    req, resp = isolated_queue
    _queue_request(req, "test-resp-fail", "echo", {"x": 1})

    # Simulate response write failing.
    real_replace = os.replace

    def fake_replace(src, dst):
        if str(dst).endswith("test-resp-fail.json"):
            raise OSError("disk full")
        return real_replace(src, dst)

    with patch("os.replace", side_effect=fake_replace):
        process_pending.run(fake_scene)

    # Request file IS removed (drain shouldn't keep retrying a failed write).
    assert not (req / "test-resp-fail.json").exists()
