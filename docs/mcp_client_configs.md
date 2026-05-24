# MCP client configuration snippets

Copy-paste-able configuration for the major MCP clients. Adjust the install
command to your environment (`uvx poppet-mcp` once published to PyPI;
`pip install -e .` then `python -m poppet_mcp.server` for a local dev install).

## Claude Code (CLI)

```bash
claude mcp add poppet -- uvx poppet-mcp
```

Or for a local dev install:

```bash
claude mcp add poppet -- C:/Users/you/poppet/.venv/Scripts/python.exe -m poppet_mcp.server
```

## Claude Desktop

Append to `claude_desktop_config.json` (Windows: `%APPDATA%\Claude\claude_desktop_config.json`, macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "poppet": {
      "command": "uvx",
      "args": ["poppet-mcp"]
    }
  }
}
```

For a local dev install on Windows:

```json
{
  "mcpServers": {
    "poppet": {
      "command": "C:\\Users\\you\\poppet\\.venv\\Scripts\\python.exe",
      "args": ["-m", "poppet_mcp.server"]
    }
  }
}
```

## Cursor / Windsurf / other VSCode-based MCP clients

Most use the same `claude_desktop_config.json` shape — drop the snippet above into the client's MCP config file.

## Environment variables

All of the above honor:

| Env var | Default | What it does |
|---|---|---|
| `POPPET_TIMEOUT` | `60` | Seconds to wait for a response from Cascadeur before raising. Bump this if AutoPhysics convergence takes longer than 60s on big rigs. |
| `POPPET_POLL_INTERVAL` | `0.1` | Seconds between response-file polls. Lowering shortens latency, raising reduces CPU. |
| `LOCALAPPDATA` | (set by Windows) | Used to locate `%LOCALAPPDATA%\poppet-mcp\` (the request/response queue). |

Set them per-client via `env` in your MCP config:

```json
{
  "mcpServers": {
    "poppet": {
      "command": "uvx",
      "args": ["poppet-mcp"],
      "env": {
        "POPPET_TIMEOUT": "120"
      }
    }
  }
}
```

## Smoke-testing the config

Before wiring in your MCP client, verify the server starts and lists tools:

```bash
python scripts/mcp_smoke_test.py
# Should print: "MCP initialize OK" + "39 tools registered" + "1 resources registered"
```

If you see fewer tools or an import error, check:

1. `pip install -e .` (or `uvx poppet-mcp`) succeeded
2. Python is 3.11+
3. The `mcp` package version is `>=1.0.0`

## Pairing with the Cascadeur-side install

Whichever MCP client you wire up, the Cascadeur side needs to be installed too — Poppet is a two-component system. From the repo root:

```powershell
# Windows
.\scripts\install.ps1
```

```bash
# macOS / Linux
./scripts/install.sh
```

Then restart Cascadeur. Verify:

- `Commands → Poppet → Process Pending` (manual drain) appears
- `Commands → Poppet → Status / Drain Dialog` (queue inspector) appears
- `Commands → Poppet → Refresh Schema` (regenerates `csc_schema.json`) appears

If the events handler is installed, focus the Cascadeur window once after queueing a request — `scene_activated` fires and drains the queue automatically.
