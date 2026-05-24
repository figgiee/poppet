# Poppet architecture deep dive

This is the long version of the README's architecture section. Read it if you want to understand why the design looks the way it does — or if you're considering forking for a different DCC app.

## TL;DR

Two processes, three files, one polling loop.

- **`poppet-mcp`** runs out-of-process. Modern Python 3.11+. Speaks MCP stdio to Claude (or any MCP client). Knows nothing about Cascadeur except where its `%LOCALAPPDATA%` directory is.
- **`poppet`** package lives in Cascadeur's `user_scripts/` directory. Runs inside Cascadeur's embedded Python 3.8 interpreter. Speaks Cascadeur's `csc.*` API directly.
- They talk by writing `request<uuid>.json` and `response<uuid>.json` files to `%LOCALAPPDATA%\poppet-mcp\`. The MCP server writes requests, polls for responses. Cascadeur drains the requests directory whenever a `scene_activated` / `scene_opened` event fires (or whenever a user clicks `Commands → Poppet → Process Pending`).

## Why not sockets?

This was the v0 design, and it died fast against three independent constraints:

1. **No PySide bundled in Cascadeur 2025.3.3.** Cascadeur is a Qt6/C++ app with an embedded CPython 3.8, but Python has zero PySide. So no `QTimer`, no `QApplication.instance()`, no `QMetaObject.invokeMethod`.

2. **No csc-side main-thread scheduler.** We grep'd 115 candidate methods on `csc.*` looking for something like `post_to_main_thread(callable)` or `schedule_on_qt(...)`. Nothing matches. `csc.update.SceneUpdater` is a DAG of attributes, not an event loop.

3. **Background Python threads only run their first GIL slice.** We verified this with a minimal `threading.Thread(target=lambda: while True: time.sleep(0.1); print("tick"))`. The first `print` fires; the second never does. Something in Cascadeur's embedded interpreter starves background threads indefinitely (probably a custom GIL host or a Qt thread that holds the GIL forever).

So a TCP listener inside Cascadeur is impossible — there's no way to accept connections in the background.

## What the file-sync design buys us

Every operation routes through Cascadeur's normal command-invocation path. When a user clicks a menu item, Cascadeur calls the command's `run(scene)` function on the Qt main thread, with full csc.* access. We piggyback: our `Poppet.Process Pending` command runs on every drain, reads the queue, dispatches each request via `_dispatchers.dispatch(message, scene)`, and writes a response file.

This gives us:

- **No background threads.** Everything runs on the main thread under Cascadeur's existing command machinery.
- **Undo support.** Mutations go through `scene.modify_with_session(label, mod)` or `scene.modify_update_with_session(label, mod)` — same as bundled commands — so they appear as proper Cascadeur undo steps.
- **Atomic responses.** Responses are written to `<uuid>.json.tmp` then renamed to `<uuid>.json`, so a polling reader never sees half-written JSON.
- **Survives Cascadeur restarts.** If Cascadeur crashes mid-drain, the unprocessed request files stay in the queue and drain on the next start.

The cost is a per-request floor of ~25ms (write request, poll, read response). For a 50-request batch that's ~1.2s end-to-end — slow vs. a hot socket round-trip, but invisible inside a conversational Claude session where each turn is already taking ~5s of LLM latency.

## Auto-drain via `scene_activated`

Cascadeur fires `scene_activated` events whenever a scene tab gains focus. Crucially this includes when the Cascadeur **window** regains focus. We register a handler:

```text
cascadeur_side/poppet_events/scene_activated/poppet_drain.py
    └─ run(scene): poppet.process_pending.run(scene)
```

…and register `poppet_events` in `settings.json` `Python.Events`. Cascadeur's bundled `events_rule.py` walks the package tree once at startup via `pkgutil.walk_packages`, discovers our handler, and wires it to the event.

The result: any time the MCP server queues requests and the user clicks back into the Cascadeur window, the queue drains automatically. Most flows feel autonomous; the manual `Process Pending` menu is a fallback for cases where the user doesn't click back (e.g., MCP server invoked from a script with no window switch).

We also register a `scene_opened` handler so freshly-loaded scenes drain on load.

## The Windows-API auto-nudge

`src/poppet_mcp/_nudge.py` tries to bring Cascadeur's window to the foreground via `SetForegroundWindow` after writing a request. The intent: trigger `scene_activated` without requiring the user to click.

It works inconsistently because of Windows focus-stealing prevention — `SetForegroundWindow` is silently denied when the MCP server process doesn't already have focus. We treat the nudge as best-effort: queue the request, try to nudge, and if it fails the user is the fallback.

## Why this design works for Cascadeur but not Blender

Blender has `bpy.app.timers.register(callable, first_interval=0.1)` — a clean main-thread scheduler. Blender MCP uses it to host a real TCP listener inside Blender. We can't do that in Cascadeur 2025.3.3.

If a future Cascadeur version ships PySide or exposes a main-thread scheduler, the socket design becomes viable and Poppet could switch to it for the per-request latency win. Until then, file-sync is the only working architecture.

## Why dispatchers try multiple API call shapes

Cascadeur's `csc.*` API drifts between versions — method names rename, signatures shift, modules move. Our dispatchers defend against this by trying a small set of candidate call shapes and reporting which one worked:

```python
for label, attempt in (
    ("dsm.save_scene(cur, path)", lambda: dsm.save_scene(cur, normalized)),
    ("dsm.save_scene(path, cur)", lambda: dsm.save_scene(normalized, cur)),
    ("dsm.save(cur, path)", lambda: dsm.save(cur, normalized)),
    ("cur.save(path)", lambda: cur.save(normalized)),
):
    try:
        attempt()
        method = label
        last_err = None
        break
    except Exception as e:
        last_err = f"{label}: {type(e).__name__}: {e}"
```

This way:

- If Cascadeur 2025.3.4 renames `save_scene` to `persist_scene`, our dispatcher fails gracefully and the `method` field in the response surfaces which signatures we tried.
- If a method's argument order swaps, we typically hit the right variant in the second or third attempt.
- The MCP tool surface stays stable — Claude calls `save_scene(path)` and gets back a structured response either way.

## Files you'd touch to add a new tool

| File | Role |
|---|---|
| `cascadeur_side/poppet/_dispatchers.py` | Add `_d_your_tool(params, scene)` and register in `_HANDLERS` |
| `src/poppet_mcp/server.py` | Add `@mcp.tool() def your_tool(...)` — Claude-facing surface |
| `tests/test_new_dispatchers.py` | Validation tests for the dispatcher |
| `tests/test_mcp_server.py` | Routing test that the MCP wrapper forwards correctly |
| `README.md` | Add a row to the verified-tools table |
| `CHANGELOG.md` | Under `## [unreleased]` (or the next planned version) |

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full workflow including the Python 3.8 compat rules.

## What's not in scope

- **Headless Cascadeur.** We don't run Cascadeur in batch mode — it needs a UI for the event-loop to tick. If Nekki ever ships a headless build, the file-sync design needs no changes; you just lose the auto-drain because there's no window focus event.
- **Cross-machine MCP.** stdio transport assumes the MCP server and Cascadeur live on the same machine (file-sync needs shared `%LOCALAPPDATA%`). For a multi-machine setup you'd swap the file-sync layer for HTTP + a shared queue.
- **Authentication.** The file-sync dir is per-user, so an attacker who can write to `%LOCALAPPDATA%\poppet-mcp\requests\` can already do anything in Cascadeur. We rely on OS-level filesystem perms.
