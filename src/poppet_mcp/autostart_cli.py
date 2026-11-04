"""Optional zero-touch autostart for Cascadeur 2026.2.

``cascadeur-bootstrap`` needs one console paste per Cascadeur session. This module
removes that step for people who prefer a Cascadeur-side add-on: it installs a tiny
``user_scripts`` event package (``poppet_autostart``) that Cascadeur runs itself at
application start, which in turn starts the built-in MCP script server, installs the
interpreter keeper, and records the chosen port — no console, no menu.

The add-on is **optional**: the core integration stays install-free and works with the
console bootstrap. It writes only:

- ``<user_scripts>/poppet_autostart/`` (handler package, ~3 small files),
- one entry in ``settings.json`` ``Python.Events`` (backed up first),
- the standard ``%LOCALAPPDATA%\\cascadeur-mcp\\cascadeur_bootstrap.py`` file.

Uninstall with ``cascadeur-autostart --uninstall``; restart Cascadeur afterwards.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from importlib import resources
from pathlib import Path

PACKAGE_NAME = "poppet_autostart"
DEFAULT_PORT = 8765
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA") or str(Path.home())


def _default_user_scripts() -> Path:
    return Path(_LOCALAPPDATA) / "Nekki Limited" / "Cascadeur" / "user_scripts"


def _default_settings() -> Path:
    return Path(_LOCALAPPDATA) / "Nekki Limited" / "Cascadeur" / "settings.json"


def _default_bootstrap() -> Path:
    return Path(_LOCALAPPDATA) / "cascadeur-mcp" / "cascadeur_bootstrap.py"


def _user_scripts(explicit: str | None, settings_path: Path) -> Path:
    if explicit:
        return Path(explicit)
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        for candidate in data.get("Python", {}).get("Path", []) or []:
            path = Path(candidate)
            if path.exists():
                return path
    except Exception:
        pass
    return _default_user_scripts()


_HANDLER_HEADER = '''"""cascadeur-mcp autostart: start the built-in MCP script server and keeper.

Installed by ``cascadeur-autostart --install``. Cascadeur runs this event handler on
its Qt main thread; it executes the standard bootstrap file written by
``cascadeur-bootstrap`` and does not modify the application itself.
"""

import csc  # noqa: F401  (Cascadeur convention: every event handler imports csc)
import os
import traceback

BOOTSTRAP = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
    "cascadeur-mcp",
    "cascadeur_bootstrap.py",
)


def _run_bootstrap():
    with open(BOOTSTRAP, encoding="utf-8") as handle:
        source = handle.read()
    namespace = {"__name__": "__cascadeur_mcp_autostart__", "__file__": BOOTSTRAP}
    exec(compile(source, BOOTSTRAP, "exec"), namespace)
'''

_APPLICATION_STARTED = (
    _HANDLER_HEADER
    + """

def run(scene=None):
    try:
        _run_bootstrap()
    except Exception:
        print("[cascadeur-mcp] autostart failed; run `cascadeur-bootstrap` once instead")
        traceback.print_exc()
"""
)

_SCENE_OPENED = (
    _HANDLER_HEADER
    + """

def run(scene=None):
    # Retry only when the server never came up (application_started can fire before
    # the embedded Python environment is fully ready on some builds).
    try:
        import scripts.mcp.script_server.server as server

        if server.is_running():
            return
    except Exception:
        pass
    try:
        _run_bootstrap()
        try:
            if scene is not None:
                scene.info("[cascadeur-mcp] autostart: script server ready")
        except Exception:
            pass
    except Exception:
        print("[cascadeur-mcp] autostart retry failed")
        traceback.print_exc()
"""
)


# 2026.2.3 dispatches user event handlers for scene events (a startup probe showed
# scene_created + scene_activated firing, but application_started never firing), so the
# bootstrap retry is installed on every scene event that can occur before a user acts.
_RETRY_EVENTS = ("scene_created", "scene_opened", "scene_activated")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _bootstrap_source(port: int) -> str:
    source = (
        resources.files("poppet_mcp").joinpath("cascadeur_bootstrap.py").read_text(encoding="utf-8")
    )
    if port != DEFAULT_PORT:
        source = source.replace(f"DEFAULT_PORT = {DEFAULT_PORT}", f"DEFAULT_PORT = {port}", 1)
    return source


def _read_settings(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        raise RuntimeError(f"could not parse {path}: {exc}") from exc


def _write_settings(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")


def install(
    *,
    user_scripts: Path,
    settings_path: Path,
    bootstrap_path: Path,
    port: int = DEFAULT_PORT,
) -> dict:
    """Write the autostart package, bootstrap file and settings entry."""
    package_dir = user_scripts / PACKAGE_NAME
    _write(
        package_dir / "__init__.py",
        '"""cascadeur-mcp autostart package (installed by cascadeur-autostart)."""\n',
    )
    _write(package_dir / "application_started" / "__init__.py", "")
    _write(package_dir / "application_started" / "autostart.py", _APPLICATION_STARTED)
    for event in _RETRY_EVENTS:
        _write(package_dir / event / "__init__.py", "")
        _write(package_dir / event / "autostart_retry.py", _SCENE_OPENED)

    _write(bootstrap_path, _bootstrap_source(port))

    settings = _read_settings(settings_path)
    python = settings.setdefault("Python", {})
    events = python.setdefault("Events", [])
    added_event = False
    if PACKAGE_NAME not in events:
        events.append(PACKAGE_NAME)
        added_event = True
    if added_event:
        backup = settings_path.with_name(settings_path.name + ".cascadeur-mcp.backup")
        if not backup.exists() and settings_path.exists():
            backup.write_text(settings_path.read_text(encoding="utf-8-sig"), encoding="utf-8")
        _write_settings(settings_path, settings)

    return {
        "installed": True,
        "package": str(package_dir),
        "bootstrap": str(bootstrap_path),
        "settings": str(settings_path),
        "settings_event_added": added_event,
        "port": port,
    }


def uninstall(*, user_scripts: Path, settings_path: Path) -> dict:
    package_dir = user_scripts / PACKAGE_NAME
    removed = False
    if package_dir.exists():
        shutil.rmtree(package_dir)
        removed = True

    settings = _read_settings(settings_path)
    python = settings.get("Python", {})
    events = python.get("Events", [])
    if PACKAGE_NAME in events:
        events.remove(PACKAGE_NAME)
        _write_settings(settings_path, settings)

    return {"uninstalled": True, "package_removed": removed, "settings": str(settings_path)}


def status(*, user_scripts: Path, settings_path: Path, bootstrap_path: Path) -> dict:
    package_dir = user_scripts / PACKAGE_NAME
    try:
        events = _read_settings(settings_path).get("Python", {}).get("Events", [])
    except Exception:
        events = []
    return {
        "installed": package_dir.is_dir() and PACKAGE_NAME in events,
        "package_dir": str(package_dir),
        "package_exists": package_dir.is_dir(),
        "settings_entry": PACKAGE_NAME in events,
        "bootstrap": str(bootstrap_path),
        "bootstrap_exists": bootstrap_path.is_file(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cascadeur-autostart",
        description=(
            "Optional zero-touch autostart for cascadeur-mcp: installs a small "
            "Cascadeur user_scripts event package that starts the script server and "
            "keeper at application start."
        ),
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--install", action="store_true", help="Install the autostart (default).")
    action.add_argument("--uninstall", action="store_true", help="Remove the autostart.")
    action.add_argument("--status", action="store_true", help="Show installed status.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Preferred server port.")
    parser.add_argument(
        "--user-scripts", default=None, help="Override Cascadeur's user_scripts dir."
    )
    parser.add_argument("--settings", default=None, help="Override Cascadeur settings.json path.")
    parser.add_argument("--bootstrap", default=None, help="Override the bootstrap file path.")
    args = parser.parse_args(argv)

    settings_path = Path(args.settings) if args.settings else _default_settings()
    user_scripts = _user_scripts(args.user_scripts, settings_path)
    bootstrap_path = Path(args.bootstrap) if args.bootstrap else _default_bootstrap()

    try:
        if args.status:
            result = status(
                user_scripts=user_scripts,
                settings_path=settings_path,
                bootstrap_path=bootstrap_path,
            )
            print(json.dumps(result, indent=2))
            return 0 if result["installed"] else 1
        if args.uninstall:
            print(
                json.dumps(
                    uninstall(user_scripts=user_scripts, settings_path=settings_path), indent=2
                )
            )
            print("Restart Cascadeur to unload the event package.")
            return 0
        result = install(
            user_scripts=user_scripts,
            settings_path=settings_path,
            bootstrap_path=bootstrap_path,
            port=args.port,
        )
        print(json.dumps(result, indent=2))
        print()
        print("Installed. Restart Cascadeur: the server + keeper will start automatically")
        print("on launch (Event Log: '[cascadeur-mcp] script server ready at ...').")
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI should report, not traceback
        print(f"cascadeur-autostart failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
