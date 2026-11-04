"""Independent re-validation of the public Cascadeur-MCP landscape.

Clones each public implementation at its current default branch, records the exact
commit, and statically inventories its tool registrations and architecture markers
(native 8765 usage, Cascadeur-side bridge, console/bootstrap steps, safety features).
Output goes to ``.validation/landscape.json``; this is a read-only survey and none of
the cloned code is executed.

Usage::

    python scripts/independent_validation.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".validation" / "repos"
OUT = ROOT / ".validation" / "landscape.json"

REPOS = {
    "gprethesh/cascadeur-mcp": "https://github.com/gprethesh/cascadeur-mcp.git",
    "MnxD2A6/cascadeur-mcp": "https://github.com/MnxD2A6/cascadeur-mcp.git",
    "Karylcode/cascadeur-mcp-plus": "https://github.com/Karylcode/cascadeur-mcp-plus.git",
    "BrianFinch-1/cascadeur-codex-bridge": "https://github.com/BrianFinch-1/cascadeur-codex-bridge.git",
    "muhwagwa0112/cascadeur-complete": "https://github.com/muhwagwa0112/cascadeur-complete.git",
    "ysk424/cascadeur-mcp": "https://github.com/ysk424/cascadeur-mcp.git",
}

TOOL_PATTERNS = [
    r"@[a-zA-Z_][a-zA-Z0-9_]*\.tool\(",
    r"@[a-zA-Z_][a-zA-Z0-9_]*\.tool\b",
    r"\bTool\(",
    r"\badd_tool\(",
    r"\bregister_tool\(",
]
ARCH_MARKERS = {
    "native_8765": r"8765",
    "native_run_script": r"run_script",
    "user_scripts": r"user_scripts",
    "q_timer": r"QTimer|QTimer|setInterval",
    "pyside": r"PySide6|PySide2",
    "console_bootstrap": r"Python Console|python console",
    "start_script": r"start_bridge|start_mcp|start_script",
    "acl_or_safety": r"allowlist|allow_list|ACL|readonly|read_only|dry[-_ ]run",
    "license": r"LICENSE|license",
}
README_TOOL_COUNT = re.compile(r"(\d{1,3})\s+(?:mcp\s+)?tools\b", re.IGNORECASE)


def run(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {result.stderr[-400:]}")
    return result.stdout


def clone_or_update(slug: str, url: str) -> Path:
    target = WORK / slug.replace("/", "__")
    if (target / ".git").exists():
        run(["git", "fetch", "--depth", "1", "origin"], target)
        run(["git", "reset", "--hard", "FETCH_HEAD"], target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--depth", "1", url, str(target)])
    return target


def scan(repo: Path) -> dict:
    files = [p for p in repo.rglob("*") if p.is_file()]
    text_by_file = {}
    for path in files:
        if path.suffix in {".py", ".md", ".js", ".ts", ".json", ".yaml", ".yml", ".toml"}:
            try:
                if path.stat().st_size > 2_000_000:
                    continue
                text_by_file[path] = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
    combined = "\n".join(text_by_file.values())

    tool_hits = 0
    tool_files = []
    for path, text in text_by_file.items():
        if path.suffix not in {".py", ".js", ".ts"}:
            continue
        hits = sum(len(re.findall(pattern, text)) for pattern in TOOL_PATTERNS)
        if hits:
            tool_hits += hits
            tool_files.append(str(path.relative_to(repo)))

    readme = next((p for p in repo.glob("README*")), None)
    readme_text = ""
    if readme:
        readme_text = readme.read_text(encoding="utf-8", errors="replace")
    declared = [int(n) for n in README_TOOL_COUNT.findall(readme_text)]

    sha = run(["git", "rev-parse", "HEAD"], repo).strip()
    date = run(["git", "log", "-1", "--format=%cs"], repo).strip()

    markers = {
        key: bool(re.search(pattern, combined, re.IGNORECASE))
        for key, pattern in ARCH_MARKERS.items()
    }
    return {
        "repo": str(repo.relative_to(WORK)).replace("__", "/"),
        "commit": sha,
        "commit_date": date,
        "tool_decorator_hits": tool_hits,
        "tool_files": tool_files[:20],
        "readme_declared_tool_counts": declared[:5],
        "markers": markers,
        "python_files": len([p for p in files if p.suffix == ".py"]),
        "has_tests": any("test" in p.name.lower() for p in files),
    }


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    rows = []
    for slug, url in REPOS.items():
        print(f"scanning {slug} ...")
        try:
            repo = clone_or_update(slug, url)
            rows.append(scan(repo))
        except Exception as exc:  # noqa: BLE001 - survey keeps going
            print(f"  FAILED: {exc}")
            rows.append({"repo": slug, "error": str(exc)[:500]})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps(rows, indent=2))
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
