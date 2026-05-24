"""Manual smoke test — connect to the Poppet server and exchange a few messages.

Run this from outside Cascadeur once 'Commands -> Poppet -> Start Server' is
running. Validates the wire format end-to-end without going through MCP.

Usage:
    python scripts/poc_client.py
    python scripts/poc_client.py --port 53145
    python scripts/poc_client.py --exec "csc.app.get_application().current_scene()"
"""

from __future__ import annotations

import argparse
import json
import socket
import sys

HEADER_LEN = 64


def encode(message: dict) -> bytes:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    header = str(len(body)).encode("ascii")
    header += b" " * (HEADER_LEN - len(header))
    return header + body


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("peer closed mid-message")
        buf += chunk
    return buf


def send_recv(sock: socket.socket, message: dict) -> dict:
    sock.sendall(encode(message))
    header = recv_exact(sock, HEADER_LEN).decode("ascii").strip()
    length = int(header)
    body = recv_exact(sock, length).decode("utf-8")
    return json.loads(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=53145)
    ap.add_argument(
        "--exec",
        dest="exec_code",
        help="Run arbitrary csc Python via exec_csc and print the result.",
    )
    args = ap.parse_args()

    s = socket.socket()
    s.settimeout(10)
    try:
        s.connect((args.host, args.port))
    except OSError as e:
        print(f"connect failed: {e}", file=sys.stderr)
        print(
            "Is Cascadeur running with 'Commands -> Poppet -> Start Server' active?",
            file=sys.stderr,
        )
        return 1

    if args.exec_code:
        r = send_recv(s, {"type": "exec_csc", "params": {"code": args.exec_code}})
        print(json.dumps(r, indent=2))
        return 0 if r.get("status") == "success" else 2

    # Default: walk through echo + scene_info + call_action(Scene.Undo).
    print("=== echo ===")
    print(
        json.dumps(send_recv(s, {"type": "echo", "params": {"hello": "from poc_client"}}), indent=2)
    )
    print()
    print("=== scene_info ===")
    print(json.dumps(send_recv(s, {"type": "scene_info", "params": {}}), indent=2))
    print()
    print("=== call_action: Scene.Undo (will no-op if nothing to undo) ===")
    print(
        json.dumps(
            send_recv(s, {"type": "call_action", "params": {"action_id": "Scene.Undo"}}), indent=2
        )
    )
    s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
