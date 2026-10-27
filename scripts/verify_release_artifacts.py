"""Verify the release artifacts attached to a GitHub release.

Downloads the wheel/sdist attached to a tag, checks their metadata and contents,
imports the package from the wheel without installing it, and (optionally) runs a
subprocess against the extracted wheel. Writes a JSON report next to the other
verification evidence.

Usage::

    python scripts/verify_release_artifacts.py --tag v1.0.0
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

EXPECTED_NAME = "cascadeur-mcp"
EXPECTED_VERSION = "1.0.0"


def _download(repo: str, tag: str, target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["gh", "release", "download", tag, "--repo", repo, "--dir", str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(target.glob("*"))


def _wheel_metadata(wheel: Path) -> dict[str, str]:
    with zipfile.ZipFile(wheel) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
        text = archive.read(name).decode("utf-8")
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            fields.setdefault(key, value)
    return fields


def _sdist_paths(sdist: Path) -> list[str]:
    with tarfile.open(sdist) as archive:
        return archive.getnames()


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="figgiee/poppet")
    parser.add_argument("--tag", default="v1.0.0")
    parser.add_argument("--report", default="docs/verification/release-artifacts.json")
    args = parser.parse_args(argv)

    workdir = Path(tempfile.mkdtemp(prefix="cascadeur-mcp-release-"))
    report: dict = {"repo": args.repo, "tag": args.tag, "checks": [], "ok": True}

    def check(name: str, fn):
        try:
            detail = fn()
        except Exception as exc:  # noqa: BLE001 - report every failure
            report["ok"] = False
            report["checks"].append({"check": name, "ok": False, "error": str(exc)[:2000]})
            print(f"FAIL {name}: {exc}")
            return None
        report["checks"].append({"check": name, "ok": True, "detail": detail})
        print(f"PASS {name}: {detail}")
        return detail

    try:
        assets = _download(args.repo, args.tag, workdir)
        wheels = [a for a in assets if a.suffix == ".whl"]
        sdists = [a for a in assets if a.name.endswith(".tar.gz")]
        check("assets downloaded", lambda: [a.name for a in assets])
        if not wheels or not sdists:
            print("missing wheel or sdist in release assets")
            return 1

        wheel = wheels[0]
        sdist = sdists[0]
        meta = (
            check(
                "wheel metadata",
                lambda: {
                    "Name": _wheel_metadata(wheel).get("Name"),
                    "Version": _wheel_metadata(wheel).get("Version"),
                },
            )
            or {}
        )
        report["wheel"] = wheel.name
        report["sdist"] = sdist.name
        if meta.get("Name") != EXPECTED_NAME or meta.get("Version") != EXPECTED_VERSION:
            report["ok"] = False
            print(f"FAIL metadata expected {EXPECTED_NAME} {EXPECTED_VERSION}, got {meta}")
        else:
            print(f"PASS wheel is {EXPECTED_NAME} {EXPECTED_VERSION}")

        extract_dir = workdir / "extracted"
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(extract_dir)
        check(
            "wheel contains runtime source",
            lambda: (extract_dir / "poppet_mcp/runtime/inapp.py").is_file(),
        )
        check(
            "wheel contains bootstrap",
            lambda: (extract_dir / "poppet_mcp/cascadeur_bootstrap.py").is_file(),
        )

        def import_check():
            env = dict(os.environ)
            env["PYTHONPATH"] = str(extract_dir) + os.pathsep + env.get("PYTHONPATH", "")
            out = subprocess.run(
                [sys.executable, "-c", "import poppet_mcp; print(poppet_mcp.__version__)"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            return out.stdout.strip()

        version = check("wheel imports", import_check)
        if version != EXPECTED_VERSION:
            report["ok"] = False

        def entrypoints():
            env = dict(os.environ)
            env["PYTHONPATH"] = str(extract_dir) + os.pathsep + env.get("PYTHONPATH", "")
            out = subprocess.run(
                [sys.executable, "-m", "poppet_mcp.bootstrap_cli", "--print-only"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            return "Python Console" in out.stdout

        check("bootstrap CLI runs from wheel", entrypoints)

        def sdist_check():
            paths = _sdist_paths(sdist)
            required = [
                "src/poppet_mcp/server.py",
                "src/poppet_mcp/runtime/inapp.py",
                "README.md",
                "CHANGELOG.md",
            ]
            missing = [p for p in required if not any(name.endswith(p) for name in paths)]
            if missing:
                raise RuntimeError(f"missing from sdist: {missing}")
            return f"{len(paths)} entries"

        check("sdist contents", sdist_check)

        pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
        report["project"] = pyproject["project"]["name"]
    finally:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"report: {report_path}")
        shutil.rmtree(workdir, ignore_errors=True)

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
