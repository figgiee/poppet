# MCP client configuration snippets

cascadeur-mcp 1.0 is a **single stdio MCP server** (`cascadeur-mcp`). There is no
Cascadeur-side install: register the server in your client and start Cascadeur's
script server (**Scripts → MCP → Start script server**).

Install flavours:

- **uvx** — `uvx cascadeur-mcp` (needs [uv](https://docs.astral.sh/uv/), no pre-install).
- **pip** — `pip install cascadeur-mcp`, then command `cascadeur-mcp` (or
  `python -m poppet_mcp.server`).

The snippets below use uvx; replace `"command": "uvx"` / `"args": ["cascadeur-mcp"]`
with `"command": "cascadeur-mcp"` for a pip install.

## Claude Code (CLI)

```bash
claude mcp add cascadeur-mcp -- uvx cascadeur-mcp
```

Local dev checkout:

```bash
claude mcp add cascadeur-mcp -- C:/Users/you/cascadeur-mcp/.venv/Scripts/python.exe -m poppet_mcp.server
```

## Claude Desktop

Edit `claude_desktop_config.json` (Windows: `%APPDATA%\Claude\claude_desktop_config.json`,
macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "cascadeur-mcp": { "command": "uvx", "args": ["cascadeur-mcp"] }
  }
}
```

## Cursor

`~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (per project):

```json
{
  "mcpServers": {
    "cascadeur-mcp": { "command": "uvx", "args": ["cascadeur-mcp"] }
  }
}
```

## Windsurf

`~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "cascadeur-mcp": { "command": "uvx", "args": ["cascadeur-mcp"] }
  }
}
```

## VS Code

`.vscode/mcp.json` (workspace) or the user-level config — VS Code uses `servers`
and an explicit `type`:

```json
{
  "servers": {
    "cascadeur-mcp": { "type": "stdio", "command": "uvx", "args": ["cascadeur-mcp"] }
  }
}
```

## Environment variables

| Env var | Default | What it does |
|---|---|---|
| `POPPET_URL` | `http://127.0.0.1:8765` | Script server base URL. Set when the server runs on another port (port-conflict workaround). |
| `POPPET_TIMEOUT` | `35` | Seconds the MCP server waits for a tool response. Keep above Cascadeur's ~30 s cap. |

Set per client in the `env` block:

```json
{
  "mcpServers": {
    "cascadeur-mcp": {
      "command": "uvx",
      "args": ["cascadeur-mcp"],
      "env": {
        "POPPET_URL": "http://127.0.0.1:8766",
        "POPPET_TIMEOUT": "45"
      }
    }
  }
}
```

## Verifying the setup

1. Cascadeur: **Scripts → MCP → Start script server**; Event Log shows
   `[Cascadeur MCP] listening at http://127.0.0.1:8765/mcp`.
2. Terminal probe (venv where `cascadeur-mcp` is installed):

   ```bash
   python -m poppet_mcp.cascadeur_connection
   # {"ok": true, "health": {...}, "ping": {...}}
   ```

3. MCP client: list tools (45 expected), call `get_script_server_status()` and
   `get_scene_info()`. The first call bootstraps the in-app runtime, so it is slower.

If the client shows no `cascadeur-mcp` server, run the configured command in a terminal —
the traceback there is the real error. See [TROUBLESHOOTING.md](../TROUBLESHOOTING.md).

## Cascadeur-side prerequisites

No Cascadeur-side install is needed, but every Cascadeur session needs the bootstrap:

```bash
uvx cascadeur-bootstrap
```

Paste the printed `exec(open(...))` line into **Window → Python Console** and Execute.
The bootstrap starts the built-in script server on a free port (8765 by default),
installs the 10 ms interpreter keeper, and writes the chosen port to
`%LOCALAPPDATA%\cascadeur-mcp\server.json`. `cascadeur-mcp` reads that file, so no
`POPPET_URL` is normally required. Set `POPPET_URL` (and `POPPET_SERVER_PORT` before
bootstrapping) only for custom setups.
