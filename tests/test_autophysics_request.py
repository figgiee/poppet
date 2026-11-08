"""Dispatching a native action must not masquerade as solver completion."""

from unittest.mock import MagicMock

import csc
import pytest

from .runtime_loader import runtime


def test_snap_returns_unverified_request_without_main_thread_sleep(monkeypatch):
    sleep = MagicMock(side_effect=AssertionError("must not block native work"))
    monkeypatch.setattr(runtime.time, "sleep", sleep)
    action = MagicMock()
    monkeypatch.setattr(csc.app.get_application().get_action_manager(), "call_action", action)
    result = runtime._d_autophysics_run({"timeout_sec": 25}, MagicMock())
    action.assert_called_once_with("AutoPhysicsTool.Snap to Auto Physics")
    assert result["status"] == "requested"
    assert result["converged"] is None
    assert result["completion_verified"] is False
    sleep.assert_not_called()


def test_snap_dispatch_failure_is_not_reported_as_requested(monkeypatch):
    action = MagicMock(side_effect=RuntimeError("native action unavailable"))
    monkeypatch.setattr(csc.app.get_application().get_action_manager(), "call_action", action)
    with pytest.raises(RuntimeError, match="native action unavailable"):
        runtime._d_autophysics_run({}, MagicMock())
