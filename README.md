# Poppet — Cascadeur MCP

[![CI](https://github.com/figgiee/poppet/actions/workflows/ci.yml/badge.svg)](https://github.com/figgiee/poppet/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Cascadeur 2025.3.3](https://img.shields.io/badge/Cascadeur-2025.3.3-orange.svg)](https://cascadeur.com/)

Model Context Protocol server for [Cascadeur](https://cascadeur.com/) 2025.3.3. Lets Claude (and any MCP client) drive a real character animation pipeline: read scene state, set sparse keyframes, trigger AutoPosing + AutoPhysics, read back telemetry, save/load scenes, screenshot the viewport, manage layers + object hierarchy, export FBX.

End-to-end demo verified: Claude proposes 8 spec §4 operations → user clicks **Commands → Poppet → Process Pending** in Cascadeur once → all 8 land, dispatcher returns 8 success responses in <3 seconds, FBX file appears on disk.

**v0.2 — auto-drain via events.** Installing the `poppet_events` package wires `scene_activated` and `scene_opened` event hooks. Cascadeur drains the request queue automatically every time its window regains focus — no manual click required for most workflows.

## Architecture

```
Claude ──MCP stdio──▶ poppet-mcp (host process, uvx-installable)
                       │ FastMCP — 43 tools + 1 resource
                       ▼
              %LOCALAPPDATA%\poppet-mcp\requests\<uuid>.json
                       ▼
        [scene_activated event fires on window focus, OR
         user clicks Commands → Poppet → Process Pending,
         OR Cascadeur is in a Poppet → Status / Drain dialog]
                       │ Cascadeur reads request, dispatches via csc.*,
                       │ writes response file
                       ▼
              %LOCALAPPDATA%\poppet-mcp\responses\<uuid>.json
                       ▲
                       │ polled by MCP server
              Returned to Claude as the tool result
```

**Why file-sync instead of sockets?** Cascadeur 2025.3.3's embedded Python can't host a long-running listener:
- PySide is not bundled — no `QTimer`
- `csc.*` exposes no main-thread scheduler / event-post / dispatch API (verified — 115 candidate methods searched, none match)
- Background `threading.Thread` only runs its first GIL slice and is then starved indefinitely (verified with minimal `time.sleep() + print()` loop)

The file-sync pattern routes around all three limitations by piggybacking on Cascadeur's normal command-invocation path (which runs on the Qt main thread with full csc.* access).

## Install

```powershell
# 1. Cascadeur-side: copies poppet/ into Cascadeur's user_scripts dir +
#    additive Python.Path/Python.Commands override (no ScriptsDir replacement —
#    that FATAL-crashes Cascadeur because it loses the rig "parts" subdir).
.\scripts\install.ps1

# 2. MCP server-side: install in your Python env (3.11+).
pip install -e .                       # editable
# or once published:
uvx poppet-mcp                         # zero-install
```

Restart Cascadeur and verify **Commands → Poppet → Process Pending** appears.

Wire into your MCP client. `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "poppet": { "command": "uvx", "args": ["poppet-mcp"] }
  }
}
```

Or Claude Code: `claude mcp add poppet -- uvx poppet-mcp`.

See [docs/mcp_client_configs.md](docs/mcp_client_configs.md) for env-var configuration, local dev install snippets, and Cursor/Windsurf setup.

After install, verify everything wired up correctly:

```powershell
python scripts/install_check.py
```

Walks through the Cascadeur-side install, `settings.json` keys (Python.Path, Python.Commands, Python.Events), the MCP server's importability, and the queue dirs — exits non-zero if anything's broken.

## Tools (verified status)

| Tool | Status | Notes |
|---|---|---|
| `get_scene_info` | [VERIFIED] | Returns frame, object_count (289 on Cascy), layer_count, selection_count, scene_name |
| `list_objects(name_contains)` | [VERIFIED] | Returns id (UUID), name, type for all objects. Honors name filter. |
| `get_selection` / `set_selection(names)` / `clear_selection` | [VERIFIED] | Uses `scene.modify_with_session(session.take_selector().select(...))` |
| `execute_csc_code(code)` | [VERIFIED] | Escape hatch — runs arbitrary Python in Cascadeur with `csc` + `scene` in scope |
| `call_action(action_id)` | [VERIFIED] | Invokes any Cascadeur menu/toolbar action ID. See https://cascadeur.com/help/category/301 |
| `list_layers` | [VERIFIED] | Returns 13 layers with id + key_frame_count for Cascy |
| `get_keyframes(layer_id, frame_start, frame_end)` | [VERIFIED] | Layer-id matched via stringified UUID |
| `set_controller_position(name, frame, x, y, z)` | [VERIFIED] | Works on both Joint (pelvis) and Box (pelvis_Box) controllers |
| `set_controller_rotation(name, frame, qx, qy, qz, qw)` | [VERIFIED] | Quat -> XYZ Euler -> `Rotation.from_euler` (csc.math.Quaternion has no public ctor) |
| `add_keyframe(layer_id, frame)` / `remove_keyframe(layer_id, frame)` | [WIRED v0.4] | `session.layers_editor().set_fixed_interpolation_or_key_if_need` / `unset_section`, patterns from `keyframe_reduction.py` + `reverse_animation.py` |
| `set_controller_scale(controller_id, frame, sx, sy, sz)` | [WIRED v0.4] | Mirrors set_controller_position; writes to Local Scale / Scale node |
| `selection_extend(names)` / `selection_subtract(names)` | [WIRED v0.5] | Set-union / set-difference on current selection — incremental refinement |
| `read_telemetry_range(controllers, start, end, step, local)` | [WIRED v0.5] | Bulk read across a frame range in one update-graph walk |
| `run_autoposing` | [VERIFIED] | Wraps `AutoPosingTool.AutoPosing` action |
| `run_autophysics(timeout_sec)` | [VERIFIED] | Wraps `AutoPhysicsTool.Snap to Auto Physics` + polls scene-state hash for convergence |
| `read_telemetry(names, frames)` | [VERIFIED] | Returns position [x,y,z] + rotation_euler [rx,ry,rz] per controller per frame |
| `export_fbx(path)` | [VERIFIED] | Real dialog-free export via `FbxSceneLoader.get_fbx_loader(scene).export_all_objects(path)`. Verified file appears (~2.9MB Binary FBX from Cascy) |
| `import_fbx(path, target=scene|animation)` | [WIRED] | Uses `FbxLoader.import_scene` / `import_animation`. Not yet exercised against a real FBX. |
| `get_current_frame` | [VERIFIED] | Returns playhead position |
| `set_current_frame(frame)` | [FIXED v0.2] | Now uses `scene.modify_update_with_session(..., lambda m, u, su, ses: ses.set_current_frame(N))`. Pattern lifted from bundled `commands/export_to_roblox.py`. |
| `save_scene(path)` / `load_scene(path)` / `new_scene` | [WIRED v0.2] | DataSourceManager + SceneManager — tries multiple call signatures to handle Cascadeur API drift |
| `get_object_hierarchy` | [WIRED v0.2] | Walks model_viewer with `get_parent_id` / `get_children_ids` (best-effort across API variants) |
| `get_object_transform(name, frame, local)` | [WIRED v0.2] | Reads Local Position + Local Rotation + Local Scale at frame |
| `list_object_attributes(name)` | [WIRED v0.2] | Lists every attribute node on the root_group — discovery aid for the LLM |
| `set_layer_visible(layer_id, visible)` / `set_layer_locked(layer_id, locked)` | [WIRED v0.2] | Uses `session.layers_editor()` with `layer.set_visible/locked()` fallback |
| `delete_object(name)` | [WIRED v0.2] | `session.model_editor().delete_objects([oid])` → action ID fallback chain |
| `duplicate_object(name)` | [WIRED v0.2] | Selects + invokes `Scene.Edit.Duplicate`; returns the diff of new objects |
| `screenshot_viewport(path)` | [WIRED v0.2] | `csc.tools.RenderToFile.editor.take_image(path)` → `Viewport.*` action fallback |
| `add_layer(name, parent_id?)` / `delete_layer(layer_id)` | [WIRED v0.2] | `session.layers_editor().create_layer/delete_layer`, pattern from `common/layers_operation.py` |
| `undo()` / `redo()` | [WIRED v0.2] | `Scene.Undo` / `Scene.Redo` action wrappers |
| `bake_range(layer_id, frame_start, frame_end)` | [WIRED v0.2] | Bakes per-frame keys via `set_fixed_interpolation_or_key_if_need`, pattern from `commands/animation_scripts/reverse_animation.py` |
| `selection_filter(pattern, mode)` | [WIRED v0.3] | Filters by `contains` / `prefix` / `suffix` / `regex` and replaces selection |
| `get_active_layer` / `set_active_layer(layer_id)` | [WIRED v0.3] | Tries multiple `current/active/selected_layer_id` getters/setters |

Resources:
- `csc://schema` — live `csc.*` API JSON (134KB) dumped by **Commands → Poppet → Refresh Schema**

## Demo scripts

### `scripts/demo_batch_spec4.py` (recommended)

Writes all 8 spec §4 operations to the request queue at once. You click Process Pending **once**, the script reads all responses. Run:

```powershell
.venv\Scripts\python.exe scripts\demo_batch_spec4.py
# In Cascadeur: click Commands → Poppet → Process Pending
```

Verified output:
```
[success] 00-scene_info
[success] 01-objects_list
[success] 02-set_controller_position pelvis_Box -> applied {position: true, position_new: [0,0,30]}
[success] 03-selection_set foot_Box_l + foot_Box_r -> resolved 2, missing 0
[success] 04-autopose_run -> invoked
[success] 05-autophysics_run -> converged: true
[success] 06-telemetry_read pelvis_Box -> position [0.0002, 48.14, 11.22], euler [...]
[success] 07-fbx_export -> exists: true, size_bytes: 2888032
[OK] FBX exported to ./tmp/poppet_demo.fbx (2888032 bytes)
```

### `scripts/demo_mcp_client.py` (per-call MCP via stdio)

Same flow but routes every tool call through the actual `poppet-mcp` server via MCP stdio transport. Requires clicking Process Pending between each call (8 clicks total). Proves the MCP pipe round-trips.

### `scripts/mcp_smoke_test.py` (no Cascadeur required)

Initializes the MCP server, lists 20 tools + 1 resource, exits. Run any time to verify the FastMCP shim:

```powershell
.venv\Scripts\python.exe scripts\mcp_smoke_test.py
```

### `scripts/poc_client.py` (low-level wire test)

Raw socket round-trip — predates the file-sync pivot. Kept for archaeological reference; ignore for new work.

## Manual smoke test

```powershell
# 1. Queue a request
python -c "
import json, os, uuid
base = os.path.join(os.environ['LOCALAPPDATA'], 'poppet-mcp')
os.makedirs(os.path.join(base, 'requests'), exist_ok=True)
rid = 'manual-' + str(uuid.uuid4())[:8]
with open(os.path.join(base, 'requests', rid + '.json'), 'w') as f:
    json.dump({'type': 'scene_info', 'params': {}}, f)
print('queued', rid)
"

# 2. In Cascadeur: Commands → Poppet → Process Pending

# 3. Read response
type %LOCALAPPDATA%\poppet-mcp\responses\manual-*.json
```

## Known limitations

| What | Why |
|---|---|
| Auto-drain via `scene_activated` only fires on focus changes | The event semantics are focus-edge-triggered, not wall-clock periodic. If the Cascadeur window is already focused and idle, no drain happens — `_nudge` re-focuses the window to force the edge transition. Manual drain (Process Pending menu / Status dialog) is always available. |
| Auto-nudge via Windows-API key-send is flaky | `SetForegroundWindow` is blocked when the MCP server process doesn't already have focus (Windows focus-stealing prevention) |
| Higher per-call latency (~100–500ms file IO) | Inherent to the file-sync architecture vs the original socket design |
| `import_fbx` not exercised end-to-end | Wired but no test FBX run against a real file yet |

## Cascadeur quirks worth knowing

- **Joint vs Box objects**: Cascy has both. Joints are skeleton bones (`pelvis`, `thigh_l`). **Controllers** are the `_Box`-suffixed objects (`pelvis_Box`, `foot_Box_l`) — those are what you actually animate.
- **`scene` parameter** to a command's `run(scene)` is a `csc.domain.Scene`, NOT `csc.view.Scene`. `scene.model_viewer()` and `scene.modify_with_session(...)` work directly.
- **`ScriptsDir` in `settings.json` is a hard replacement, not additive.** Setting it removes the bundled scripts dir and Cascadeur FATAL-crashes on startup (no rig "parts"). Use `Python.Path` + `Python.Commands` instead — see `install.ps1`.
- **Cascadeur uses Qt6** in C++, but the embedded Python has zero PySide. `Qt6Core.dll`/`Qt6Gui.dll` etc. are bundled but not accessible from Python.
- **`call_action` is fire-and-forget.** No completion signal. For solves like AutoPhysics, poll scene state (see `_d_autophysics_run`).
- **csc.math has no public Vec3 constructor.** Read existing value, build deltas as plain lists, set the sum (Vec3-likes auto-coerce). `_quat_to_euler_xyz` helper in `_dispatchers.py` because `csc.math.Quaternion` also has no public ctor in `dir()`.

## License

MIT. See [LICENSE](LICENSE).

## Status

Alpha. The file-sync architecture is verified working end-to-end against Cascadeur 2025.3.3 + the bundled CASCY sample. Most tools are exercised against real data. Some refinements remain (see Tools table).

GitHub: https://github.com/figgiee/poppet
