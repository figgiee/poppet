"""Live end-to-end check against a running Cascadeur 2026.2+.

Prerequisites:
  1. Cascadeur 2026.2.3 is running with a scene open.
  2. **Scripts -> MCP -> Start script server** has been clicked (Cascadeur's
     Event Log should print ``[Cascadeur MCP] listening at http://127.0.0.1:8765/mcp``).
  3. A compatible port is free (see docs/TROUBLESHOOTING.md if another app owns
     8765; start the server on another port and pass ``--url``).

Usage::

    python scripts/live_check.py
    python scripts/live_check.py --url http://127.0.0.1:8766

Exits non-zero on the first failure; prints a readable trace per step.
"""

from __future__ import annotations

import argparse
import json
import sys

from poppet_mcp.cascadeur_connection import CascadeurConnection, CascadeurConnectionError


def _summarize(result: object, limit: int = 240) -> str:
    """Compact one-line view of a tool result for console output."""
    try:
        text = json.dumps(result, default=str, ensure_ascii=False)
    except Exception:  # pragma: no cover - defensive only
        text = repr(result)
    return text if len(text) <= limit else text[:limit] + "..."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify cascadeur-mcp against a running Cascadeur."
    )
    parser.add_argument(
        "--url", default=None, help="Script-server URL (default: POPPET_URL or 127.0.0.1:8765)"
    )
    args = parser.parse_args(argv)

    connection = CascadeurConnection(url=args.url)
    print(f"cascadeur-mcp live check -> {connection.url}\n")

    checks: list[tuple[str, callable]] = [
        ("health", connection.health),
        ("ping", lambda: connection.request("ping")),
        ("scene_info", lambda: connection.request("scene_info")),
        ("list_objects", lambda: connection.request("objects_list", {"name_contains": None})),
        ("list_layers", lambda: connection.request("layers_list")),
        ("selection_get", lambda: connection.request("selection_get")),
        ("frame_get", lambda: connection.request("frame_get")),
        (
            "schema_get",
            lambda: {"schema_json_size": connection.request("schema_get").get("schema_json_size")},
        ),
    ]

    for name, fn in checks:
        try:
            result = fn()
        except CascadeurConnectionError as exc:
            print(f"FAIL {name}\n{exc}")
            if name == "health":
                print(
                    "\nIs Cascadeur running with the script server started?\n"
                    "  In Cascadeur: Scripts -> MCP -> Start script server"
                )
            return 1
        print(f"PASS {name}: {_summarize(result)}")

    print(f"\nAll {len(checks)} live checks passed against {connection.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
