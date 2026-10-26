# Troubleshooting

Start here: `get_script_server_status()` in your MCP client tells you whether the
cascadeur-mcp side can see Cascadeur, and which URL/runtime version it is using.

## "not reachable" / connection refused

The MCP client can't reach Cascadeur's script server.

1. Is Cascadeur 2026.2.3+ running with a **scene open**?
2. Did you run the bootstrap in **Window → Python Console** this Cascadeur session?

   ```bash
   uvx cascadeur-bootstrap           # prints the exact exec(open(...)) line
   ```

   Event Log should show:

   ```
   [cascadeur-mcp] script server ready at http://127.0.0.1:8765/mcp
   [cascadeur-mcp] interpreter keeper installed (10 ms); keep Cascadeur open
   ```

3. If `[cascadeur-mcp] bootstrap failed` appears, read the traceback below it. The most
   common cause is that `%LOCALAPPDATA%\cascadeur-mcp\` is not writable for the
   Cascadeur process; run `uvx cascadeur-bootstrap --write <a path you own>` and paste
   that file's line instead.

## The server says "listening" but every call times out

This is the 2026.2.3 embedded-Python limitation cascadeur-mcp's bootstrap exists for:
Cascadeur holds the GIL in its Qt idle loop, so the built-in server's background
thread can't accept or answer requests while the app is idle. Symptom: Event Log says
`[Cascadeur MCP] listening at ...`, but connections hang and the port's accept queue
eventually stops accepting new ones.

Fix: run the bootstrap (it installs the 10 ms PySide keeper timer). If you started the
server from **Scripts → MCP → Start script server** instead, the bootstrap will stop it
and restart it on a hosted port; run the bootstrap line.

## Another program owns port 8765

Symptom: `get_script_server_status()` reports a protocol error, or `/health` returns
something that isn't `{"ok": true, "version": ...}`. On Windows, Cascadeur's
`SO_REUSEADDR` listener can even appear to start while the other program keeps
answering the port.

Fix: run the bootstrap. It walks upward from 8765 to the first free port, starts
Cascadeur's server there, and writes `%LOCALAPPDATA%\cascadeur-mcp\server.json` so
`cascadeur-mcp` finds it. If the port changes later, the file is updated on every
bootstrap run. To start from a preferred port:

```powershell
$env:POPPET_SERVER_PORT = "8766"
uvx cascadeur-bootstrap
```

## Timeouts on a single tool call

Cascadeur's script server allows a request ~30 s between the HTTP call and the next
`scene_idle` execution. A handler that runs longer looks like a timeout even though it
may still finish in-app. cascadeur-mcp raises `CascadeurTimeout` with that explanation.

- Read state back before retrying a mutation.
- `run_autophysics(timeout_sec=...)` — keep the budget at ~25 s or less and poll.
- Large FBX exports may need splitting or a retry.

## In-app tracebacks

A tool error that includes `In-app traceback:` came from Python inside Cascadeur —
that's the real error location. Cascadeur's own log at
`%LOCALAPPDATA%\Nekki Limited\Cascadeur\logs\cascadeur_log.log` often has more context
(including `scene.modify*` callback failures, which Cascadeur logs but does not raise).

## Stale runtime after upgrading cascadeur-mcp

Not a thing to fix: the in-app runtime is stamped with the SHA-256 of its exact source.
When the client ships a different runtime, the next call re-bootstraps automatically.
After upgrading cascadeur-mcp you can keep Cascadeur open. If a tool errors with a bootstrap
marker error, restart Cascadeur and re-run the bootstrap line.

## "no scene" / handlers fail on scene state

Most tools need an open scene. `get_script_server_status()` reports `has_scene`; open
a scene in Cascadeur before calling scene tools.

## Duplicate object fails

`duplicate_object` is a known issue on Cascadeur 2026.2.3 (the clipboard paste modify
callback fails). Workaround: run Cascadeur's own bundled command through
`execute_csc_code` after selecting the object:

```python
import commands.copy_paste_objects.duplicate as dup
dup.run(scene)
```

## The client doesn't list cascadeur-mcp

- Run the same command your client runs (`uvx cascadeur-mcp`) from a terminal; a client
  configured with a different Python environment won't see the package.
- `uvx` resolves the published package; for local development use
  `python -m poppet_mcp.server` with an absolute interpreter path.
- MCP client logs (Claude Desktop: `%APPDATA%\Claude\logs\`) show handshake errors.

## Removing cascadeur-mcp

Nothing is installed into Cascadeur, so there is nothing to uninstall there. Stop using
`cascadeur-mcp` in your client config; the bootstrap's only artefacts are the file it
writes and `%LOCALAPPDATA%\cascadeur-mcp\server.json`.
