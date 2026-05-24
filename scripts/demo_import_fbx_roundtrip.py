"""Round-trip demo for import_fbx — exports the scene, then re-imports it.

Sequence:
  1. scene_info (baseline)
  2. export_fbx -> tmp/poppet_roundtrip.fbx
  3. scene_info (still baseline)
  4. import_fbx target=animation with the file we just exported
  5. scene_info (should still report a populated scene)

This verifies the import_fbx code path against a known-good FBX
(the one Poppet itself just wrote). If anything goes wrong, the error
response will surface in the demo output.

Caveat: import_fbx target=scene REPLACES the scene contents. We use
target=animation so we layer the exported animation back over the
current rig without nuking it. If you want full-scene import as a
fresh state, run with: --target scene

Run:
    .venv\\Scripts\\python.exe scripts\\demo_import_fbx_roundtrip.py [--target {scene,animation}]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid


def base_dir() -> str:
    if sys.platform == "win32":
        return os.path.join(os.environ["LOCALAPPDATA"], "poppet-mcp")
    return os.path.expanduser("~/.local/share/poppet-mcp")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=("scene", "animation"), default="animation")
    args = ap.parse_args(argv)

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmp_dir = os.path.join(repo_root, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    fbx_path = os.path.join(tmp_dir, "poppet_roundtrip.fbx").replace("\\", "/")

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
        ("fbx_export", {"path": fbx_path}),
        ("scene_info", {}),
        ("fbx_import", {"path": fbx_path, "target": args.target}),
        ("scene_info", {}),
    ]

    ids: list[tuple[str, str]] = []
    for i, (cmd, params) in enumerate(tests):
        rid = f"fbxrt-{i:02d}-{cmd}-{str(uuid.uuid4())[:6]}"
        path = os.path.join(req_dir, rid + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"type": cmd, "params": params}, f)
        ids.append((rid, cmd))
        time.sleep(0.01)

    print(f"Queued {len(ids)} requests for FBX round-trip (target={args.target!r})")
    print(">>> Focus Cascadeur OR click Commands -> Poppet -> Process Pending")
    print()

    deadline = time.time() + 90  # FBX export + import can take time
    pending = {rid: cmd for rid, cmd in ids}
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
                        print(f"    result : {rj[:280]}")
                except Exception:
                    continue
        time.sleep(0.2)

    if pending:
        print(f"\nTimeout — leftovers: {list(pending)}")
        return 1

    print()
    if os.path.exists(fbx_path):
        size = os.path.getsize(fbx_path)
        print(f"[OK] FBX round-trip file: {fbx_path} ({size} bytes)")
        return 0 if size > 0 else 2
    else:
        print(f"[!!] No FBX file at {fbx_path}")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
