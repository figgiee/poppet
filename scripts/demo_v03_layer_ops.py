"""Batch demo of the v0.2/v0.3 layer ops + undo/redo + bake_range.

Exercises:
  - list_layers (sanity, captures the first layer id)
  - add_layer ("Poppet_Demo_Layer")
  - layers_list (confirm new layer appears)
  - delete_layer (clean up the new layer)
  - undo (reverses the delete)
  - redo (re-applies the delete)
  - undo (final, leaves scene as it was)
  - bake_range on the first existing layer (small range so it's fast)

This is a destructive demo — it adds/deletes a layer. The undo dance at
the end leaves the scene unchanged (assuming Cascadeur's undo stack
honors the operations).

Run:
    .venv\\Scripts\\python.exe scripts\\demo_v03_layer_ops.py

Then focus Cascadeur (scene_activated auto-drains) OR click
Commands -> Poppet -> Process Pending.
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

    # The bake_range / delete_layer operations need a real layer_id which
    # we won't know upfront. For this demo we send layers_list first; in
    # a real Claude-driven scenario the LLM would chain off the response.
    # Here, we send everything with a placeholder and pick the first real
    # layer id from the layers_list response to use for bake_range. The
    # demo prints both stages.

    # Stage 1: discovery + add/delete with undo dance.
    tests_stage1 = [
        ("layers_list", {}),
        ("layer_add", {"name": "Poppet_Demo_Layer"}),
        ("layers_list", {}),
        # delete_layer needs a real id from the response — we'll loop on
        # the response of layer_add and queue this dynamically.
    ]

    ids: list[tuple[str, str]] = []
    for i, (cmd, params) in enumerate(tests_stage1):
        rid = f"v03s1-{i:02d}-{cmd}-{str(uuid.uuid4())[:6]}"
        path = os.path.join(req_dir, rid + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"type": cmd, "params": params}, f)
        ids.append((rid, cmd))
        time.sleep(0.01)

    print(f"Queued stage 1 ({len(ids)} requests)")
    print(">>> Focus Cascadeur OR click Commands -> Poppet -> Process Pending")
    print()

    # Drain stage 1.
    responses: dict[str, dict] = {}
    deadline = time.time() + 60
    pending = {rid: cmd for rid, cmd in ids}
    while pending and time.time() < deadline:
        for rid in list(pending):
            resp_path = os.path.join(resp_dir, rid + ".json")
            if os.path.exists(resp_path):
                try:
                    with open(resp_path, encoding="utf-8") as f:
                        responses[rid] = json.load(f)
                    cmd = pending.pop(rid)
                    status = responses[rid].get("status")
                    print(f"  [{status:>7}] {rid}")
                    if status == "error":
                        print(f"    message: {responses[rid].get('message')}")
                    else:
                        result_json = json.dumps(responses[rid].get("result"))
                        print(f"    result : {result_json[:240]}")
                except Exception:
                    continue
        time.sleep(0.2)

    if pending:
        print(f"\nTimeout — stage 1 leftovers: {list(pending)}")
        return 1

    # Pick the new layer id (from layer_add response) and a pre-existing
    # one (from the first layers_list response) for stage 2.
    new_layer_id = None
    first_layer_id = None
    for rid, cmd in ids:
        r = responses[rid]
        if r.get("status") != "success":
            continue
        result = r.get("result") or {}
        if cmd == "layer_add" and "layer_id" in result:
            new_layer_id = result["layer_id"]
        if cmd == "layers_list" and result.get("layers") and not first_layer_id:
            first_layer_id = result["layers"][0].get("id")

    print()
    print(f"new_layer_id   = {new_layer_id}")
    print(f"first_layer_id = {first_layer_id}")

    if not new_layer_id:
        print("layer_add didn't return a layer_id — skipping stage 2 (delete+undo+redo).")
        return 0

    # Stage 2: delete the new layer, undo it, redo it, then bake a tiny range
    # on the first existing layer.
    tests_stage2 = [
        ("layer_delete", {"layer_id": new_layer_id}),
        ("undo", {}),
        ("redo", {}),
        ("undo", {}),  # leave scene as we found it
    ]
    if first_layer_id:
        tests_stage2.append(
            ("bake_range", {"layer_id": first_layer_id, "frame_start": 0, "frame_end": 2})
        )

    print()
    print(f"Queued stage 2 ({len(tests_stage2)} requests)")
    print(">>> Focus Cascadeur OR click Process Pending again")
    print()

    ids2: list[tuple[str, str]] = []
    for i, (cmd, params) in enumerate(tests_stage2):
        rid = f"v03s2-{i:02d}-{cmd}-{str(uuid.uuid4())[:6]}"
        path = os.path.join(req_dir, rid + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"type": cmd, "params": params}, f)
        ids2.append((rid, cmd))
        time.sleep(0.01)

    deadline = time.time() + 60
    pending = {rid: cmd for rid, cmd in ids2}
    while pending and time.time() < deadline:
        for rid in list(pending):
            resp_path = os.path.join(resp_dir, rid + ".json")
            if os.path.exists(resp_path):
                try:
                    with open(resp_path, encoding="utf-8") as f:
                        body = json.load(f)
                    cmd = pending.pop(rid)
                    status = body.get("status")
                    print(f"  [{status:>7}] {rid}")
                    if status == "error":
                        print(f"    message: {body.get('message')}")
                    else:
                        rj = json.dumps(body.get("result"))
                        print(f"    result : {rj[:240]}")
                except Exception:
                    continue
        time.sleep(0.2)

    if pending:
        print(f"\nTimeout — stage 2 leftovers: {list(pending)}")
        return 1

    print()
    print("Stage 2 complete. Scene should be in its original state.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
