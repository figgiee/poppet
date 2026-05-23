# Poppet — Cascadeur MCP

Model Context Protocol server that lets Claude (and any other MCP client) drive [Cascadeur](https://cascadeur.com/) 2025.3.3 for AI-assisted character animation.

**Architecture (after the v1 pivot — see [`PLAN.md`](#)):**

```
Claude ──MCP stdio──▶ poppet-mcp (host process)
                       │ FastMCP tools
                       ▼
              %LOCALAPPDATA%\poppet-mcp\requests\<uuid>.json  ◀── written by MCP server
                       ▼
              [User clicks Commands → Poppet → Process Pending in Cascadeur]
                       │ Cascadeur reads request, dispatches via csc.*, writes response
                       ▼
              %LOCALAPPDATA%\poppet-mcp\responses\<uuid>.json ◀── polled by MCP server
```

**Why file-sync?** Cascadeur 2025.3.3's embedded Python can't host a long-running socket listener:
- PySide is not bundled — no QTimer
- csc.* exposes no main-thread scheduler / event-post API
- Background `threading.Thread` only runs its first GIL slice and is then starved indefinitely

The file-sync pattern routes around all three limitations by using Cascadeur's normal command-invocation path (which runs on the main thread, in Python, with full csc.* access) as the dispatch tick.

## Status

Alpha. Manual-drain workflow is verified working end-to-end (echo, scene_info, call_action all round-trip through Cascadeur 2025.3.3 + CASCY sample scene). Auto-nudge via Windows-API key-send is experimental and only works when the MCP server's process already has foreground focus (Windows focus-stealing prevention blocks it otherwise).

## Install

```powershell
.\scripts\install.ps1
```

This:
1. Reads `%LOCALAPPDATA%\Nekki Limited\Cascadeur\settings.json`
2. Adds `%LOCALAPPDATA%\Nekki Limited\Cascadeur\user_scripts` to `Python.Path`
3. Appends `"poppet"` to `Python.Commands`
4. Copies `cascadeur_side/poppet/` to `%LOCALAPPDATA%\Nekki Limited\Cascadeur\user_scripts\poppet\`

ScriptsDir is **never** modified — Cascadeur replaces (not extends) the bundled scripts dir if you set it, which removes the rig "parts" and triggers a FATAL crash on next launch.

**macOS / Linux:** `./scripts/install.sh` (path probes for `/Applications/Cascadeur.app/...`, untested).

## First-run workflow

1. Restart Cascadeur. Verify **Commands → Poppet → Process Pending** and **Commands → Poppet → Refresh Schema** appear.
2. Run **Commands → Poppet → Refresh Schema** once — this dumps the live `csc.*` API to `%LOCALAPPDATA%\poppet-mcp\csc_schema.json` for LLM consumption.
3. Wire the MCP server into your client. Claude Desktop's `claude_desktop_config.json`:
   ```json
   {
     "mcpServers": {
       "poppet": { "command": "uvx", "args": ["poppet-mcp"] }
     }
   }
   ```
   Or Claude Code: `claude mcp add poppet -- uvx poppet-mcp`.
4. **Per tool call**: Claude tools call into poppet-mcp, which writes a request file and polls for a response. **You must click Commands → Poppet → Process Pending** in Cascadeur to drain the queue (auto-nudge is best-effort — see below).

## Tools exposed

**Core**
- `get_scene_info()`, `get_selection()`, `set_selection(object_names)`
- `execute_csc_code(code)` — arbitrary Python escape hatch
- `call_action(action_id)` — any Cascadeur menu/toolbar action ID (see https://cascadeur.com/help/category/301)

**Animation**
- `list_layers()`, `get_keyframes(layer_id, frame_start, frame_end)`
- `set_controller_position(controller_id, frame, x, y, z)`
- `set_controller_rotation(controller_id, frame, qx, qy, qz, qw)`
- `add_keyframe(layer_id, frame)`, `remove_keyframe(layer_id, frame)`

**AutoPhysics workflow (spec §4)**
- `run_autoposing()`, `run_autophysics(timeout_sec=30)`
- `read_telemetry(controller_ids, frames)`

**FBX**
- `import_fbx(path)`, `export_fbx(path)`

**Resource**
- `csc://schema` — live-introspected `csc.*` signature JSON

Many higher-level handlers (keyframes, telemetry, etc.) are scaffolding marked `TODO` in `cascadeur_side/poppet/_dispatchers.py` — refine against the live API as you exercise them. `execute_csc_code` and `call_action` work today and cover anything the typed wrappers don't.

## Auto-nudge

The MCP server side has a best-effort nudge in `src/poppet_mcp/_nudge.py` that:
1. Finds Cascadeur's window via `EnumWindows`
2. Primes Windows with an Alt keystroke (to bypass focus-stealing prevention)
3. Sends `Alt+C, p, p, Enter, p` to navigate **Commands → Poppet → Process Pending**

**Limitation**: Windows blocks `SetForegroundWindow` from processes that don't currently hold focus. When the MCP server runs from Claude Desktop / Code (which has focus), the nudge fails. **Reliable workflow is the manual click.**

A fix for the nudge would require either:
- AttachThreadInput trick + SetForegroundWindow (still flaky)
- A native helper hooked into Cascadeur (intrusive)
- Cascadeur adding a main-thread scheduler API (upstream ask)

## Known limitations

| What | Why |
|---|---|
| No autonomous server | Cascadeur's embedded Python can't host a tick loop (no PySide, no scheduler API, no real Python threading) |
| Manual drain per request | Same root cause — user must click **Process Pending** |
| Auto-nudge flaky | Windows focus-stealing prevention blocks `SetForegroundWindow` from background processes |
| Some dispatchers are scaffolding | `_dispatchers.py` selection/layers/keyframes/telemetry are TODO; csc API surface verification needed against live install |
| Higher latency per call | ~100-500ms file IO + user-click latency (no longer the ~ms socket latency the original design promised) |

## Test it manually

```bash
# 1. Drop a request file
python -c "
import json, os, uuid
base = os.path.join(os.environ['LOCALAPPDATA'], 'poppet-mcp')
os.makedirs(os.path.join(base, 'requests'), exist_ok=True)
rid = 'test-' + str(uuid.uuid4())[:8]
with open(os.path.join(base, 'requests', rid + '.json'), 'w') as f:
    json.dump({'type': 'echo', 'params': {'hello': 'world'}}, f)
print('queued', rid)
"

# 2. Click Commands → Poppet → Process Pending in Cascadeur

# 3. Read the response
ls %LOCALAPPDATA%\poppet-mcp\responses\
type %LOCALAPPDATA%\poppet-mcp\responses\test-*.json
```

## License

MIT. See [LICENSE](LICENSE).
