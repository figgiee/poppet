"""Shared pytest fixtures for cascadeur-mcp.

The in-app runtime imports `csc` lazily (inside handler bodies), so we install a
MagicMock into sys.modules['csc'] BEFORE any test loads the runtime source. That
lets handlers run outside Cascadeur for unit tests.

We also expose `src/` on sys.path so `poppet_mcp` is importable. The temporary
pytest directory is redirected into the repo (`.pytest-tmp/`) because the host
sandbox denies directory creation under the OS temp root.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

# --- sys.path wiring -----------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO_ROOT, "src")

if SRC not in sys.path:
    sys.path.insert(0, SRC)


def pytest_configure(config):
    """Keep pytest's tmp dirs inside the writable workspace.

    The host sandbox makes pytest's own temp-dir cleanup unreliable (it tries to
    enumerate a directory tree the confined process cannot always re-read), so
    cleanup is disabled here: the directories live in ``.pytest-tmp/`` and are
    gitignored.
    """
    if not config.option.basetemp:
        base = os.path.join(REPO_ROOT, ".pytest-tmp")
        os.makedirs(base, exist_ok=True)
        config.option.basetemp = base
    import _pytest.pathlib

    _pytest.pathlib.cleanup_dead_symlinks = lambda root: None


# --- csc mock — installed at import time, BEFORE _dispatchers imports ----
#
# The dispatchers do `import csc` inside function bodies, so installing a
# MagicMock here makes those imports return our mock without ever hitting
# Cascadeur's real csc module. We do submodule access (csc.model.ObjectId,
# csc.math.Rotation, csc.app.get_application, csc.fbx.*) so MagicMock's
# default attribute auto-creation does the right thing.


def _install_csc_mock() -> MagicMock:
    csc = MagicMock(name="csc")
    # Make csc.model.ObjectId behave like a class with .null() classmethod-ish.
    csc.model.ObjectId = MagicMock(name="ObjectId")
    csc.model.ObjectId.null = MagicMock(return_value="<null-obj-id>")
    # Rotation.from_euler returns something we can pass through.
    csc.math.Rotation.from_euler = MagicMock(return_value="<rotation-from-euler>")
    sys.modules["csc"] = csc
    sys.modules["csc.app"] = csc.app
    sys.modules["csc.model"] = csc.model
    sys.modules["csc.math"] = csc.math
    sys.modules["csc.fbx"] = csc.fbx
    return csc


_CSC_MOCK = _install_csc_mock()


@pytest.fixture
def csc_mock():
    """Fresh-state csc MagicMock for a single test.

    Returns the module-level mock (it's already in sys.modules) but resets
    the call tracking so each test sees a clean slate.
    """
    _CSC_MOCK.reset_mock()
    # Re-stub the leaves that reset_mock() blew away.
    _CSC_MOCK.model.ObjectId.null = MagicMock(return_value="<null-obj-id>")
    _CSC_MOCK.math.Rotation.from_euler = MagicMock(return_value="<rotation-from-euler>")
    return _CSC_MOCK


@pytest.fixture
def fake_scene():
    """Minimal csc.domain.Scene-shaped MagicMock.

    Tests that need richer behavior should configure attributes on the
    returned MagicMock (e.g. fake_scene.model_viewer.return_value.get_objects
    .return_value = [...]).
    """
    scene = MagicMock(name="scene")
    # Sensible defaults so basic dispatchers don't blow up.
    scene.get_current_frame.return_value = 0
    scene.model_viewer.return_value.get_objects.return_value = []
    scene.layers_viewer.return_value.all_layer_ids.return_value = []
    scene.selector.return_value.selected.return_value.ids = []
    return scene
