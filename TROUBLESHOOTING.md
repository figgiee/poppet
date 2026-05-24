# Poppet — Troubleshooting

Known issues, their causes, and the fix. Issues are roughly ordered by how often they hit first-time users. For background on the architecture and why Poppet works the way it does, see [README.md](README.md).

## Cascadeur won't start after install

`install.ps1` rewrites `settings.json` to add Poppet to `Python.Path` and `Python.Commands`. If something corrupted the file (bad JSON, missing field, ScriptsDir replaced with a custom path), Cascadeur FATAL-crashes on launch — most often because the bundled `parts` rig data goes missing.

The installer backs the original up to `settings.json.bak` on first run. Restore it:

```powershell
$cfg = Join-Path $env:LOCALAPPDATA "Nekki Limited\Cascadeur"
Copy-Item -Path (Join-Path $cfg "settings.json.bak") `
          -Destination (Join-Path $cfg "settings.json") -Force
```

Then launch Cascadeur to confirm it boots clean, and re-run `install.ps1`. If the backup is also broken, delete `settings.json` entirely — Cascadeur will regenerate a default on next launch.

## Process Pending menu doesn't appear

After install, `Commands → Poppet → Process Pending` should be in the menu. If it's not:

1. **Did you restart Cascadeur?** Settings are loaded once at launch. Restart, don't just reopen a scene.
2. **Did the script actually copy to the right place?** Verify:

   ```powershell
   ls "$env:LOCALAPPDATA\Nekki Limited\Cascadeur\user_scripts\poppet"
   ```

   You should see `__init__.py`, `process_pending.py`, `refresh_schema.py`, `_dispatchers.py`, `_paths.py`, `_introspect.py`. If the directory is empty or missing, re-run `install.ps1` from the repo root and read its output — it logs every copy step.

3. **Is `poppet` in the settings command list?** Open `settings.json` and look for:

   ```json
   "Python": {
     "Path":     ["...user_scripts"],
     "Commands": ["...", "poppet"]
   }
   ```

   If `poppet` is missing from `Commands`, the script's settings patch silently failed. Re-run `install.ps1`.

4. **Did you launch the same Cascadeur the script targeted?** The installer writes to `%LOCALAPPDATA%\Nekki Limited\Cascadeur`. If you have multiple Cascadeur installs or a portable one with a different config dir, Poppet's menu won't appear in that build.

## Tool call times out

The MCP server polls for a response file for `POPPET_TIMEOUT` seconds (default 60). If Cascadeur never drains the request, the call raises:

```
Cascadeur did not respond within 60s. Is Cascadeur running and did
'Commands -> Poppet -> Process Pending' get clicked?
```

In order of likelihood:

1. **You didn't click Process Pending.** Auto-nudge is best-effort — it tries to push the menu sequence via Windows API but is blocked by focus-stealing prevention (next section). The reliable fallback is always: click `Commands → Poppet → Process Pending` in Cascadeur yourself.
2. **Cascadeur isn't running**, or doesn't have a scene loaded. Several dispatchers expect a real `scene` object — open Cascy or any other scene first.
3. **The dispatcher crashed mid-drain.** Check `%LOCALAPPDATA%\poppet-mcp\dispatcher.log` for tracebacks. If you see one, the request file usually stays in `requests/` (re-drainable) but no response was written.
4. **Set a longer timeout** for slow operations (long AutoPhysics solves, large FBX exports): `POPPET_TIMEOUT=300 uvx poppet-mcp`.

## `set_current_frame` doesn't move the playhead

Known issue in Cascadeur 2025.3.3, documented in `_dispatchers.py::_d_frame_set`. Both `scene.set_current_frame()` and `session.set_current_frame()` accept the value but `get_current_frame()` reads back the prior frame — the playhead doesn't actually move. The real setter is likely on `csc.view.Scene.animation_boundary` or requires a UI message dispatch Poppet hasn't found yet.

The tool returns `{requested, current_frame, persisted: false, note: "..."}` so you can detect it.

Workarounds:

- Try `call_action(action_id="Timeline.Play")` and pause, or scrub via the timeline action set.
- For now, design your workflow around the current playhead rather than fighting it — set sparse keys at known frame indexes, let `read_telemetry(frames=[...])` sample what you need, skip the explicit playhead move.

## FBX export reports success but file is empty/missing

`export_fbx` returns `{exists: true, size_bytes: N}` when it works. If you get `exists: false` or a zero-byte file:

- **Use an absolute path with forward slashes.** Cascadeur's FBX loader is finicky about backslash escaping — `C:/work/out.fbx` is safe, `C:\work\out.fbx` may not be.
- **The parent directory must exist.** Poppet doesn't `mkdir -p` for you.
- **Cascadeur's process needs write permission.** If you're exporting under `Program Files` or another protected location, pick somewhere in your user profile instead.
- **Confirm a scene is open.** Exporting an empty scene produces a near-empty FBX.

The bundled `Cascy.casc` scene exports to a ~2.9 MB binary FBX as a baseline — if yours is dramatically smaller, the scene probably wasn't loaded.

## `import_fbx` behavior is undefined

`import_fbx` is wired to `FbxLoader.import_scene` / `import_animation` but has not been exercised end-to-end against a real FBX in the verified demo flow. The signature works; the semantics (which `target` mode does what, how it interacts with the existing scene) haven't been pinned down.

Use at your own risk. If you hit something weird, file an issue with the FBX file and the call you made.

## `set_controller_position` on `pelvis` doesn't visibly move anything

Cascy (and any Cascadeur biped) has two parallel object hierarchies:

- **Joints** (`pelvis`, `thigh_l`, `spine_01`) — the underlying skeleton bones.
- **Controllers** (`pelvis_Box`, `foot_Box_l`, `hand_Box_r`) — the `_Box`-suffixed objects that AutoPosing drives.

You want the `_Box` variant. Setting a position on the bare joint may technically succeed (the dispatcher writes to it) but it's not what gets read by AutoPosing or what shows up in the viewport as a manipulator gizmo.

If you're not sure which name to use, run `list_objects(name_contains="pelvis")` and pick the `_Box` one.

## Auto-nudge sometimes fails (Windows focus-stealing prevention)

`_nudge.py` uses `SetForegroundWindow` + simulated Alt+C, P, P keystrokes to click **Process Pending** for you. Windows blocks `SetForegroundWindow` unless the calling process already has focus or has just received a key event — Poppet primes the queue with an Alt tap to work around this, but it still loses to:

- Cascadeur being minimized or behind a fullscreen window.
- Another process stealing focus mid-sequence.
- Some antivirus / accessibility software that intercepts synthetic input.

Mitigations:

- **Minimize unrelated windows** so the alt-tab order ends at Cascadeur.
- **Just click Process Pending manually.** It's one click. Auto-nudge is convenience, not architecture.
- If you want to confirm whether auto-nudge fired: watch Cascadeur's title bar and menu animation when you issue a tool call. If the Commands menu doesn't briefly flash, nudge silently failed.

## I want to call a csc method Poppet doesn't expose

Two escape hatches, in order of preference:

1. **`call_action(action_id=...)`** — for anything that's a Cascadeur menu or toolbar command. Action IDs are documented at https://cascadeur.com/help/category/301. Fire-and-forget, no return value.
2. **`execute_csc_code(code=...)`** — for raw Python access. `csc` and `scene` are in scope. Returns the repr of the last expression. Wrap mutations in `scene.modify_with_session(lambda s: ...)` for undo support. See the recipe in [USAGE.md](USAGE.md).

If you find yourself running the same `execute_csc_code` snippet repeatedly, that's a signal to promote it to a real Poppet tool — file an issue.

## Schema is stale after Cascadeur update

`csc://schema` is a one-shot snapshot taken by **Commands → Poppet → Refresh Schema**. After upgrading Cascadeur, the cached JSON at `%LOCALAPPDATA%\poppet-mcp\csc_schema.json` still reflects the old version's API surface — methods that moved or renamed will look real to Claude but fail at call time.

Fix:

1. Restart Cascadeur on the new version.
2. **Commands → Poppet → Refresh Schema** — writes a fresh dump.
3. In your MCP client, re-fetch `csc://schema` so Claude picks up the new content (or restart the client if it caches resources).
