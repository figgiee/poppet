# cascadeur-mcp — Cascadeur MCP

[![CI](https://github.com/figgiee/poppet/actions/workflows/ci.yml/badge.svg)](https://github.com/figgiee/poppet/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Cascadeur 2026.2.3](https://img.shields.io/badge/Cascadeur-2026.2.3-orange.svg)](https://cascadeur.com/)
[![Version 1.0.0](https://img.shields.io/badge/version-1.0.0-green.svg)](CHANGELOG.md)

Model Context Protocol server for [Cascadeur](https://cascadeur.com/) **2026.2.3+**.
cascadeur-mcp gives Claude (or any MCP client) **45 typed tools** for character animation —
scene/rig inspection, sparse keyframes, AutoPosing, AutoPhysics, telemetry, layers,
scene I/O, FBX, viewport capture, escape hatches — and drives Cascadeur through the
**built-in MCP script server that ships with Cascadeur 2026.2**.

There is **nothing to install inside Cascadeur**: no `user_scripts` copy, no
`settings.json` edits, no menu commands, no queue draining, no window-focus dance.
Requires Cascadeur 2026.2.3+, Python 3.11+ (`uvx` is enough) and an MCP client.

> **Cascadeur 2025.3.x is not supported in 1.0.** The file-queue 0.6 line is preserved
> at the [v0.6.0 release](https://github.com/figgiee/poppet/releases/tag/v0.6.0).

## Quickstart (three steps)

1. **Install cascadeur-mcp** in your MCP client's environment:

   ```bash
   uvx cascadeur-mcp                 # zero-install; or: pip install cascadeur-mcp
   ```

2. **In Cascadeur, once per launch:** open a scene, then **Window → Python Console**,
   paste and Execute the line that `cascadeur-bootstrap` prints:

   ```bash
   uvx cascadeur-bootstrap           # writes the bootstrap file and prints the line
   ```

   It looks like:

   ```python
   exec(open(r"C:\Users\<you>\AppData\Local\cascadeur-mcp\cascadeur_bootstrap.py").read())
   ```

   Event Log then shows:

   ```
   [cascadeur-mcp] script server ready at http://127.0.0.1:8765/mcp
   [cascadeur-mcp] interpreter keeper installed (10 ms); keep Cascadeur open
   ```

   The same file works after every Cascadeur restart — re-run that one line.

3. **In your MCP client:** register cascadeur-mcp.

   ```bash
   claude mcp add cascadeur-mcp -- uvx cascadeur-mcp       # Claude Code
   ```

   ```json
   // Claude Desktop — claude_desktop_config.json
   { "mcpServers": { "cascadeur-mcp": { "command": "uvx", "args": ["cascadeur-mcp"] } } }
   ```

   Cursor / Windsurf / VS Code: [docs/mcp_client_configs.md](docs/mcp_client_configs.md).

No `POPPET_URL` needed: the bootstrap records the chosen port in
`%LOCALAPPDATA%\cascadeur-mcp\server.json` and `cascadeur-mcp` picks it up. Ask "what's in
my Cascadeur scene?". The **first tool call bootstraps cascadeur-mcp's ~70 KB in-app
runtime** into Cascadeur (slower); later calls are small JSON round trips. Failures:
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

### Why a bootstrap at all?

Cascadeur 2026.2's built-in script server runs its HTTP handler on a background
Python thread. Cascadeur's embedded interpreter keeps the GIL inside its Qt idle loop,
so that thread **starves whenever the app is idle** — the menu command prints
"listening", but connections sit unanswered and `/run` scripts never reach the idle
event they wait for. The bootstrap installs a 10 ms PySide timer that keeps the
interpreter ticking and drives `scene_idle`, which makes the server responsive and its
queue drain. This is a workaround for a 2026.2.3 limitation, contained in one
paste-once file; when Nekki fixes the idle loop, the built-in menu command alone will
suffice. Details: [docs/architecture.md](docs/architecture.md).

## Architecture

```
MCP client ──stdio──▶ cascadeur-mcp ──HTTP 127.0.0.1:<port>──▶ Cascadeur script server
                                                                │ scene_idle (driven
                                                                │ by cascadeur-mcp's 10 ms
                                                                │ QTimer keeper)
                                                                ▼
                                                       poppet_rt (in-app runtime)
                                                                │  csc.* / scene.*
                                                                ▼
                                                       the running Cascadeur scene
```

Cascadeur's script server exposes one primitive: run Python on the next
`scene_idle`, on the Qt main thread — a safe point for scene mutations. On the first
call cascadeur-mcp embeds `src/poppet_mcp/runtime/inapp.py` in a single expression, executes
it inside Cascadeur as private module `poppet_rt`, then sends compact
`{"command", "params"}` JSON through it. The runtime's SHA-256 is stamped in-app, so
an upgraded cascadeur-mcp re-bootstraps automatically instead of using stale handlers.

| Env var | Default | Meaning |
|---|---|---|
| `POPPET_URL` | auto-discovered, else `http://127.0.0.1:8765` | Script server base URL. |
| `POPPET_TIMEOUT` | `35` | Seconds the MCP server waits for a tool response (must stay above Cascadeur's ~30 s cap). |
| `POPPET_SERVER_PORT` | `8765` | Preferred port the **bootstrap** tries first; it walks upward if taken. |

The `POPPET_*` env names and the `poppet-mcp` / `poppet-bootstrap` console scripts
are kept as compatibility aliases (the project shipped as *poppet* before this
release); the Python package is still `poppet_mcp`.

## Tools (45)

Verification legend: **live** = exercised end-to-end on Cascadeur 2026.2.3 during the
1.0 release verification ([report](docs/verification/)); **expected** = unit-tested and
statically verified against the 2026.2.3 stubs, not yet exercised live; **known
issue** = does not work on 2026.2.3 yet. Full results:
[docs/verification/](docs/verification/).

### Scene & objects

| Tools | Status |
|---|---|
| `get_scene_info()` | live — name, frame, object/layer counts (289 objects / 13 layers on Cascy) |
| `list_objects(name_contains?)` | live — id/name/type, optional substring filter |
| `get_current_frame()` / `set_current_frame(frame)` | live — playhead moves; readback applies on the next scene update |
| `get_object_transform(object_name, frame?, local?)` | live — position/rotation/scale |
| `get_object_hierarchy()` | live — id/name/parent/children |
| `list_object_attributes(object_name)` | live — discovery aid for `execute_csc_code` |

### Selection

| Tools | Status |
|---|---|
| `get_selection()` / `set_selection(names)` / `clear_selection()` | live — undo-wrapped |
| `selection_extend(names)` / `selection_subtract(names)` | live — set union / difference |
| `selection_filter(pattern, mode=contains\|prefix\|suffix\|regex)` | live |

### Pose & telemetry

| Tools | Status |
|---|---|
| `set_controller_position(controller_id, frame, x, y, z)` | live — writes a key, verified via readback |
| `set_controller_rotation(controller_id, frame, qx, qy, qz, qw)` | expected — same verified write path |
| `set_controller_scale(controller_id, frame, sx, sy, sz, local?)` | live |
| `read_telemetry(controller_ids, frames)` | live — position + Euler rotation |
| `read_telemetry_range(controller_ids, start, end, step?, local?)` | live — one update-graph walk |

### Layers & keyframes

| Tools | Status |
|---|---|
| `list_layers()` | live — id, name, object count, key count, visible/locked |
| `get_keyframes(layer_id, frame_start, frame_end)` | live — inclusive range |
| `add_keyframe(layer_id, frame)` / `remove_keyframe(layer_id, frame)` | live |
| `add_layer(name, parent_id?)` / `delete_layer(layer_id)` | live |
| `set_layer_visible(layer_id, visible)` / `set_layer_locked(layer_id, locked)` | live |
| `bake_range(layer_id, frame_start, frame_end)` | live |
| `get_active_layer()` / `set_active_layer(layer_id)` | live — mapped to the timeline layer selection |

### Solvers

| Tools | Status |
|---|---|
| `run_autoposing()` | live invocation — action fires on the current frame |
| `run_autophysics(timeout_sec=30.0)` | expected — not re-verified live; keep `timeout_sec` ≤ ~25 s under the script-server cap |

### Scene & FBX I/O

| Tools | Status |
|---|---|
| `save_scene(path)` | live — `view.Scene.save`, client waits for the file to hit disk |
| `load_scene(path)` | live — opened the 4 MB Cascy sample |
| `new_scene()` | live — created a fresh `untitled.casc` scene |
| `import_fbx(path, target=scene\|animation)` | expected — not exercised end-to-end |
| `export_fbx(path)` | live — dialog-free binary FBX (2.9 MB for Cascy) |

### Object edit & viewport

| Tools | Status |
|---|---|
| `delete_object(name)` | expected |
| `duplicate_object(name)` | **known issue** — the 2026.2 clipboard paste path fails its modify callback; returns a clear error instead of a false success |
| `undo()` / `redo()` | live — `Scene.Undo` / `Scene.Redo` |
| `screenshot_viewport(path?, wait_sec=10)` | live — asynchronous render, client waits for the PNG (2.2 MB for Cascy) |

### Escape hatches & diagnostics

| Tools | Status |
|---|---|
| `execute_csc_code(code)` | live — in-app Python via `poppet_rt`; `csc`, `scene`, `app` in scope |
| `call_action(action_id)` | live — any menu/toolbar action ID, fire-and-forget |
| `run_script(code)` | live — raw script-server pass-through, returns `{ok, value, messages, error}` |
| `get_script_server_status()` | live — `connected`, `url`, `server_version`, `runtime_version`, `python`, `has_scene`, or `error` |

Resource: `csc://schema` — live JSON of the connected Cascadeur's `csc.*` API surface
(106 KB on 2026.2.3), introspected at read time.

## Live verification

The 1.0 release was verified against a running Cascadeur 2026.2.3 with the Cascy
sample scene:

- `scripts/live_verify.py` — **43/44** end-to-end tool steps passed (the failure is
  the documented `duplicate_object` issue); read + mutation + export + screenshot all
  exercised. Report: [docs/verification/live-verify.json](docs/verification/live-verify.json).
- `scripts/live_e2e_mcp.py` — full **MCP stdio → cascadeur-mcp → Cascadeur** path: 45
  tools registered, status/scene/layers/frame/`run_script`/`execute_csc_code` passed.
  Transcript: [docs/verification/live-e2e-mcp.txt](docs/verification/live-e2e-mcp.txt).
- `python -m pytest tests` — 210 passed, 1 skipped; protocol tests run Cascadeur's
  *shipped* `script_server.py` offline with fake `csc`/`events`.

## Known limitations

- **One console paste per Cascadeur launch** (see *Why a bootstrap at all?*).
- **~30 s per tool call** — Cascadeur's script server caps a request. Long solves or
  exports may need splitting or a retry; timeouts are not proof the operation failed.
- **`duplicate_object`** fails on 2026.2.3 (clipboard paste callback). Use
  `execute_csc_code` with Cascadeur's own `commands/copy_paste_objects/duplicate.py`
  until it is fixed.
- **AutoPhysics / FBX import** were not re-verified live in 1.0.

## Migrating from 0.6 (file queue) to 1.0

1. Delete the old Cascadeur-side package (skip if you never used 0.6):
   `%LOCALAPPDATA%\Nekki Limited\Cascadeur\user_scripts\cascadeur-mcp\` and
   `...\user_scripts\poppet_events\`.
2. Optionally remove cascadeur-mcp entries from `Python.Path` / `Python.Commands` /
   `Python.Events` in Cascadeur's `settings.json` (harmless if left; no longer used).
   Restart Cascadeur once so the old menu commands disappear.
3. `uvx cascadeur-bootstrap` and run the printed line in Cascadeur's Python Console.
4. Keep your MCP client entry as-is. Tool names/parameters are unchanged; new tools are
   `get_script_server_status` and `run_script`.
5. Forget the old drain step, focus nudge and queue directories.

Cascadeur 2025.3.x users: stay on
[v0.6.0](https://github.com/figgiee/poppet/releases/tag/v0.6.0).

## Why cascadeur-mcp?

Cascadeur's built-in server exposes one tool (`run_script`) and two resources. cascadeur-mcp
adds the typed, verified layer: 45 named tools, a live API schema, structured errors,
and an in-app runtime that keeps handler logic out of prompts. Of the public Cascadeur
MCP servers surveyed in [docs/research/github-landscape.md](docs/research/github-landscape.md),
cascadeur-mcp is the only typed implementation built on the native server (the others ship
their own Cascadeur-side bridges).

## Docs

[USAGE.md](USAGE.md) · [TROUBLESHOOTING.md](TROUBLESHOOTING.md) ·
[docs/architecture.md](docs/architecture.md) ·
[docs/mcp_client_configs.md](docs/mcp_client_configs.md) ·
[docs/publishing.md](docs/publishing.md) ·
[docs/research/](docs/research/README.md). License: MIT — see [LICENSE](LICENSE).
cascadeur-mcp is independent of Nekki; Cascadeur is a trademark of Nekki Limited.
