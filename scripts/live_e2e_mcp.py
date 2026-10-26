"""Live end-to-end test through the real MCP stdio transport.

Spawns ``cascadeur-mcp`` exactly as a client would, performs the MCP handshake,
lists tools, and calls a handful of tools that reach the running Cascadeur.
Requires Cascadeur 2026.2.3 with cascadeur-mcp's console bootstrap active.

Usage::

    python scripts/live_e2e_mcp.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_MIN_TOOLS = 45


async def run() -> int:
    env = os.environ.copy()
    env.pop("POPPET_URL", None)  # exercise port auto-discovery via server.json
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "poppet_mcp.server"],
        env=env,
    )
    failures = 0

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"MCP initialize OK: {init.serverInfo.name} {init.serverInfo.version}")

            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            print(f"{len(names)} tools registered")
            if len(names) < EXPECTED_MIN_TOOLS:
                failures += 1
                print(f"FAIL expected >= {EXPECTED_MIN_TOOLS} tools")
            for required in ("get_script_server_status", "run_script", "get_scene_info"):
                if required not in names:
                    failures += 1
                    print(f"FAIL missing tool: {required}")

            async def call(tool: str, args: dict | None = None) -> object:
                nonlocal failures
                try:
                    result = await session.call_tool(tool, args or {})
                    if result.isError:
                        failures += 1
                        detail = result.content[0].text if result.content else "unknown error"
                        print(f"FAIL {tool}: {detail[:300]}")
                        return None
                    text = result.content[0].text if result.content else ""
                    parsed = json.loads(text) if text.startswith(("{", "[")) else text
                    print(f"PASS {tool}: {str(parsed)[:180]}")
                    return parsed
                except Exception as exc:  # noqa: BLE001 - report and continue
                    failures += 1
                    print(f"FAIL {tool}: {exc}")
                    return None

            await call("get_script_server_status")
            await call("get_scene_info")
            await call("list_layers")
            await call("get_current_frame")
            await call("run_script", {"code": "1 + 1"})
            await call("execute_csc_code", {"code": "import sys; sys.version.split()[0]"})

    print()
    if failures:
        print(f"{failures} MCP end-to-end check(s) failed")
        return 1
    print("MCP stdio -> cascadeur-mcp -> Cascadeur end-to-end checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
