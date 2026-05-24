"""Tests for poppet_mcp.cascadeur_connection.CascadeurConnection.request.

A thread plays the role of Cascadeur: it polls the requests directory, picks
up our request file, and atomically writes a response. This lets us exercise
the full request / response loop without Cascadeur, the MCP layer, or sockets.
"""

from __future__ import annotations

import json
import os
import threading
import time

import pytest

from poppet_mcp.cascadeur_connection import CascadeurConnection


def _make_conn(tmp_path, monkeypatch, **kwargs) -> CascadeurConnection:
    """Build a CascadeurConnection that lives entirely under tmp_path."""
    # Point _base_dir() at our tmp dir by setting LOCALAPPDATA (Windows path) and
    # also patching the module's _base_dir for non-Windows platforms.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import poppet_mcp.cascadeur_connection as cc

    monkeypatch.setattr(cc, "_base_dir", lambda: str(tmp_path / "poppet-mcp"))
    return CascadeurConnection(timeout=5.0, poll_interval=0.02, **kwargs)


class _FakeCascadeur:
    """Background drain loop that mimics process_pending.run()."""

    def __init__(self, req_dir: str, resp_dir: str, responder):
        self.req_dir = req_dir
        self.resp_dir = resp_dir
        self.responder = responder  # callable(request_dict) -> response_dict
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.seen: list[dict] = []

    def _loop(self):
        while not self.stop.is_set():
            try:
                files = [f for f in os.listdir(self.req_dir) if f.endswith(".json")]
            except FileNotFoundError:
                files = []
            for fname in files:
                req_path = os.path.join(self.req_dir, fname)
                try:
                    with open(req_path, encoding="utf-8") as f:
                        req = json.load(f)
                except Exception:
                    # Mid-write — try again.
                    continue
                self.seen.append(req)
                try:
                    response = self.responder(req)
                except Exception as e:
                    response = {"status": "error", "message": f"responder raised: {e}"}
                resp_path = os.path.join(self.resp_dir, fname)
                tmp = resp_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(response, f, ensure_ascii=False)
                os.replace(tmp, resp_path)
                try:
                    os.remove(req_path)
                except FileNotFoundError:
                    pass
            time.sleep(0.01)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(timeout=2.0)


# --- happy path -----------------------------------------------------------


def test_request_round_trip_returns_result(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)

    def responder(req: dict) -> dict:
        assert req["type"] == "echo"
        return {"status": "success", "result": {"params": req["params"], "ok": True}}

    with _FakeCascadeur(conn.req_dir, conn.resp_dir, responder) as fake:
        result = conn.request("echo", {"hi": "there"})

    assert result == {"params": {"hi": "there"}, "ok": True}
    assert len(fake.seen) == 1
    assert fake.seen[0] == {"type": "echo", "params": {"hi": "there"}}


def test_request_with_no_params_sends_empty_dict(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)

    def responder(req):
        return {"status": "success", "result": req["params"]}

    with _FakeCascadeur(conn.req_dir, conn.resp_dir, responder):
        result = conn.request("scene_info")

    assert result == {}


def test_request_cleans_up_response_file(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)

    def responder(req):
        return {"status": "success", "result": "ok"}

    with _FakeCascadeur(conn.req_dir, conn.resp_dir, responder):
        conn.request("ping")

    # After a successful request the response file should be deleted by the client.
    leftover = [f for f in os.listdir(conn.resp_dir) if f.endswith(".json")]
    assert leftover == []


# --- error path -----------------------------------------------------------


def test_request_error_response_raises_runtime_error(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)

    def responder(req):
        return {
            "status": "error",
            "message": "ValueError: bad thing",
            "traceback": "Traceback (most recent call last):\n  fake line\nValueError: bad thing",
        }

    with _FakeCascadeur(conn.req_dir, conn.resp_dir, responder):
        with pytest.raises(RuntimeError) as ei:
            conn.request("autopose_run", {})

    assert "ValueError: bad thing" in str(ei.value)
    assert "Traceback" in str(ei.value)


def test_request_error_without_traceback_still_raises(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)

    def responder(req):
        return {"status": "error", "message": "no traceback present"}

    with _FakeCascadeur(conn.req_dir, conn.resp_dir, responder):
        with pytest.raises(RuntimeError, match="no traceback present"):
            conn.request("frame_set", {"frame": 99})


# --- timeout --------------------------------------------------------------


def test_request_times_out_when_no_response(tmp_path, monkeypatch):
    # No FakeCascadeur — nothing drains the queue.
    conn = _make_conn(tmp_path, monkeypatch)
    conn.timeout = 0.2  # keep the test fast

    start = time.monotonic()
    with pytest.raises(TimeoutError, match="Cascadeur did not respond"):
        conn.request("echo", {})
    elapsed = time.monotonic() - start

    # Should have honored the timeout (with a little slack for scheduling).
    assert 0.15 <= elapsed < 2.0
    # Timeout path should also clean up the request file so a later drain doesn't
    # see a stale request.
    leftover = [f for f in os.listdir(conn.req_dir) if f.endswith(".json")]
    assert leftover == []


# --- mid-write resilience -------------------------------------------------


def test_request_retries_on_partial_response_read(tmp_path, monkeypatch):
    """If the client sees the response file before the writer is done, it retries."""
    conn = _make_conn(tmp_path, monkeypatch)

    # Custom fake that writes an invalid (truncated) file first, then a real one.
    def adversarial_writer():
        # Wait for a request to appear.
        deadline = time.time() + 3.0
        req_file = None
        while time.time() < deadline:
            candidates = [f for f in os.listdir(conn.req_dir) if f.endswith(".json")]
            if candidates:
                req_file = candidates[0]
                break
            time.sleep(0.01)
        assert req_file, "client never wrote a request"

        uuid_str = req_file[:-5]
        resp_path = os.path.join(conn.resp_dir, uuid_str + ".json")

        # Step 1: write a corrupted, partial response (NOT atomic — direct write).
        with open(resp_path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        # Give the client a tick to attempt a read.
        time.sleep(0.05)
        # Step 2: replace with the real response atomically.
        tmp = resp_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"status": "success", "result": "eventually-ok"}, f)
        os.replace(tmp, resp_path)
        try:
            os.remove(os.path.join(conn.req_dir, req_file))
        except FileNotFoundError:
            pass

    t = threading.Thread(target=adversarial_writer, daemon=True)
    t.start()
    try:
        result = conn.request("echo", {})
    finally:
        t.join(timeout=2.0)

    assert result == "eventually-ok"


# --- directory creation ---------------------------------------------------


def test_init_creates_request_and_response_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import poppet_mcp.cascadeur_connection as cc

    monkeypatch.setattr(cc, "_base_dir", lambda: str(tmp_path / "freshly-made"))
    conn = CascadeurConnection()
    assert os.path.isdir(conn.req_dir)
    assert os.path.isdir(conn.resp_dir)
