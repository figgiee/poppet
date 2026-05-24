"""Tests for cascadeur_side.poppet._dispatchers.dispatch() routing layer.

These exercise the wrapper that maps incoming messages to handlers and
formats success/error responses. The csc mock from conftest.py is in place
so handlers that lazily `import csc` work.
"""

from __future__ import annotations

from poppet import _dispatchers


def test_dispatch_unknown_command_returns_error(fake_scene):
    resp = _dispatchers.dispatch({"type": "no_such_command", "params": {}}, fake_scene)
    assert resp["status"] == "error"
    assert "unknown command" in resp["message"]
    assert "no_such_command" in resp["message"]


def test_dispatch_unknown_command_with_no_params(fake_scene):
    # params is allowed to be missing — dispatch should default to {}.
    resp = _dispatchers.dispatch({"type": "no_such_command"}, fake_scene)
    assert resp["status"] == "error"


def test_dispatch_echo_returns_params(fake_scene):
    payload = {"type": "echo", "params": {"hello": "world", "n": 42}}
    resp = _dispatchers.dispatch(payload, fake_scene)
    assert resp["status"] == "success"
    assert resp["result"] == {"hello": "world", "n": 42}


def test_dispatch_handler_exception_wraps_in_error_with_traceback(fake_scene, monkeypatch):
    """If a handler raises, dispatch returns an error response with traceback."""

    def boom(params, scene):
        raise RuntimeError("synthetic explode")

    monkeypatch.setitem(_dispatchers._HANDLERS, "_test_boom", boom)
    resp = _dispatchers.dispatch({"type": "_test_boom", "params": {}}, fake_scene)
    assert resp["status"] == "error"
    assert "RuntimeError" in resp["message"]
    assert "synthetic explode" in resp["message"]
    assert "traceback" in resp
    assert 'raise RuntimeError("synthetic explode")' in resp["traceback"]


def test_dispatch_handler_value_error_classname_in_message(fake_scene, monkeypatch):
    def bad(params, scene):
        raise ValueError("nope")

    monkeypatch.setitem(_dispatchers._HANDLERS, "_test_bad", bad)
    resp = _dispatchers.dispatch({"type": "_test_bad", "params": {}}, fake_scene)
    assert resp["status"] == "error"
    assert resp["message"].startswith("ValueError: ")


def test_dispatch_missing_type_treated_as_unknown(fake_scene):
    resp = _dispatchers.dispatch({}, fake_scene)
    assert resp["status"] == "error"
    assert "unknown command" in resp["message"]


def test_dispatch_call_action_invokes_csc_action_manager(fake_scene, csc_mock):
    """call_action dispatcher should resolve through csc.app.get_application()."""
    resp = _dispatchers.dispatch(
        {"type": "call_action", "params": {"action_id": "Scene.Undo"}},
        fake_scene,
    )
    assert resp["status"] == "success"
    assert resp["result"] == {"action_id": "Scene.Undo", "invoked": True}
    # Verify the call chain actually fired.
    csc_mock.app.get_application.assert_called()
    am = csc_mock.app.get_application.return_value.get_action_manager.return_value
    am.call_action.assert_called_once_with("Scene.Undo")


def test_dispatch_call_action_rejects_non_string_action_id(fake_scene):
    resp = _dispatchers.dispatch(
        {"type": "call_action", "params": {"action_id": 123}},
        fake_scene,
    )
    assert resp["status"] == "error"
    assert "must be a string" in resp["message"]


def test_dispatch_frame_get_uses_scene_method(fake_scene):
    fake_scene.get_current_frame.return_value = 17
    resp = _dispatchers.dispatch({"type": "frame_get", "params": {}}, fake_scene)
    assert resp == {"status": "success", "result": {"current_frame": 17}}


def test_all_registered_handlers_are_callable():
    for name, handler in _dispatchers._HANDLERS.items():
        assert callable(handler), f"handler {name!r} is not callable"
