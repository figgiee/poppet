# Poppet — Cascadeur MCP

Model Context Protocol server that lets Claude (and any other MCP client) drive [Cascadeur](https://cascadeur.com/) 2025.3.3 for AI-assisted character animation — sparse keyframe authoring, AutoPosing, AutoPhysics, scene introspection, FBX I/O.

Mirrors the two-component shape of the popular [Blender MCP](https://github.com/ahujasid/blender-mcp):

```
Claude ──MCP stdio──▶ poppet-mcp (host process)
                       │ FastMCP tools
                       │ persistent TCP, length-prefixed JSON
                       ▼
                  localhost:53145
                       ▲
                       │ non-blocking accept loop, QTimer-driven
                  poppet (Cascadeur command script, PySide2 event loop)
                       │ scene.modify_with_session(...)
                       ▼
                  Cascadeur csc.* API
```

## Status

Alpha. Verify the QTimer POC works on your install before relying on the full server (see [Verification](#verification)).

## Install

### 1. Install the Cascadeur-side command script

```powershell
.\scripts\install.ps1
```

This copies `cascadeur_side/poppet/` into your Cascadeur commands folder (auto-detected from `%LOCALAPPDATA%\Nekki Limited\Cascadeur\settings.ini`, with fallback probes of common install paths).

macOS/Linux: `./scripts/install.sh`.

### 2. Restart Cascadeur

Open Cascadeur and run **Commands → External commands → Poppet Start Server** once. The listener stays up until you close Cascadeur.

### 3. Wire up your MCP client

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "poppet": { "command": "uvx", "args": ["poppet-mcp"] }
  }
}
```

Or Claude Code:

```bash
claude mcp add poppet -- uvx poppet-mcp
```

## Tools exposed

**Core**
- `get_scene_info()`, `get_selection()`, `set_selection(object_names)`
- `execute_csc_code(code)` — arbitrary Python escape hatch
- `call_action(action_id)` — invoke any Cascadeur menu/toolbar action

**Animation**
- `list_layers()`, `get_keyframes(layer_id, frame_start, frame_end)`
- `set_controller_position(controller_id, frame, x, y, z)`
- `set_controller_rotation(controller_id, frame, qx, qy, qz, qw)`
- `add_keyframe(layer_id, frame)`, `remove_keyframe(layer_id, frame)`

**AutoPhysics workflow**
- `run_autoposing()`, `run_autophysics()`
- `read_telemetry(controller_ids, frames)`

**FBX**
- `import_fbx(path)`, `export_fbx(path)`

**Resources**
- `csc://schema` — live-introspected `csc.*` signature JSON

## Verification

The architectural risk is whether Cascadeur's embedded PySide2 event loop tolerates a QTimer-driven socket listener without freezing the UI. Verify before relying on the full server:

1. Install the Cascadeur-side script (step 1 above).
2. Run **Commands → External commands → Poppet POC Tick Loop**.
3. While the POC is running, rotate the viewport, click controllers, drag the timeline. UI should stay responsive for 60+ seconds with `nc localhost 53145` holding the connection open.

If the UI freezes, file an issue with your Cascadeur version — the fallback path is the FBX-sync loop described in spec §5.

## License

MIT. See [LICENSE](LICENSE).
