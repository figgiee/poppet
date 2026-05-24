"""Diagnostic for a new Poppet install. Run AFTER install.ps1 / install.sh.

Checks:
  1. The poppet/ command package is in user_scripts and has the expected files.
  2. The poppet_events/ events package is in user_scripts (with the right
     subpackage shape: scene_activated/poppet_drain.py).
  3. Cascadeur's settings.json has `Python.Path` extended, `Python.Commands`
     contains "poppet", and `Python.Events` contains "poppet_events".
  4. The MCP server entry point is importable in the current Python env.
  5. The %LOCALAPPDATA%\\poppet-mcp\\{requests,responses}\\ dirs exist (or
     get created on first call).

Output is a checklist with [OK] / [FAIL] / [WARN] markers. Exit code is 0
if every check passes, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import sys

CHECK_OK = "[OK]  "
CHECK_FAIL = "[FAIL]"
CHECK_WARN = "[WARN]"


def _cascadeur_user_scripts() -> str:
    if sys.platform == "win32":
        return os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "Nekki Limited",
            "Cascadeur",
            "user_scripts",
        )
    # macOS uses ~/Library/Application Support/Cascadeur per Nekki, Linux ~/.local/share/Cascadeur.
    # We won't probe — only check this on Windows where the install script targets.
    return ""


def _settings_path() -> str:
    if sys.platform == "win32":
        return os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "Nekki Limited",
            "Cascadeur",
            "settings.json",
        )
    return ""


def _poppet_queue_dir() -> str:
    if sys.platform == "win32":
        return os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "poppet-mcp",
        )
    return os.path.expanduser("~/.local/share/poppet-mcp")


def main() -> int:
    failures = 0
    warnings = 0

    print("Poppet install diagnostic")
    print("=" * 60)

    # 1. Cascadeur-side install
    user_scripts = _cascadeur_user_scripts()
    if not user_scripts:
        print(f"{CHECK_WARN} Non-Windows platform — Cascadeur-side checks skipped.")
        warnings += 1
    else:
        poppet_dir = os.path.join(user_scripts, "poppet")
        events_dir = os.path.join(user_scripts, "poppet_events")

        if os.path.isdir(poppet_dir):
            print(f"{CHECK_OK} cascadeur_side/poppet/ installed at {poppet_dir}")
            for required in ("__init__.py", "_dispatchers.py", "process_pending.py", "_paths.py"):
                p = os.path.join(poppet_dir, required)
                if os.path.isfile(p):
                    print(f"        + {required}")
                else:
                    print(f"{CHECK_FAIL}   missing: {required}")
                    failures += 1
        else:
            print(f"{CHECK_FAIL} cascadeur_side/poppet/ NOT installed at {poppet_dir}")
            print("        Re-run scripts/install.ps1.")
            failures += 1

        if os.path.isdir(events_dir):
            print(f"{CHECK_OK} cascadeur_side/poppet_events/ installed at {events_dir}")
            drain_path = os.path.join(events_dir, "scene_activated", "poppet_drain.py")
            if os.path.isfile(drain_path):
                print("        + scene_activated/poppet_drain.py")
            else:
                print(f"{CHECK_FAIL}   missing: scene_activated/poppet_drain.py")
                failures += 1
        else:
            print(
                f"{CHECK_WARN} cascadeur_side/poppet_events/ NOT installed — "
                "auto-drain unavailable."
            )
            print("         Re-run scripts/install.ps1 to enable focus-driven drain.")
            warnings += 1

    # 2. settings.json
    settings_path = _settings_path()
    if not settings_path:
        pass
    elif not os.path.isfile(settings_path):
        print(f"{CHECK_FAIL} settings.json not found at {settings_path}")
        print("        Has Cascadeur been launched at least once?")
        failures += 1
    else:
        try:
            with open(settings_path, encoding="utf-8") as f:
                settings = json.load(f)
        except Exception as e:
            print(f"{CHECK_FAIL} settings.json unreadable: {e}")
            failures += 1
        else:
            paths = settings.get("Python", {}).get("Path", []) or []
            cmds = settings.get("Python", {}).get("Commands", []) or []
            evs = settings.get("Python", {}).get("Events", []) or []

            if user_scripts and user_scripts in paths:
                print(f"{CHECK_OK} settings.json Python.Path includes user_scripts")
            else:
                print(f"{CHECK_FAIL} settings.json Python.Path missing user_scripts entry")
                failures += 1

            if "poppet" in cmds:
                print(f"{CHECK_OK} settings.json Python.Commands includes 'poppet'")
            else:
                print(f"{CHECK_FAIL} settings.json Python.Commands missing 'poppet'")
                failures += 1

            if "poppet_events" in evs:
                print(f"{CHECK_OK} settings.json Python.Events includes 'poppet_events'")
            else:
                print(
                    f"{CHECK_WARN} settings.json Python.Events missing 'poppet_events' "
                    "— auto-drain off"
                )
                warnings += 1

            if settings.get("ScriptsDir") not in ("", None):
                sd_value = settings.get("ScriptsDir")
                print(
                    f"{CHECK_WARN} settings.json ScriptsDir is set to {sd_value!r} — "
                    "this REPLACES the bundled commands dir and FATAL-crashes Cascadeur."
                )
                warnings += 1

    # 3. MCP server importability
    try:
        from poppet_mcp.server import main as _server_main  # noqa: F401

        py_ver = sys.version.split()[0]
        print(f"{CHECK_OK} poppet_mcp.server importable in this Python env ({py_ver})")
    except Exception as e:
        print(f"{CHECK_FAIL} poppet_mcp.server NOT importable: {e}")
        print("        Did you run `pip install -e .` (or `uvx poppet-mcp`)?")
        failures += 1

    # 4. Queue dirs
    qd = _poppet_queue_dir()
    req = os.path.join(qd, "requests")
    resp = os.path.join(qd, "responses")
    for name, p in (("requests", req), ("responses", resp)):
        if os.path.isdir(p):
            print(f"{CHECK_OK} queue dir exists: {p}")
        else:
            print(f"{CHECK_WARN} queue dir missing: {p} (will be created on first call)")
            warnings += 1

    print("=" * 60)
    print(f"Summary: failures={failures}, warnings={warnings}")
    if failures:
        print("Fix failures before driving Cascadeur from Claude.")
        return 1
    if warnings:
        print("Install works; warnings indicate degraded modes.")
    else:
        print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
