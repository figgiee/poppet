"""``cascadeur-bootstrap`` console command.

Writes cascadeur-mcp's Cascadeur-side bootstrap file to a stable location and prints the
single line to paste into Cascadeur's Python Console. Cascadeur 2026.2's built-in
script server starves its own background thread while the application is idle, so
this bootstrap (which installs a tiny PySide timer) is how cascadeur-mcp gets a
responsive server without a Cascadeur-side install.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from importlib import resources
from pathlib import Path

SOURCE_NAME = "cascadeur_bootstrap.py"
DEFAULT_PORT = 8765


def _default_target() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "cascadeur-mcp" / SOURCE_NAME


def _load_source() -> str:
    return resources.files("poppet_mcp").joinpath(SOURCE_NAME).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cascadeur-bootstrap",
        description="Write cascadeur-mcp's Cascadeur bootstrap and print the console line to run.",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="Preferred script-server port."
    )
    parser.add_argument("--write", default=None, help="Where to write the bootstrap file.")
    parser.add_argument(
        "--print-only", action="store_true", help="Only print the file path/line; do not write."
    )
    args = parser.parse_args(argv)

    target = Path(args.write) if args.write else _default_target()
    if not args.print_only:
        try:
            source = _load_source()
        except Exception as exc:  # pragma: no cover - packaging problem
            print(f"could not read the bundled bootstrap source: {exc}", file=sys.stderr)
            return 1
        if args.port != DEFAULT_PORT:
            source = source.replace(
                f"DEFAULT_PORT = {DEFAULT_PORT}", f"DEFAULT_PORT = {args.port}", 1
            )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
        except OSError as exc:
            fallback = Path(tempfile.gettempdir()) / "cascadeur-mcp" / SOURCE_NAME
            fallback.parent.mkdir(parents=True, exist_ok=True)
            fallback.write_text(source, encoding="utf-8")
            print(f"could not write {target} ({exc}); using {fallback}", file=sys.stderr)
            target = fallback
        print(f"cascadeur-mcp bootstrap written to: {target}")

    print()
    print("In Cascadeur 2026.2.3: Window -> Python Console, paste this line and press Execute:")
    print(f'exec(open(r"{target}").read())')
    print()
    print("Expected Event Log lines:")
    print("  [cascadeur-mcp] script server ready at http://127.0.0.1:<port>/mcp")
    print("  [cascadeur-mcp] interpreter keeper installed (10 ms); keep Cascadeur open")
    print()
    print("The bootstrap writes %LOCALAPPDATA%\\cascadeur-mcp\\server.json, so cascadeur-mcp")
    print("finds the port automatically. Re-run it after restarting Cascadeur.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
