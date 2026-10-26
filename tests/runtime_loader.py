"""Load cascadeur-mcp's in-app runtime as an importable module for unit tests.

The runtime is normally shipped to Cascadeur as source text (see
``poppet_mcp.runtime``), never imported by the MCP server. Tests execute that
same source here, with the ``csc`` MagicMock installed by ``conftest`` standing
in for Cascadeur's API. Testing the exact shipped bytes — not a copy — keeps the
unit tests honest.

``runtime`` is a real module object, so ``from .runtime_loader import runtime as
_dispatchers`` gives tests the same call surface the old dispatcher package had.
"""

from __future__ import annotations

import types

from poppet_mcp.runtime import load_source


def _build() -> types.ModuleType:
    module = types.ModuleType("poppet_rt")
    exec(compile(load_source(), "<poppet_rt>", "exec"), module.__dict__)
    return module


runtime = _build()
