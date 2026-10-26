# Poppet — Cascadeur MCP

[![CI](https://github.com/figgiee/poppet/actions/workflows/ci.yml/badge.svg)](https://github.com/figgiee/poppet/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Cascadeur 2026.2.3](https://img.shields.io/badge/Cascadeur-2026.2.3-orange.svg)](https://cascadeur.com/)
[![Version 1.0.0](https://img.shields.io/badge/version-1.0.0-green.svg)](CHANGELOG.md)

Model Context Protocol server for [Cascadeur](https://cascadeur.com/) **2026.2.3+**.
Poppet gives Claude (or any MCP client) **45 typed tools** for character animation —
scene/rig inspection, sparse keyframes, AutoPosing, AutoPhysics, telemetry, layers,
scene I/O, FBX, viewport capture, escape hatches — and drives Cascadeur through the
**built-in MCP script server that ships with Cascadeur 2026.2**.

There is **nothing to install inside Cascadeur**: no `user_scripts` copy, no
`settings.json` edits, no menu commands, no queue draining, no window-focus dance.
Start Cascadeur's script server, register Poppet in your MCP client, done. Requires
Cascadeur 2026.2.3+, Python 3.11+ (`uvx` is enough) and an MCP client.

> **Cascadeur 2025.3.x is not supported in 1.0.** The file-queue 0.6 line is preserved
> at the [v0.6.0 release](https://github.com/figgiee/poppet/releases/tag/v0.6.0).

## Quickstart (two steps)

1. **In Cascadeur:** open a scene, then **Scripts → MCP → Start script server**. The
   Event Log prints `[Cascadeur MCP] listening at http://127.0.0.1:8765/mcp`.
   The server stops when Cascadeur exits; on a script reload Cascadeur restarts it
   automatically.

2. **In your MCP client:** register Poppet.

   ```bash
   claude mcp add poppet -- uvx poppet-mcp       # Claude Code
   ```

   ```json
   // Claude Desktop — claude_desktop_config.json
   { "mcpServers": { "poppet": { "command": "uvx", "args": ["poppet-mcp"] } } }
   ```

   Cursor / Windsurf / VS Code: [docs/mcp_client_configs.md](docs/mcp_client_configs.md).

Ask "what's in my Cascadeur scene?". The **first tool call bootstraps Poppet's
~70 KB in-app runtime** into Cascadeur (slower); later calls are small JSON round
trips. Failures: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Architecture

```
MCP client ──stdio──▶ poppet-mcp ──HTTP 127.0.0.1:8765──▶ Cascadeur script server
                                                             │ scene_idle
                                                             ▼
                                                    poppet_rt (in-app runtime)
                                                             │  csc.* / scene.*
                                                             ▼
                                                    the running Cascadeur scene
```

Cascadeur's script server exposes one primitive: run Python on the next
`scene_idle`, on the Qt main thread — a safe point for scene mutations. On the first
call Poppet embeds `src/poppet_mcp/runtime/inapp.py` in a single expression, executes
it inside Cascadeur as private module `poppet_rt`, then sends compact
`{"command", "params"}` JSON through it. Plain HTTP/JSON, no SSE, no install, no
background processes inside Cascadeur. Details: [docs/architecture.md](docs/architecture.md).

| Env var | Default | Meaning |
|---|---|---|
| `POPPET_URL` | `http://127.0.0.1:8765` | Script server base URL (change if it runs on another port). |
| `POPPET_TIMEOUT` | `35` | Seconds the MCP server waits for a tool response (must stay above Cascadeur's ~30 s cap). |

## Tools (45)

Verification legend: **verified** = exercised end-to-end in 0.6 on Cascadeur
2025.3.3, handler migrated unchanged; **expected** = wired and unit-tested, not yet
re-verified live on 2026.2.3; **known risk** = flagged by the static 2026.2.3 API
audit ([docs/research/python-api-diff.md](docs/research/python-api-diff.md));
**new** = added in 1.0. 1.0 has not been re-verified tool-by-tool against a live
2026.2.3 session; the protocol path is covered by integration tests against
Cascadeur's *shipped* server (`tests/native_server_harness.py`). Treat `expected` as
"should work — report if not".

### Scene & objects

| Tools | Verification / notes |
|---|---|
| `get_scene_info()` | verified — name, frame, counts, whether a scene is open |
| `list_objects(name_contains?)` | verified — id/name/type, optional substring filter |
| `get_current_frame()` / `set_current_frame(frame)` | verified — `set` readback can lag one drain; trust the viewport |
| `get_object_transform(object_name, frame?, local?)` | expected |
| `get_object_hierarchy()` | known risk — audit flags the parent/children call shape |
| `list_object_attributes(object_name)` | expected — discovery aid for `execute_csc_code` |

### Selection

| Tools | Verification / notes |
|---|---|
| `get_selection()` / `set_selection(names)` / `clear_selection()` | verified — undo-wrapped |
| `selection_extend(names)` / `selection_subtract(names)` | expected — set union / difference |
| `selection_filter(pattern, mode=contains\|prefix\|suffix\|regex)` | expected |

### Pose & telemetry

| Tools | Verification / notes |
|---|---|
| `set_controller_position(controller_id, frame, x, y, z)` | verified — world-space, creates a key |
| `set_controller_rotation(controller_id, frame, qx, qy, qz, qw)` | verified |
| `set_controller_scale(controller_id, frame, sx, sy, sz, local?)` | expected |
| `read_telemetry(controller_ids, frames)` | verified — position + Euler rotation |
| `read_telemetry_range(controller_ids, start, end, step?, local?)` | expected — one update-graph walk |

### Layers & keyframes

| Tools | Verification / notes |
|---|---|
| `list_layers()` | known risk — visibility/lock/object-count fields may be missing; id/name/key counts reliable |
| `get_keyframes(layer_id, frame_start, frame_end)` | verified — inclusive range |
| `add_keyframe(layer_id, frame)` / `remove_keyframe(layer_id, frame)` | expected |
| `add_layer(name, parent_id?)` / `delete_layer(layer_id)` | expected |
| `set_layer_visible(layer_id, visible)` / `set_layer_locked(layer_id, locked)` | known risk — audit flags argument order |
| `bake_range(layer_id, frame_start, frame_end)` | expected — per-frame keys |
| `get_active_layer()` / `set_active_layer(layer_id)` | expected — mapped to the timeline layer selection; 2026.2 has no separate "active layer" API |

### Solvers

| Tools | Verification / notes |
|---|---|
| `run_autoposing()` | verified — current frame, near-instant |
| `run_autophysics(timeout_sec=30.0)` | verified (2025.3.3); keep `timeout_sec` ≤ ~25 s under the script-server cap |

### Scene & FBX I/O

| Tools | Verification / notes |
|---|---|
| `save_scene(path)` / `load_scene(path)` / `new_scene()` | expected — `.casc` save/open/create |
| `import_fbx(path, target=scene\|animation)` | expected — semantics not exercised end-to-end |
| `export_fbx(path)` | verified — dialog-free binary FBX, ~2.9 MB for Cascy |

### Object edit & viewport

| Tools | Verification / notes |
|---|---|
| `delete_object(name)` / `duplicate_object(name)` | known risk — audit flags the call shapes |
| `undo()` / `redo()` | expected — `Scene.Undo` / `Scene.Redo` |
| `screenshot_viewport(path?)` | known risk — `RenderToFile.take_image` arity may differ; check `exists` |

### Escape hatches & diagnostics

| Tools | Verification / notes |
|---|---|
| `execute_csc_code(code)` | verified — in-app Python via `poppet_rt`; `csc`, `scene`, `app` in scope |
| `call_action(action_id)` | verified — any menu/toolbar action ID, fire-and-forget |
| `run_script(code)` | new / `[needs live verification]` — raw script-server pass-through, returns `{ok, value, messages, error}` |
| `get_script_server_status()` | new — `connected`, `url`, `server_version`, `runtime_version`, `python`, `has_scene`, or `error` |

Resource: `csc://schema` — live JSON of the connected Cascadeur's `csc.*` API surface,
introspected at read time (matches the exact build you are driving).

## Migrating from 0.6 (file queue) to 1.0

1. Delete the old Cascadeur-side package (skip if you never used 0.6):
   `%LOCALAPPDATA%\Nekki Limited\Cascadeur\user_scripts\poppet\` and
   `...\user_scripts\poppet_events\`.
2. Optionally remove Poppet entries from `Python.Path` / `Python.Commands` /
   `Python.Events` in Cascadeur's `settings.json` (harmless if left; no longer used).
   Restart Cascadeur once so the old menu commands disappear.
3. Start Cascadeur's script server: **Scripts → MCP → Start script server**.
4. Keep your MCP client entry as-is (`uvx poppet-mcp` or
   `python -m poppet_mcp.server`). Tool names/parameters are unchanged; new tools are
   `get_script_server_status` and `run_script`.
5. Forget the old drain step, focus nudge and queue directories.

Cascadeur 2025.3.x users: stay on
[v0.6.0](https://github.com/figgiee/poppet/releases/tag/v0.6.0).

## Why Poppet?

Cascadeur's built-in server exposes one tool (`run_script`) and two resources. Poppet
adds the typed, verified layer: 45 named tools, a live API schema, structured errors,
and an in-app runtime that keeps handler logic out of prompts. Of the public Cascadeur
MCP servers surveyed in [docs/research/github-landscape.md](docs/research/github-landscape.md),
Poppet is the only install-free typed implementation built on the native server.

## Docs

[USAGE.md](USAGE.md) · [TROUBLESHOOTING.md](TROUBLESHOOTING.md) ·
[docs/architecture.md](docs/architecture.md) ·
[docs/mcp_client_configs.md](docs/mcp_client_configs.md) ·
[docs/research/](docs/research/README.md). License: MIT — see [LICENSE](LICENSE).
Poppet is independent of Nekki; Cascadeur is a trademark of Nekki Limited.
