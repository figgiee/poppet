"""Shared pytest fixtures for Poppet.

The Cascadeur-side dispatchers import `csc` lazily (inside function bodies),
so we install a MagicMock into sys.modules['csc'] BEFORE any test imports
_dispatchers. This lets the dispatchers run outside Cascadeur for unit tests.

We also expose the cascadeur_side/ tree on sys.path so the `poppet` package
(not to be confused with the MCP server's `poppet_mcp`) can be imported.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

# --- sys.path wiring -----------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASCADEUR_SIDE = os.path.join(REPO_ROOT, "cascadeur_side")
SRC = os.path.join(REPO_ROOT, "src")

for p in (SRC, CASCADEUR_SIDE):
    if p not in sys.path:
        sys.path.insert(0, p)


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
