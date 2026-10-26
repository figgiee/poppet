# Contributing to cascadeur-mcp

Thanks for considering a contribution.

## Quick start

```powershell
git clone https://github.com/figgiee/poppet.git
cd cascadeur-mcp
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest tests/                         # offline: mocked csc + Cascadeur's shipped server code
ruff check src tests scripts
```

You do **not** need Cascadeur to run the test suite. The protocol tests load
Cascadeur's own `scripts/mcp/script_server/server.py` from a local install with
fake `csc`/`events` modules (see `tests/native_server_harness.py`); they skip
automatically when the install is absent.

To try the real thing: open Cascadeur 2026.2.3, run **Scripts → MCP → Start script
server**, then `python scripts/live_check.py`.

## Project layout

| Path | Runs in | Notes |
|---|---|---|
| `src/poppet_mcp/server.py` | MCP client host (Python 3.11+) | FastMCP stdio server; the tool surface agents see |
| `src/poppet_mcp/cascadeur_connection.py` | MCP client host | Loopback HTTP client for Cascadeur's script server; error mapping, bootstrap/reload |
| `src/poppet_mcp/_expression.py` | MCP client host | Builds the single `eval`-able expression payload and the dispatch/bootstrap programs |
| `src/poppet_mcp/runtime/inapp.py` | **Inside Cascadeur** (embedded Python 3.11) | The shipped in-app runtime: `dispatch()`, all handlers, schema introspection |
| `src/poppet_mcp/runtime/__init__.py` | MCP client host | Loads the runtime source text, derives `RUNTIME_VERSION` and `SOURCE_DIGEST` |
| `tests/` | Python 3.11+ | Unit tests (mocked `csc`), protocol tests against Cascadeur's shipped server |
| `scripts/` | Python 3.11+ | `live_check.py` (real Cascadeur), `mcp_smoke_test.py` (stdio handshake) |
| `docs/` | — | Architecture, client configs, research notes (competitive landscape + API diff) |

## How the two halves talk

1. The MCP client calls a tool.
2. `cascadeur_connection.py` submits **one Python expression** to Cascadeur's
   script server over `POST /run`.
3. That expression either dispatches into an already-loaded `poppet_rt` module or
   bootstraps it from shipped source, then returns a JSON string.
4. The client `literal_eval`s the repr, `json.loads`es the payload, and either
   returns the result or raises with the in-app traceback.

The runtime module is stamped with the SHA-256 (`SOURCE_DIGEST`) of the exact
source the client ships. Editing `inapp.py` therefore invalidates any runtime
already loaded in Cascadeur on the next call — no stale handlers, no manual cache
clearing. `RUNTIME_VERSION` is a human-readable stamp reported by
`get_script_server_status`.

## Adding a new tool

Two layers, both required:

1. **Handler** in `src/poppet_mcp/runtime/inapp.py`:
   - `def _d_<your_tool>(params, scene):` — returns a JSON-able dict
   - Register in the `_HANDLERS` dict at the bottom of the file
   - Raise `ValueError` for bad parameters; never return a fake success
   - For mutations, wrap work in `scene.modify_with_session(...)` /
     `scene.modify_update_with_session(...)` **and check the return value** — a
     `False`/falsy result means Cascadeur's callback failed even though the HTTP
     call succeeded
   - Ground API calls in the shipped `.pyi` stubs under
     `<Cascadeur install>/resources/scripts/stubs/` — do not guess method names
2. **MCP tool** in `src/poppet_mcp/server.py`:
   - `@mcp.tool() def your_tool(...) -> dict: return _call("your_tool", ...)`
   - The docstring is what the agent sees: state what it does, what it returns,
     failure modes, and how it differs from neighbouring tools

Then:

3. **Tests**
   - Handler tests in `tests/test_new_dispatchers.py` (validation + mocked
     `scene.modify_*` arguments)
   - Routing test in `tests/test_mcp_server.py` (tool forwards correct command +
     params)
   - Bump the tool-count assertions when the surface grows
4. **Docs**: add the tool to the README table and a line under the next
   `## [Unreleased]` in `CHANGELOG.md`.

## Runtime invariants (do not break these)

- Everything submitted to Cascadeur must be **one expression** — the script server
  compiles with `mode="eval"` first and drops values from the `exec` path.
- `dispatch(request_json, scene, csc, app) -> str` stays the runtime entry point.
- Command names and parameter shapes are the stable contract between
  `server.py` and `inapp.py`; rename both sides together.
- The script server runs submitted code on the next `scene_idle` event with a
  ~30 second cap. Handlers that can exceed it must return progress/status and let
  the caller poll instead of blocking.

## Style

- Ruff (line length 100, target py311, rule set E/F/I/UP); `ruff format` before
  committing.
- Match the existing dry, technical voice. No emojis, no marketing language.
- No AI/LLM attribution in commits, code, docs, or PR descriptions.

## Branch + PR workflow

- Branch naming: `feat/<topic>`, `fix/<topic>`, `chore/<topic>`, `docs/<topic>`
- PRs include a **Test plan** section listing what was actually run
  (e.g. "pytest 172 passed; live_check against Cascadeur 2026.2.3 on port 8766")
- CI must be green: `ruff check`, `ruff format --check`, pytest matrix,
  MCP stdio smoke

## Releasing

Maintainers: tag a release commit on `main`, push the tag, and `release.yml` will
build + publish to PyPI and attach artifacts to the GitHub release.

```bash
git tag -a v1.0.0 -m "cascadeur-mcp 1.0.0 — native-script-server runtime"
git push origin v1.0.0
```

Release notes are extracted from the matching `## [x.y.z]` section of
`CHANGELOG.md`. The workflow needs PyPI Trusted Publishing or a
`PYPI_API_TOKEN` repository secret.
