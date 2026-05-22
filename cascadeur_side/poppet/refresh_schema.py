"""Cascadeur command: Poppet → Refresh Schema.

Runs the csc.* reflection script (spec §3) and writes the schema JSON to
%LOCALAPPDATA%\\poppet-mcp\\csc_schema.json (Windows) or
~/.local/share/poppet-mcp/csc_schema.json (mac/linux).

The MCP server reads this file and exposes it as the `csc://schema` resource,
so Claude has accurate method signatures and stops hallucinating csc names.
"""

from . import _introspect


def command_name():
    return "Poppet.Refresh Schema"


def run(scene):
    path = _introspect.dump_schema()
    print("[poppet] schema written to: {}".format(path))
