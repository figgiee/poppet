"""Benchmark the file-sync round-trip latency.

Sends N echo requests in a batch, prompts for one Process Pending drain,
times each request from "file written" to "response file read", reports
p50/p90/p99/min/max + total wall time.

Use this to track regressions after dispatcher changes. Typical baseline on
Windows 11 / SSD / Cascadeur 2025.3.3:
  - per-request p50: ~25ms
  - per-request p99: ~80ms
  - 50-request drain: ~1.2s wall

Run:
    .venv\\Scripts\\python.exe scripts\\benchmark.py [--count N]
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


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = max(0, min(len(sorted_v) - 1, int(round(len(sorted_v) * pct / 100.0)) - 1))
    return sorted_v[idx]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=50,
                    help="number of echo requests to send (default 50)")
    ap.add_argument("--timeout", type=int, default=60,
                    help="seconds to wait for drain (default 60)")
    args = ap.parse_args(argv)

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

    # Queue N echo requests.
    sent_at: dict[str, float] = {}
    print(f"Queuing {args.count} echo requests...")
    queue_start = time.perf_counter()
    for i in range(args.count):
        rid = f"bench-{i:04d}-{str(uuid.uuid4())[:6]}"
        path = os.path.join(req_dir, rid + ".json")
        body = {"type": "echo", "params": {"i": i, "size": 256, "payload": "x" * 256}}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(body, f)
        os.replace(tmp, path)
        sent_at[rid] = time.perf_counter()
    queue_end = time.perf_counter()
    queue_ms = (queue_end - queue_start) * 1000

    print(f"Queue write time: {queue_ms:.1f}ms ({queue_ms / args.count:.2f}ms per request)")
    print()
    print(">>> Focus Cascadeur OR click Commands -> Poppet -> Process Pending")
    print()

    latencies: list[float] = []
    deadline = time.time() + args.timeout
    pending = set(sent_at)
    while pending and time.time() < deadline:
        for rid in list(pending):
            resp_path = os.path.join(resp_dir, rid + ".json")
            if os.path.exists(resp_path):
                try:
                    with open(resp_path, encoding="utf-8") as f:
                        json.load(f)
                except Exception:
                    continue
                received_at = time.perf_counter()
                latencies.append((received_at - sent_at[rid]) * 1000)
                pending.discard(rid)
                try:
                    os.remove(resp_path)
                except Exception:
                    pass
        time.sleep(0.01)

    if pending:
        print(f"Timeout — {len(pending)} requests un-drained.")
        return 1

    total_wall = max(latencies)
    print()
    print(f"Drained {len(latencies)} requests:")
    print(f"  min   : {min(latencies):.2f} ms")
    print(f"  p50   : {percentile(latencies, 50):.2f} ms")
    print(f"  p90   : {percentile(latencies, 90):.2f} ms")
    print(f"  p99   : {percentile(latencies, 99):.2f} ms")
    print(f"  max   : {max(latencies):.2f} ms")
    print(f"  total : {total_wall:.0f} ms (wall)")
    print(f"  rate  : {len(latencies) / (total_wall / 1000):.1f} req/s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
