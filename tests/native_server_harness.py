"""Run Cascadeur's *shipped* MCP script server locally, with fake host modules.

Cascadeur 2026.2.3 installs ``scripts/mcp/script_server/server.py``. That file is
the protocol peer our client must satisfy, so the most honest integration test is
to execute **the real file**, with ``csc`` and ``events`` replaced by small fakes
and a driver thread standing in for Cascadeur's ``scene_idle`` event.

This lets us validate the eval-expression wire format, bootstrap/reload behaviour,
error propagation, and timeouts without launching Cascadeur.

The harness is skipped automatically when the Cascadeur install is not present.
"""

from __future__ import annotations

import enum
import importlib.util
import itertools
import sys
import threading
import time
import traceback
import types
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NATIVE_SERVER_PATH = Path(
    r"C:\Users\sandv\AppData\Local\Cascadeur\resources\scripts\python"
    r"\scripts\mcp\script_server\server.py"
)

_module_counter = itertools.count(1)


def available() -> bool:
    """True when the local Cascadeur install ships the script server."""
    return NATIVE_SERVER_PATH.is_file()


class FakeMessageLevel(enum.IntEnum):
    Info = 0
    Warning = 1
    Error = 2


class FakeMessageManager:
    """Stand-in for ``events.event_message_manager``."""

    def __init__(self) -> None:
        self._subscribers: dict[int, Any] = {}
        self._next_id = 0
        self._lock = threading.Lock()

    def subscribe(self, callback):
        with self._lock:
            self._next_id += 1
            subscription_id = self._next_id
            self._subscribers[subscription_id] = callback
        return subscription_id

    def unsubscribe(self, subscription_id):
        with self._lock:
            self._subscribers.pop(subscription_id, None)

    def emit(self, *args):
        with self._lock:
            callbacks = list(self._subscribers.values())
        for callback in callbacks:
            callback(*args)


class FakeIdleManager(FakeMessageManager):
    """Stand-in for ``events.scene_idle_manager``.

    Subscribing starts a daemon thread that keeps firing the idle event at the
    fake scene, mirroring how Cascadeur drives the server from its main loop.
    """

    def __init__(self, scene, interval: float = 0.01) -> None:
        super().__init__()
        self.scene = scene
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def subscribe(self, callback):
        subscription_id = super().subscribe(callback)
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="fake-scene-idle", daemon=True)
            self._thread.start()
        return subscription_id

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.emit(self.scene)
            self._stop.wait(self.interval)

    def unsubscribe(self, subscription_id):
        super().unsubscribe(subscription_id)
        if not self._subscribers:
            self._stop.set()


class FakeApp:
    def __init__(self, scene) -> None:
        self._scene = scene

    def current_scene(self):
        return self._scene


@dataclass
class NativeServer:
    """A running instance of Cascadeur's shipped script server."""

    module: types.ModuleType
    port: int
    scene: Any

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _install_fake_modules(scene):
    """Install fake ``csc`` / ``events`` modules for Cascadeur's script server.

    ``csc`` is a MagicMock with a real ``MessageLevel`` enum and an ``app``
    submodule whose ``get_application()`` returns a mock application, so real
    Poppet handlers can be exercised end-to-end: unknown attributes auto-create
    instead of raising AttributeError.
    """
    from unittest.mock import MagicMock

    csc = MagicMock(name="csc")
    csc.MessageLevel = FakeMessageLevel

    csc_app = MagicMock(name="csc.app")
    application = MagicMock(name="application")
    application.current_scene.return_value = scene
    csc_app.get_application.return_value = application
    csc.app = csc_app

    events = types.ModuleType("events")
    events.event_message_manager = FakeMessageManager()
    events.scene_idle_manager = FakeIdleManager(scene)

    saved = {name: sys.modules.get(name) for name in ("csc", "csc.app", "events")}
    sys.modules["csc"] = csc
    sys.modules["csc.app"] = csc_app
    sys.modules["events"] = events
    return saved


def _restore_modules(saved) -> None:
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


@contextmanager
def native_server(port: int = 0, scene: Any | None = None) -> Iterator[NativeServer]:
    """Load and start Cascadeur's shipped script server, then tear it down."""
    if not available():
        raise RuntimeError(f"Cascadeur script server not found at {NATIVE_SERVER_PATH}")

    scene = scene if scene is not None else object()
    saved = _install_fake_modules(scene)
    module_name = f"cascadeur_native_server_{next(_module_counter)}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, NATIVE_SERVER_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        module.start(scene, "127.0.0.1", port)
        real_port = module._server.server_address[1]
        yield NativeServer(module=module, port=real_port, scene=scene)
    finally:
        try:
            module.stop(scene)  # type: ignore[possibly-undefined]
        except Exception:
            traceback.print_exc()
        sys.modules.pop(module_name, None)
        _restore_modules(saved)


def wait_until_idle(server: NativeServer, timeout: float = 2.0) -> None:
    """Block until the fake idle driver has drained the request queue."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if server.module._requests.empty():
            return
        time.sleep(0.005)
    raise TimeoutError("script server request queue did not drain")
