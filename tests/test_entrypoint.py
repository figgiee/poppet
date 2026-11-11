"""``python -m poppet_mcp.server`` must serve the pipeline tools, not just the core set."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_module_entry_point_serves_pipeline_tools():
    async def names():
        env = {**os.environ, "PYTHONPATH": SRC}
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "poppet_mcp.server"], env=env
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return {t.name for t in (await session.list_tools()).tools}

    tools = asyncio.run(names())
    for name in ("cascadeur_preflight", "block_poses", "render_frames", "lint_take", "retime_take"):
        assert name in tools
