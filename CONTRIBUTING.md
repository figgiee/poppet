# Contributing to Poppet

Thanks for considering a contribution.

## Quick start

```powershell
git clone https://github.com/figgiee/poppet.git
cd poppet
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
.\scripts\install.ps1                 # Cascadeur side
python scripts\install_check.py       # Verify install
pytest tests/                         # Should be 164+ passed, 1 skipped
python scripts\mcp_smoke_test.py      # 40+ tools registered
```

## Project layout

| Path | Runs in | Notes |
|---|---|---|
| `src/poppet_mcp/` | Modern Python 3.11+ | FastMCP server, file-sync client, Windows-API nudge |
| `cascadeur_side/poppet/` | Cascadeur's embedded **Python 3.8** | Commands + dispatchers — MUST stay 3.8-compatible |
| `cascadeur_side/poppet_events/` | Cascadeur's embedded Python 3.8 | Event handlers (scene_activated, scene_opened) |
| `tests/` | Python 3.11+ | pytest with mocked `csc` — exercise dispatcher routing + helpers |
| `scripts/` | Python 3.11+ | install + demo + diagnostic scripts |
| `.github/workflows/` | GitHub Actions | CI (`ci.yml`) and release (`release.yml`) |

## What "Python 3.8 compatible" means for `cascadeur_side/`

The CI job `cascadeur_side parses on Python 3.8` runs `py_compile` under real CPython 3.8. Anything that won't parse there fails the build. So:

- **DO**: `from __future__ import annotations` to use modern type-hint syntax in annotations only
- **DO**: f-strings (3.6+), walrus is NOT available (3.8 has no walrus)
- **DON'T**: `dict[str, int]` / `list[str]` in non-annotation positions — use `typing.Dict` / `typing.List` or skip the annotation
- **DON'T**: `int | str` union syntax — use `typing.Union[int, str]` or `Optional[int]`
- **DON'T**: `match`/`case` (3.10+), parenthesized context managers (3.10+)
- **DON'T**: `Self` (3.11+), `assert_never` (3.11+)

The ruff config (`pyproject.toml`) targets Python 3.8 across the whole repo as a safe superset, so `pip install -e ".[dev]"` + `ruff check` will catch most issues locally before CI does.

## Adding a new tool

Two layers. Both need to exist for a tool to be usable end-to-end:

1. **Dispatcher** in `cascadeur_side/poppet/_dispatchers.py`:
   - `_d_<your_tool>(params, scene)` function
   - Register in `_HANDLERS` dict at the bottom of the file
   - Use defensive `try/except` across multiple csc.* method-name variants — Cascadeur's API drifts, our dispatchers should report which variant worked rather than crash

2. **MCP server tool** in `src/poppet_mcp/server.py`:
   - `@mcp.tool() def <your_tool>(...) -> dict: return _call("<your_tool>", ...)`
   - Docstring is what Claude sees — be explicit about what the tool does, what it returns, and when to use it vs alternatives

3. **Tests** in `tests/test_new_dispatchers.py` and `tests/test_mcp_server.py`:
   - Dispatcher: validation tests (raises on missing required params, raises on unknown ids), routing tests (calls `scene.modify_*` with the right args)
   - MCP server: parameter-passing test (the @mcp.tool wrapper forwards correct kwargs to `_call`)
   - Bump the `test_handler_count_at_least_N` and `test_at_least_N_tools_registered` assertions
   - Add the new tool name to the `test_new_handler_registered` parametrize list

4. **README + CHANGELOG**:
   - Add a row to the tools table in README.md
   - Add the tool to the next `## [unreleased]` section of CHANGELOG.md
   - Bump the tool count in the architecture diagram

## Branch + PR workflow

- Never commit directly to `main` (a pre-commit / pre-push hook will block it)
- Branch naming: `feat/v<X>.<Y>-<topic>`, `fix/<topic>`, `chore/<topic>`, `docs/<topic>`
- Open a PR with a Test plan section (checkboxes for what was verified)
- CI must be green before merging — `ruff check`, `ruff format --check`, py3.8 syntax, pytest matrix, MCP smoke
- Squash-merge with `--auto` if you want it to merge as soon as CI passes

## Style

- Ruff (line length 100, target py38, rule set E/F/I/UP minus UP006/UP007/UP035/UP045)
- No AI/LLM attribution anywhere in commits, code, docs, or PR descriptions
- Match the existing dry, terse voice in README/USAGE/TROUBLESHOOTING
- Don't add emojis unless the user asks

## Releasing

Maintainers: tag a release commit on `main`, push the tag, and `release.yml` will build + publish.

```bash
git tag -a v0.4.0 -m "Poppet 0.4.0 — <summary>"
git push origin v0.4.0
```

The workflow needs either Trusted Publishing configured on PyPI, or a `PYPI_API_TOKEN` repository secret. See `.github/workflows/release.yml`.
