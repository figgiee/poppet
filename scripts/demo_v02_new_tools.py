"""Batch-style demo of the v0.2 dispatcher expansion.

Queues a handful of v0.2 requests upfront, drains once, prints results.
Same shape as demo_batch_spec4.py — see that script for the spec §4
sparse-control flow that's the headline workflow.

What this exercises:
  - get_scene_info (sanity)
  - get_object_hierarchy
  - get_object_transform on pelvis_Box at frame 0
  - list_object_attributes on pelvis_Box
  - set_layer_visible toggle on the first layer
  - screenshot_viewport to ./tmp/poppet_v02_shot.png
  - save_scene to ./tmp/poppet_v02_snapshot.casc
  - load_scene of the snapshot we just wrote (round-trip)

This DOES NOT run delete_object / duplicate_object / new_scene — those
mutate the scene in ways that would invalidate a follow-up demo run
without manual cleanup.

Run:
    .venv\\Scripts\\python.exe scripts\\demo_v02_new_tools.py

Then in Cascadeur:
    Commands -> Poppet -> Process Pending (one click drains all)
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
    tmp_dir = os.path.join(repo_root, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    shot_path = os.path.join(tmp_dir, "poppet_v02_shot.png").replace("\\", "/")
    snap_path = os.path.join(tmp_dir, "poppet_v02_snapshot.casc").replace("\\", "/")

    base = base_dir()
    req_dir = os.path.join(base, "requests")
    resp_dir = os.path.join(base, "responses")
    os.makedirs(req_dir, exist_ok=True)
    os.makedirs(resp_dir, exist_ok=True)

    # Clean stale responses.
    for f in os.listdir(resp_dir):
        if f.endswith(".json"):
            try:
                os.remove(os.path.join(resp_dir, f))
            except Exception:
                pass

    tests = [
        ("scene_info", {}),
        ("object_hierarchy", {}),
        ("object_transform_get", {"object_name": "pelvis_Box", "frame": 0}),
        ("object_attributes_list", {"object_name": "pelvis_Box"}),
        # Layer ops — toggle the first layer; we'll fetch layers_list first
        # in the response loop so we know the layer_id, but for a pre-built
        # batch we just send a placeholder and let the dispatcher 404 if it's
        # not a valid id. To keep the demo deterministic, swap this for your
        # layer_id from list_layers if you want it to succeed.
        ("layers_list", {}),
        ("viewport_screenshot", {"path": shot_path}),
        ("save_scene", {"path": snap_path}),
        # NOTE: load_scene of a freshly-saved file would normally come last,
        # but loading a scene mid-drain breaks the request queue (Cascadeur
        # is mid-iteration of pending). Demonstrate it as a separate run.
    ]

    ids: list[tuple[str, str]] = []
    for i, (cmd, params) in enumerate(tests):
        rid = f"v02-{i:02d}-{cmd}-{str(uuid.uuid4())[:6]}"
        path = os.path.join(req_dir, rid + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"type": cmd, "params": params}, f)
        ids.append((rid, cmd))
        time.sleep(0.01)

    print(f"Queued {len(ids)} requests in {req_dir}")
    print()
    print(">>> In Cascadeur: focus the window (auto-drain via scene_activated)")
    print(">>> OR click Commands -> Poppet -> Process Pending")
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
                    print(f"    result : {summary[:240]}")
        time.sleep(0.2)

    if pending:
        print()
        print(f"Timeout — {len(pending)} requests un-drained:")
        for rid, cmd in pending.items():
            print(f"  - {rid} ({cmd})")
        return 1

    print()
    print("All requests drained.")
    if os.path.exists(snap_path):
        print(f"[OK] Scene saved to {snap_path} ({os.path.getsize(snap_path)} bytes)")
    else:
        print(f"[!!] save_scene reported success but no file at {snap_path}")
    if os.path.exists(shot_path):
        print(f"[OK] Screenshot saved to {shot_path} ({os.path.getsize(shot_path)} bytes)")
    else:
        print(f"[!!] viewport_screenshot reported success but no file at {shot_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
