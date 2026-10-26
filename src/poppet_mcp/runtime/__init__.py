"""Loader for the in-app runtime source that is shipped to Cascadeur.

The runtime lives in ``inapp.py`` as plain source text. Keeping it as a file
(not an importable module) makes the contract obvious: it executes inside
Cascadeur's embedded interpreter, never in the MCP server process.

Two identities are derived from that one source file:

* ``runtime_version()`` — the human-readable ``RUNTIME_VERSION`` stamp, reported
  by ``get_script_server_status``.
* ``source_digest()`` — SHA-256 of the exact source text. This is the real wire
  contract: the client only trusts a loaded ``poppet_rt`` module whose digest
  matches the source it would ship, so editing handlers can never leave a stale
  runtime silently answering tool calls.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

SOURCE_NAME = "inapp.py"
_VERSION_RE = re.compile(r'^RUNTIME_VERSION = "([^"]+)"$', re.MULTILINE)

_cached_source: str | None = None
_cached_version: str | None = None
_cached_digest: str | None = None


def _source_path() -> Path:
    return Path(__file__).with_name(SOURCE_NAME)


def load_source() -> str:
    """Return the exact source text shipped to Cascadeur."""
    global _cached_source
    if _cached_source is None:
        _cached_source = _source_path().read_text(encoding="utf-8")
    return _cached_source


def source_digest() -> str:
    """SHA-256 of the shipped runtime source (the wire-contract identity)."""
    global _cached_digest
    if _cached_digest is None:
        _cached_digest = hashlib.sha256(load_source().encode("utf-8")).hexdigest()
    return _cached_digest


def runtime_version() -> str:
    """Return the human-readable runtime version parsed out of the source."""
    global _cached_version
    if _cached_version is None:
        match = _VERSION_RE.search(load_source())
        if match is None:
            raise RuntimeError(f"{SOURCE_NAME} does not declare RUNTIME_VERSION")
        _cached_version = match.group(1)
    return _cached_version
