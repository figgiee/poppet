"""Shared path helpers for the file-sync protocol.

Both sides (Cascadeur dispatcher + MCP server) read/write to:
  %LOCALAPPDATA%\\poppet-mcp\\requests\\<uuid>.json
  %LOCALAPPDATA%\\poppet-mcp\\responses\\<uuid>.json
  %LOCALAPPDATA%\\poppet-mcp\\dispatcher.log
"""

import os
import sys


def base_dir():
    if sys.platform == "win32":
        return os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "poppet-mcp",
        )
    return os.path.expanduser("~/.local/share/poppet-mcp")


def requests_dir():
    p = os.path.join(base_dir(), "requests")
    try:
        os.makedirs(p, exist_ok=True)
    except Exception:
        pass
    return p


def responses_dir():
    p = os.path.join(base_dir(), "responses")
    try:
        os.makedirs(p, exist_ok=True)
    except Exception:
        pass
    return p


def dispatcher_log_path():
    return os.path.join(base_dir(), "dispatcher.log")
