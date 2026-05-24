"""Tests for the auto-drain event handlers.

The handlers at poppet_events/scene_{activated,opened}/poppet_drain.py
must:
  1. Import poppet.process_pending lazily (since Cascadeur sets up
     Python.Path before discovering events, but the import order isn't
     part of the contract).
  2. Call process_pending.run(scene) with the scene argument forwarded.
  3. Catch and log every exception so a broken request can't wedge the
     scene-focus pipeline (silently swallowing focus events would be
     much worse than a single failed drain).
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import pytest


def _reload_handler(module_name: str):
    """(Re)load the handler module so each test gets a fresh import."""
    if module_name in sys.modules:
        del sys.modules[module_name]
    return importlib.import_module(module_name)


@pytest.mark.parametrize(
    "module_name",
    [
        "poppet_events.scene_activated.poppet_drain",
        "poppet_events.scene_opened.poppet_drain",
    ],
)
def test_handler_exposes_run(module_name):
    """Cascadeur's events_rule.py requires a `run` function with one arg."""
    mod = _reload_handler(module_name)
    assert hasattr(mod, "run")
    assert callable(mod.run)
    import inspect

    sig = inspect.signature(mod.run)
    assert len(sig.parameters) == 1


@pytest.mark.parametrize(
    "module_name",
    [
        "poppet_events.scene_activated.poppet_drain",
        "poppet_events.scene_opened.poppet_drain",
    ],
)
def test_handler_invokes_process_pending(module_name, monkeypatch):
    """run(scene) must forward to poppet.process_pending.run(scene)."""
    fake_pp = MagicMock(name="process_pending")
    fake_pp.run = MagicMock()
    # The handler does `from poppet import process_pending` at run time;
    # we inject a fake `poppet` module with that attribute on sys.modules.
    fake_poppet = MagicMock(name="poppet")
    fake_poppet.process_pending = fake_pp
    monkeypatch.setitem(sys.modules, "poppet", fake_poppet)

    mod = _reload_handler(module_name)
    sentinel_scene = MagicMock(name="scene-sentinel")
    mod.run(sentinel_scene)

    fake_pp.run.assert_called_once_with(sentinel_scene)


@pytest.mark.parametrize(
    "module_name",
    [
        "poppet_events.scene_activated.poppet_drain",
        "poppet_events.scene_opened.poppet_drain",
    ],
)
def test_handler_swallows_drain_exceptions(module_name, monkeypatch, capsys):
    """A failing process_pending.run must NOT propagate out of the handler."""
    fake_pp = MagicMock(name="process_pending")
    fake_pp.run.side_effect = RuntimeError("simulated dispatcher crash")
    fake_poppet = MagicMock(name="poppet")
    fake_poppet.process_pending = fake_pp
    monkeypatch.setitem(sys.modules, "poppet", fake_poppet)

    mod = _reload_handler(module_name)
    # Should not raise.
    mod.run(MagicMock(name="scene"))

    out = capsys.readouterr().out
    assert "poppet-events" in out
    assert "simulated dispatcher crash" in out


@pytest.mark.parametrize(
    "module_name",
    [
        "poppet_events.scene_activated.poppet_drain",
        "poppet_events.scene_opened.poppet_drain",
    ],
)
def test_handler_survives_missing_poppet_package(module_name, monkeypatch, capsys):
    """If the poppet import fails entirely, we still want to log + return."""
    # Force the import to fail by removing any prior fake injection.
    monkeypatch.delitem(sys.modules, "poppet", raising=False)
    # And make a fresh import of "poppet" raise.
    real_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name == "poppet" or name.startswith("poppet."):
            raise ImportError(f"simulated: no module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    mod = _reload_handler(module_name)
    mod.run(MagicMock(name="scene"))  # must not raise

    out = capsys.readouterr().out
    assert "could not import process_pending" in out
