"""Batch-style spec §4 demo — writes ALL requests upfront, drains once.

Works around the manual-drain limitation by writing request files directly
(bypassing the MCP server's per-call polling) and then prompting for ONE
'Process Pending' click that drains everything. Reads all responses.

This is the realistic "Claude proposes a batch of edits, user applies them
in one click" workflow that the file-sync architecture enables.

Use scripts/demo_mcp_client.py for the per-call version that exercises the
actual MCP server stdio transport.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid


def base_dir() -> str:
    if sys.platform == "win32":
        return os.path.join(os.environ["LOCALAPPDATA"], "poppet-mcp")
    return os.path.expanduser("~/.local/share/poppet-mcp")


def main() -> int:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fbx_out = os.path.join(repo_root, "tmp", "poppet_demo.fbx").replace("\\", "/")
    os.makedirs(os.path.dirname(fbx_out), exist_ok=True)

    base = base_dir()
    req_dir = os.path.join(base, "requests")
    resp_dir = os.path.join(base, "responses")
    os.makedirs(req_dir, exist_ok=True)
    os.makedirs(resp_dir, exist_ok=True)

    # Clean stale responses from prior runs.
    for f in os.listdir(resp_dir):
        if f.endswith(".json"):
            try:
                os.remove(os.path.join(resp_dir, f))
            except Exception:
                pass

    # Spec §4 sparse-control sequence.
    tests = [
        ("scene_info", {}),
        ("objects_list", {"name_contains": "Box"}),
        (
            "set_controller_position",
            {"controller_id": "pelvis_Box", "frame": 0, "x": 0, "y": 0, "z": 30},
        ),
        ("selection_set", {"object_names": ["foot_Box_l", "foot_Box_r"]}),
        ("autopose_run", {}),
        ("autophysics_run", {"timeout_sec": 5}),
        (
            "telemetry_read",
            {"controller_ids": ["pelvis_Box", "foot_Box_l", "foot_Box_r"], "frames": [0]},
        ),
        ("fbx_export", {"path": fbx_out}),
    ]

    ids: list[tuple[str, str]] = []
    for i, (cmd, params) in enumerate(tests):
        rid = f"{i:02d}-{cmd}-{str(uuid.uuid4())[:6]}"
        path = os.path.join(req_dir, rid + ".json")
        # set_controller_position is an MCP-level alias; the dispatcher
        # expects keyframe_set with a transform dict. Map it here for the
        # batch demo so we don't need to route through the MCP server.
        if cmd == "set_controller_position":
            cmd_eff = "keyframe_set"
            p = {
                "controller_id": params["controller_id"],
                "frame": params["frame"],
                "position": [params["x"], params["y"], params["z"]],
            }
        else:
            cmd_eff = cmd
            p = params
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"type": cmd_eff, "params": p}, f)
        ids.append((rid, cmd_eff))
        time.sleep(0.01)

    print(f"Queued {len(ids)} requests in {req_dir}")
    print()
    print(">>> In Cascadeur: click Commands -> Poppet -> Process Pending <<<")
    print(">>> Waiting for all responses (60s timeout)...")
    print()

    deadline = time.time() + 60
    pending = {rid: cmd for rid, cmd in ids}
    while pending and time.time() < deadline:
        for rid in list(pending):
            resp_path = os.path.join(resp_dir, rid + ".json")
            if os.path.exists(resp_path):
                try:
                    with open(resp_path, encoding="utf-8") as f:
                        resp = json.load(f)
                except Exception:
                    continue
                cmd = pending.pop(rid)
                status = resp.get("status")
                print(f"  [{status:>7}] {rid}")
                if status == "error":
                    print(f"    message: {resp.get('message')}")
                else:
                    result = resp.get("result")
                    summary = json.dumps(result) if result else ""
                    print(f"    result : {summary[:200]}")
        time.sleep(0.2)

    if pending:
        print()
        print(f"Timeout — {len(pending)} requests un-drained:")
        for rid, cmd in pending.items():
            print(f"  - {rid} ({cmd})")
        return 1

    print()
    print("All requests drained.")
    if os.path.exists(fbx_out):
        print(f"[OK] FBX exported to {fbx_out} ({os.path.getsize(fbx_out)} bytes)")
        return 0
    else:
        print(f"[!!]  FBX export reported success but no file at {fbx_out}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
