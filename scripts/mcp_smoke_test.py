"""Minimal MCP server smoke test — proves the stdio pipe works.

Spawns the poppet-mcp server as a subprocess via the MCP client SDK's
stdio_client, initializes the session, lists tools, and exits.

This does NOT call any tool against Cascadeur (which would require a manual
Process Pending click). It only proves:
  1. The poppet-mcp console script starts under MCP stdio transport.
  2. The MCP handshake completes (initialize message exchange).
  3. All FastMCP @mcp.tool() decorations registered correctly.

For the full Cascadeur-driving demo, use demo_batch_spec4.py.
"""

from __future__ import annotations

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run() -> int:
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "poppet_mcp.server"],
        env=os.environ.copy(),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("MCP initialize OK:")
            print(f"  server name   : {init.serverInfo.name}")
            print(f"  server version: {init.serverInfo.version}")
            print(f"  protocol      : {init.protocolVersion}")

            tools_resp = await session.list_tools()
            print(f"\n{len(tools_resp.tools)} tools registered:")
            for t in tools_resp.tools:
                print(f"  - {t.name}")

            try:
                resources_resp = await session.list_resources()
                print(f"\n{len(resources_resp.resources)} resources registered:")
                for r in resources_resp.resources:
                    print(f"  - {r.uri}: {r.name}")
            except Exception as e:
                print(f"\nlist_resources error (may be normal): {e}")

    print("\n[OK] MCP smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
