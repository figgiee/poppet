# Poppet — Troubleshooting (1.0)

Issues ordered roughly by how often they hit first. Architecture:
[docs/architecture.md](docs/architecture.md).

## First move: check the link

```text
get_script_server_status()
# {connected, url, server_version, runtime_version, python, has_scene, ...}
# or {connected: false, error: "<actionable reason>"}
```

Terminal equivalent (no MCP client needed):

```bash
python -m poppet_mcp.cascadeur_connection
# {"ok": true, "health": {...}, "ping": {...}}
```

`ping` round-trips through the in-app runtime, so success proves the whole chain:
MCP server → Cascadeur script server → `poppet_rt` → `csc`.

## Cascadeur's script server is not started

Poppet cannot start it. In Cascadeur 2026.2.3+:

1. Open a scene.
2. **Scripts → MCP → Start script server**.
3. Event Log shows `[Cascadeur MCP] listening at http://127.0.0.1:8765/mcp`.

The server stops when Cascadeur exits, and a **script reload stops/restarts it**
(Cascadeur behaviour). After every restart or reload, start it again. If a tool says
`Cascadeur's built-in script server is not reachable at http://127.0.0.1:8765`,
this is the fix.

## Port 8765 is already in use

Another local app may own the port — on this machine's author environment the DSH
channel-pack does, so this is a common, real failure.

Symptoms:

- **Scripts → MCP → Start script server** silently fails, Event Log shows
  `WinError 10013`.
- Poppet raises *"Something other than Cascadeur's script server answered at …"*:
  `/health` returns someone else's JSON (often a 404), not `{"ok": true, ...}`.

Find the owner:

```powershell
netstat -ano | findstr :8765     # Windows
lsof -i :8765                    # macOS / Linux
```

Fix, in order:

1. Stop the conflicting app, then **Scripts → MCP → Start script server** again.
2. Run Cascadeur's script server on another port (no menu entry for this — start it
   from **Window → Python Console**):

   ```python
   import scripts.mcp.script_server.server as s
   import csc
   s.start(csc.app.get_application().current_scene().domain_scene(), "127.0.0.1", 8766)
   ```

   Set `POPPET_URL=http://127.0.0.1:8766` in the MCP client's env block and restart
   the client. *[needs live verification]* — mirrors the shipped API, not covered by
   the test suite.

## Error taxonomy: which layer broke?

| What you see | Meaning | Fix |
|---|---|---|
| `CascadeurNotRunning`: "not reachable … Start script server" / "connection refused" | Nothing listening | Start the script server; check `POPPET_URL` |
| `CascadeurProtocolError`: "Something other than … answered" | Another app owns the port | Port-conflict section |
| `CascadeurTimeout`: "accepted the request but did not answer within Ns" | Never reached `scene_idle`, or handler outlived the deadline | Close modal dialogs, settle the app, read state back, retry smaller work |
| `CascadeurScriptError` + **in-app traceback** | A `poppet_rt` handler raised inside Cascadeur | Read the traceback — it is Cascadeur's Python; often bad args or an unsupported API shape |
| `CascadeurProtocolError`: "empty 'value'" | Script server fell back to `exec` (statements, not an expression) | Typed tools should never do this; with `run_script`, submit one expression |
| `CascadeurProtocolError`: "bootstrap marker again" | In-app runtime failed to load | Restart Cascadeur; reinstall Poppet if it persists |

A timeout is **not** proof that nothing happened — handlers keep running after the
client gives up. Read back (`get_scene_info`, `read_telemetry`) before retrying.

## The ~30 s cap

Cascadeur's script server waits at most ~30 s for `scene_idle` and drops requests
that miss it. A handler that runs longer trips Poppet's timeout while it may still
be finishing in-app. Symptoms: slow AutoPhysics solves, big FBX exports, long bakes
or dense telemetry reads intermittently failing with `CascadeurTimeout`.

- Pass a small `timeout_sec` to `run_autophysics` (5–10 s) and poll afterwards.
- Chunk long work; checkpoint with `save_scene`; split large exports.
- After a timed-out export, wait, then check the file on disk and the Event Log.
- `POPPET_TIMEOUT` must stay **above** the server cap (default 35). Lowering it only
  fails sooner; raising it does not extend Cascadeur's cap.

## Stale in-app runtime

**After Cascadeur restart / script reload** — automatic: `poppet_rt` is gone and the
next call re-bootstraps it (slightly slower). **After upgrading Poppet** — normally
automatic too (the shipped `RUNTIME_VERSION` changes); if it was not bumped or tools
still behave like the old build, restart Cascadeur to clear `poppet_rt`, then start
the script server. **"runtime failed to load / bootstrap marker again"** — restart
Cascadeur; reinstall Poppet if it persists and report it.

## No scene open

Most handlers need an active scene. An empty Cascadeur window with no scene loaded
produces errors or empty results. Open a scene (the bundled `Cascy.casc` is the
reference target) and retry.

## `scene.modify*` failures and where Cascadeur logs them

Cascadeur's docs warn that `scene.modify_with_session` /
`modify_update_with_session` callbacks can raise while the outer call still reports
success. Poppet's runtime returns structured `status: "error"` for exceptions, but a
swallowed modify failure (callback raises, `modify*` returns `False`) can surface as
a partial/empty result instead.

Check Cascadeur's log right after a suspicious call:

```powershell
Get-Content "$env:LOCALAPPDATA\Nekki Limited\Cascadeur\logs\cascadeur_log.log" -Tail 80
```

## Tool-specific known issues

Flagged by the static 2026.2.3 audit
([docs/research/python-api-diff.md](docs/research/python-api-diff.md)); not all
re-verified live.

- **`get_active_layer` / `set_active_layer`** — Cascadeur's per-layer "active" notion
  is version-dependent and has no standard 2026.2 API (already broken in 2025.3.3).
  The response reports whether/how the concept was read; treat as experimental.
- **`set_layer_visible` / `set_layer_locked`** — audit flags argument order
  (`Editor.set_*_for_layer`); a call may report success without changing anything.
- **`list_layers`** — visibility/lock/object-count fields may be missing; id, name
  and key counts are reliable.
- **`get_object_hierarchy`, `delete_object`, `duplicate_object`** — audit flags the
  0.6 call shapes; may fail or no-op on 2026.2.3.
- **`screenshot_viewport`** — `RenderToFile.take_image` is believed to require render
  parameters in 2026.2; check `exists`, and keep the viewport visible (a minimized
  window may render nothing).
- **`set_current_frame`** — the setter accepts the value, but `current_frame`
  readback can lag one drain; trust the viewport, and prefer reading telemetry at
  explicit frame numbers over moving the playhead.
- **`import_fbx`** — wired but not exercised end-to-end against a real FBX; verify
  visually.

## FBX export issues

Absolute paths with forward slashes (`C:/work/out.fbx`); the parent directory must
exist; avoid protected locations such as `Program Files`. A near-empty FBX usually
means no scene was loaded or the export outlived the cap — `Cascy.casc` yields ~2.9 MB.

## Poppet doesn't appear in my MCP client

Confirm the command (`uvx poppet-mcp`, or `python -m poppet_mcp.server` for a local
install), Python 3.11+ and `mcp>=1.0.0`, then restart the client (most read config
only at start). Run the exact configured command in a terminal — a traceback there
is the real error.

## Still stuck

Collect the tool call, full error text (including in-app traceback),
`get_script_server_status()` output, `python -m poppet_mcp.cascadeur_connection`
output, and the tail of
`%LOCALAPPDATA%\Nekki Limited\Cascadeur\logs\cascadeur_log.log`. File an issue:
<https://github.com/figgiee/poppet/issues>.
