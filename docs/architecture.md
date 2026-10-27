# cascadeur-mcp architecture (1.0)

cascadeur-mcp 1.0 is a typed MCP front end over **Cascadeur 2026.2's built-in MCP script
server**. The Cascadeur side of cascadeur-mcp has no install step: it is source text that
the MCP server ships into Cascadeur on the first tool call and executes as a
private module (`poppet_rt`).

## TL;DR

```
MCP client ──stdio──▶ cascadeur-mcp ──HTTP 127.0.0.1:8765──▶ Cascadeur script server
                                                             │ scene_idle
                                                             ▼
                                                    poppet_rt (in-app runtime)
                                                             │  csc.* / scene.*
                                                             ▼
                                                     the running Cascadeur scene
```

- `cascadeur-mcp` is a FastMCP stdio server (Python 3.11+, `pip`/`uvx`); it talks
  loopback HTTP to Cascadeur's script server (`GET /health`, `POST /run`)
- The server evaluates one Python expression on the next `scene_idle` event on
  Cascadeur's Qt main thread and returns its value's `repr`; cascadeur-mcp submits one
  expression that dispatches to / bootstraps `poppet_rt`
- No user_scripts copy, no `settings.json` edits, no menu commands, no queue, no
  window-focus requirement

## Why the built-in server

Cascadeur 2026.2 (August 2026) added a vendor script server (**Scripts → MCP → Start
script server**) that removes the two problems that forced cascadeur-mcp 0.x into a file-queue
design: code now runs on the main thread inside a `scene_idle` event (the same safe
context as bundled commands, with background-thread starvation no longer cascadeur-mcp's
problem), over a stable loopback HTTP transport instead of request files in
`%LOCALAPPDATA%`, event hooks, a manual drain menu and a Windows focus nudge.

The trade-off: the server exposes exactly **one tool** (`run_script`) and returns
raw Python results — no typed tools, workflow semantics, safety classification, or
long-operation support, and a hard ~30 s cap. That gap is cascadeur-mcp's reason to exist.

## The eval-expression trick

Cascadeur's server compiles submitted code with `mode="eval"` first, falling back to
`mode="exec"` on `SyntaxError`. The paths return different things:

| Path | Server response |
|---|---|
| `eval` | `{"ok": true, "value": "<repr of value>", "messages": [...]}` |
| `exec` | `{"ok": true, "value": "", ...}` — statements return no data |

cascadeur-mcp needs data back, so every submission is **one expression**. Arbitrarily
large programs are wrapped in a lambda that execs them in a private namespace and
yields a result variable (`src/poppet_mcp/_expression.py`):

```python
(lambda __ns__: (
    exec(compile(<program>, "<cascadeur-mcp>", "exec"), __ns__),
    __ns__.get("__cascadeur-mcp_result__"),
)[1])({"csc": csc, "scene": scene, "app": app})
```

`csc`, `scene` and `app` come from the namespace the script server already injects,
so the wrapped program has bundled-script privileges. The result must be a `str`;
the runtime returns JSON text, and the MCP side decodes it in three steps:
`ast.literal_eval(value)` → `json.loads(...)`.

## Request lifecycle

1. An MCP client calls a tool, e.g. `get_scene_info()`.
2. `poppet_mcp.server` calls `CascadeurConnection.request("scene_info", {})`.
3. The connection builds the dispatch expression: if the loaded runtime's
   `RUNTIME_VERSION` matches the client's expectation, the program calls
   `poppet_rt.dispatch(...)`; otherwise it returns a one-key bootstrap marker
   (`{"__cascadeur-mcp_bootstrap_required__": true}`) instead of failing.
4. `POST /run` with the wrapped expression (`POPPET_TIMEOUT`, default 35 s).
5. Cascadeur's server waits for `scene_idle` (its own ~30 s cap), runs the
   expression on the Qt thread, and returns `{"ok": ..., "value": "<repr>", ...}`.
6. The client decodes `value` → JSON payload → `{"status": "success", "result": ...}`
   or `{"status": "error", "message", "traceback"}`; `CascadeurScriptError` is raised
   for the error case, carrying the in-app traceback.
7. If step 6 saw the bootstrap marker, the client re-submits once with the bootstrap
   expression and dispatches in the same request.

Handlers live on the Cascadeur side deliberately: mutations need
`scene.modify_with_session(...)` / `modify_update_with_session(...)` for undo, and
should run in the `scene_idle` context. Prompts only see typed tool arguments.

## Runtime bootstrap and versioning

- The runtime is `src/poppet_mcp/runtime/inapp.py`; its source text (~70 KB) is
  shipped verbatim and is never imported by the MCP server process.
- Two identities come from that one file: `RUNTIME_VERSION` (human-readable, reported
  by `get_script_server_status`) and `SOURCE_DIGEST`, the SHA-256 of the exact source
  text.
- `SOURCE_DIGEST` is the wire-contract identity: the client only trusts a loaded
  `poppet_rt` whose stamped digest matches the source it would ship.
- Bootstrap program: if `sys.modules["poppet_rt"]` is missing **or its stamped digest
  differs**, create a fresh module, `exec` the shipped source into it, stamp the
  digest, register it in `sys.modules`, then dispatch.
- Consequences: a Cascadeur restart clears the in-memory module (the next call
  re-bootstraps). A script reload leaves it alone — which is safe because the digest
  check re-bootstraps on the first call after any cascadeur-mcp upgrade. No manual cache
  clearing and no version-bump discipline required. The first call after either event
  is slower; later calls are compact JSON.

## Safety model

- **Loopback only.** The script server binds `127.0.0.1`; cascadeur-mcp never exposes it.
  Anything that can reach port 8765 can run arbitrary Python in Cascadeur — that is
  Cascadeur's trust model, and cascadeur-mcp does not widen it. Don't port-forward it.
- **No auth, no TLS.** Local-only by design; loopback traffic bypasses system proxies
  (`urllib.request.ProxyHandler({})`) so proxy config cannot leak requests.
- **Arbitrary code is explicit.** `execute_csc_code` and `run_script` execute
  caller-supplied Python by definition. Everything else is a fixed handler with a
  fixed parameter schema; the runtime dispatches only known command names and returns
  a structured error otherwise.
- **No persistent Cascadeur-side state by default.** The core flow writes nothing to
  `user_scripts/` or `settings.json`; the only in-app artefact is `poppet_rt` in Python
  memory, gone on restart. The optional `cascadeur-autostart` add-on is the single
  opt-in exception (a 3-file event package + one `Python.Events` entry, uninstallable).
- **Undo.** Mutations go through `scene.modify*`, so they appear as normal Cascadeur
  undo steps; `undo()`/`redo()` wrap the menu actions.

## Failure modes

| Symptom | Layer | Cause |
|---|---|---|
| `CascadeurNotRunning` — "not reachable … Start script server" | transport | Cascadeur closed, server stopped, wrong port |
| `CascadeurProtocolError` — "Something other than … answered" | transport | another app owns 8765; `/health` is not `{"ok": true, ...}` or 404s |
| `CascadeurTimeout` — "accepted the request but did not answer within Ns" | transport + host | never reached `scene_idle`, or the handler outlived the deadline |
| `CascadeurScriptError` + traceback | in-app | handler raised inside `poppet_rt`; the traceback is Cascadeur's |
| `/health` times out, port is listening, Event Log says "listening" | host | bootstrap keeper not installed (GIL stall — see above) |
| `CascadeurProtocolError` — "empty 'value'" | protocol | server fell back to `exec`; a non-expression slipped past the wrapper |
| `CascadeurProtocolError` — "bootstrap marker again" | protocol | runtime failed to load |

Timeouts are not proof the mutation did not happen. Read state back before retrying;
see [TROUBLESHOOTING.md](../TROUBLESHOOTING.md).

### The embedded-interpreter stall (why bootstrap exists)

Live-verified 2026.2.3 behaviour: the script server's HTTP handler thread starves while
Cascadeur is idle. Cascadeur's embedded interpreter keeps the GIL inside the Qt idle
loop, so the background thread cannot accept a connection or answer one; connections
queue in the listen backlog until they time out, and `/run` scripts never reach the
`scene_idle` callback they wait for. Menu-started servers therefore print "listening"
but are unreachable until Python happens to run on the main thread.

cascadeur-mcp's `cascadeur-bootstrap` (printed by `cascadeur-bootstrap`, pasted once per Cascadeur
launch) fixes both halves from inside the app:

- starts/stops the built-in server on a free port (menu default 8765, walking upward),
- installs a 10 ms PySide `QTimer` whose slot calls `events.scene_idle_manager.run(scene)`
  — this keeps the interpreter cycling the GIL *and* drives the queue drain.

The timer lives in Cascadeur's Python memory only; nothing is written into
`user_scripts/`. The chosen port goes to `%LOCALAPPDATA%\cascadeur-mcp\server.json`, which
the client reads when `POPPET_URL` is unset.

**Optional add-on — zero-touch autostart.** `cascadeur-autostart --install` writes a
small `user_scripts/poppet_autostart` event package (handlers on `scene_created`,
`scene_opened`, `scene_activated`, plus a harmless `application_started` handler for
future builds) and adds one entry to `settings.json` `Python.Events` after writing a
backup. Each handler executes the same bootstrap file and returns early when the
server is already running, so the several scene events at launch start it exactly
once. A cold-start probe on 2026.2.3 showed user handlers receive `scene_created` and
`scene_activated` but never `application_started`; the retry handlers exist for that
reason. This is convenience only: the default flow remains the one-line console
paste, and the add-on can be removed again with `cascadeur-autostart --uninstall`.

### The ~30 s cap

The script server's `_queue_script` waits at most 30 s for the next idle event and
drops requests that miss it. A handler running longer trips cascadeur-mcp's client timeout
while it may still finish in-app. Keep calls short, split long work, use a small
`run_autophysics(timeout_sec=...)` (5–10 s) and poll. Large exports may exceed the
cap; verify the file before retrying.

## Port conflict (8765 already in use)

The tell is a `/health` reply that is not Cascadeur's `{"ok": true, "version": ...}`
(often a 404 from another local tool). Find the owner with `netstat -ano | findstr
:8765` (Windows) or `lsof -i :8765` (macOS/Linux). Fixes: stop the conflicting app
and start the server again, or start Cascadeur's server on another port from
**Window → Python Console**:

```python
import scripts.mcp.script_server.server as s
import csc
s.start(csc.app.get_application().current_scene().domain_scene(), "127.0.0.1", 8766)
```

Then set `POPPET_URL=http://127.0.0.1:8766` and restart the client. *[needs live
verification]* — mirrors the shipped API, not covered by the test suite. Some
developer tools occupy 8765 on the author's machine (the DSH channel-pack is one).

## History: why the 0.x file queue existed

cascadeur-mcp 0.x targeted Cascadeur 2025.3.3, whose embedded Python had no PySide, no
main-thread scheduler and starved background threads. An in-app TCP listener was
impossible, so 0.x wrote request JSON files into `%LOCALAPPDATA%\cascadeur-mcp\` and
relied on a `user_scripts/` package plus `scene_activated` hooks or a
**Commands → cascadeur-mcp → Process Pending** click to drain them — workable, but it needed
a Cascadeur-side install, a manual drain fallback, a focus nudge, and paid a file-I/O
round trip per call. Cascadeur 2026.2 removed all three constraints; the queue,
install, menu commands and nudge are gone in 1.0. Legacy design:
[v0.6.0 release](https://github.com/figgiee/poppet/releases/tag/v0.6.0).

## Testing strategy

- **Protocol tests run against Cascadeur's real server code, offline.**
  `tests/native_server_harness.py` loads the shipped
  `resources/scripts/python/scripts/mcp/script_server/server.py` from the local
  Cascadeur install, substitutes fake `csc`/`events` modules (including a fake
  `scene_idle_manager` driving the queue from a thread), and starts it on an
  ephemeral port. Tests are skipped when Cascadeur is absent (e.g. CI).
- `tests/test_native_protocol.py` covers `/health`, bootstrap-on-first-call, runtime
  reuse, re-bootstrap after module loss, unknown commands, in-app tracebacks,
  `run_script` raw pass-through, connection-refused messaging and port-conflict
  detection.
- Unit tests cover the expression wrapper, runtime loader/version parse, connection
  error mapping and handler routing with a mocked `csc`.
- Not covered offline: real `csc.*` behaviour (rig edits, solves, export) — that
  needs a live session, which is what the README's `expected` / `known risk` markers
  refer to.

Out of scope: headless/batch Cascadeur (the server needs a GUI event loop), remote or
multi-user MCP (stdio + loopback only), Cascadeur 2025.3.x (use 0.6), authentication
(local same-user trust model).
