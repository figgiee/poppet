"""End-to-end MCP-client demo of the Poppet -> Cascadeur integration.

Spawns the poppet-mcp server as a subprocess (stdio MCP transport), connects
via the official MCP Python SDK, and walks through the spec §4 sparse-control
loop: scene_info -> set sparse keys -> AutoPosing -> AutoPhysics -> read telemetry
-> export FBX.

Each MCP tool call writes a request file and blocks waiting for the response.
Cascadeur drains the request queue when the user clicks
'Commands -> Poppet -> Process Pending'. For an interactive run, click between
each MCP call (the script will print "DRAIN NOW" prompts).

For a NON-interactive batch run (one click at the very end), use
demo_batch_spec4.py instead.

Prerequisites:
  1. Cascadeur 2025.3.3 is running with the Poppet command package installed
     (run scripts/install.ps1 first) AND with a real character scene loaded
     (e.g. Cascy.casc).
  2. `pip install -e .` has installed poppet-mcp + mcp + pydantic in this env.
"""

from __future__ import annotations

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def banner(msg: str) -> None:
    print()
    print("=" * 70)
    print(msg)
    print("=" * 70)


def drain_prompt(label: str) -> None:
    print()
    print(">>> CLICK 'Commands -> Poppet -> Process Pending' in Cascadeur NOW")
    print(f">>> (draining request for: {label})")


async def run_demo() -> int:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    server_cmd = [sys.executable, "-m", "poppet_mcp.server"]
    server_params = StdioServerParameters(
        command=server_cmd[0],
        args=server_cmd[1:],
        env=os.environ.copy(),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"MCP server up. {len(tools.tools)} tools registered:")
            for t in tools.tools:
                print(f"  - {t.name}")

            banner("STEP 1: get_scene_info")
            drain_prompt("get_scene_info")
            r = await session.call_tool("get_scene_info", {})
            print(r.content[0].text if r.content else r)

            banner("STEP 2: list_objects (Box controllers)")
            drain_prompt("list_objects")
            r = await session.call_tool("list_objects", {"name_contains": "Box"})
            print((r.content[0].text if r.content else str(r))[:600])

            banner("STEP 3: set sparse keys — pelvis up at frame 0")
            drain_prompt("set_controller_position pelvis_Box (0,0,30)")
            r = await session.call_tool(
                "set_controller_position",
                {
                    "controller_id": "pelvis_Box",
                    "frame": 0,
                    "x": 0,
                    "y": 0,
                    "z": 30,
                },
            )
            print(r.content[0].text if r.content else r)

            banner("STEP 4: select feet for AutoPosing anchors")
            drain_prompt("set_selection foot_Box_l + foot_Box_r")
            r = await session.call_tool(
                "set_selection",
                {
                    "object_names": ["foot_Box_l", "foot_Box_r"],
                },
            )
            print(r.content[0].text if r.content else r)

            banner("STEP 5: run AutoPosing")
            drain_prompt("run_autoposing")
            r = await session.call_tool("run_autoposing", {})
            print(r.content[0].text if r.content else r)

            banner("STEP 6: run AutoPhysics (short timeout)")
            drain_prompt("run_autophysics")
            r = await session.call_tool("run_autophysics", {"timeout_sec": 5})
            print(r.content[0].text if r.content else r)

            banner("STEP 7: read telemetry")
            drain_prompt("read_telemetry")
            r = await session.call_tool(
                "read_telemetry",
                {
                    "controller_ids": ["pelvis_Box", "foot_Box_l", "foot_Box_r"],
                    "frames": [0],
                },
            )
            print((r.content[0].text if r.content else str(r))[:800])

            banner("STEP 8: export FBX")
            out_path = os.path.join(repo_root, "tmp", "poppet_demo.fbx")
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            drain_prompt(f"export_fbx -> {out_path}")
            r = await session.call_tool("export_fbx", {"path": out_path})
            print(r.content[0].text if r.content else r)

            if os.path.exists(out_path):
                size = os.path.getsize(out_path)
                banner(f"[OK] FBX file written: {out_path} ({size} bytes)")
                return 0
            else:
                banner(f"[XX] FBX file NOT found at {out_path}")
                return 2

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_demo()))
