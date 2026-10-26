# Changelog

All notable changes to cascadeur-mcp — Cascadeur MCP. Follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning per
[SemVer](https://semver.org/).

## [1.0.0] — 2026-10-26

Rebuilt on Cascadeur 2026.2's built-in MCP script server. The Cascadeur-side
install is gone: no `user_scripts` copy, no `settings.json` Python overrides, no
menu commands, no request files, no `Process Pending` clicks, no event hooks, and
no window-focus requirement. `cascadeur-mcp` now ships its in-app runtime to
Cascadeur as source text on the first tool call.

### Changed — breaking

- **Target is now Cascadeur 2026.2.3.** Cascadeur 2025.3.x support ends at
  cascadeur-mcp 0.6.0 (see the `v0.6.0` tag). The old file-queue transport is removed.
- **Transport:** stdio MCP → loopback HTTP → Cascadeur's built-in script server
  (`Scripts → MCP → Start script server`, `127.0.0.1:8765`). The first call
  bootstraps `poppet_rt` inside Cascadeur; the module is version-stamped and is
  re-shipped automatically after a Cascadeur restart or a cascadeur-mcp upgrade.
- **Uninstall from 0.6:** delete `user_scripts/cascadeur-mcp` and
  `user_scripts/poppet_events` from Cascadeur's user data directory, and wire the
  client config with `uvx cascadeur-mcp` (no Cascadeur-side step).
- **New environment variables:** `POPPET_URL` (default
  `http://127.0.0.1:8765`) and `POPPET_TIMEOUT` (default 35s).

### Changed

- Published as **cascadeur-mcp** (PyPI distribution and `cascadeur-mcp` /
  `cascadeur-bootstrap` console scripts). The Python module remains `poppet_mcp`;
  `poppet-mcp` / `poppet-bootstrap` stay as aliases, and the `POPPET_*` env vars
  keep their names for compatibility.

### Added

- `cascadeur-bootstrap` — writes cascadeur-mcp's Cascadeur-side bootstrap and prints the
  one-line Python Console command. The bootstrap starts Cascadeur's built-in script
  server on a free port and installs a 10 ms PySide keeper timer that keeps the
  embedded interpreter cycling the GIL and drives `scene_idle`, fixing the 2026.2.3
  stall where the menu-started server is unreachable while Cascadeur is idle.
- Port auto-discovery: the bootstrap records its port in
  `%LOCALAPPDATA%\cascadeur-mcp\server.json`; `cascadeur-mcp` reads it when `POPPET_URL`
  is unset (new `POPPET_SERVER_PORT` env var for the preferred port).
- `get_script_server_status` — one-call diagnosis of the link between cascadeur-mcp and
  Cascadeur (connectivity, script-server version, loaded runtime version,
  embedded Python, whether a scene is open).
- `run_script` — raw escape hatch that submits Python straight to Cascadeur's
  script server and returns its native response (`ok`, `value`, `messages`,
  `error`), including full in-app tracebacks on failure.
- `scripts/live_check.py` — end-to-end verification against a running Cascadeur.
- `tests/native_server_harness.py` — runs Cascadeur's **shipped** script server
  offline with fake `csc`/`events` modules, so the wire protocol is tested
  against the real server code in CI without a GUI.
- `docs/research/` — competitive landscape and 2025.3.3 → 2026.2.3 Python API
  compatibility audit.

### Fixed

- Dependency: pin `mcp>=1.0.0,<2`. The MCP SDK 2.x renamed `FastMCP` to
  `MCPServer`, so an unpinned fresh install could not import the server
  (`ModuleNotFoundError: mcp.server.fastmcp`). Found by installing the
  released wheel into a clean venv during release verification.

- Live-verified 1.0 against Cascadeur 2026.2.3 with the Cascy sample scene: 43/44
  tool steps passed end-to-end (`docs/verification/live-verify.json`) and the full
  MCP stdio path passed with 45 tools registered. The one failure,
  `duplicate_object`, is documented as a known 2026.2.3 issue.
- 2026.2.3 compatibility pass over every handler, driven by the shipped `.pyi`
  stubs (see `docs/research/python-api-diff.md`): handler fixes for layer
  visibility/locking, object hierarchy, object delete/duplicate, scene save,
  viewport screenshot (`take_image` arity), and set-typed API arguments.
- Every mutating handler now routes through a checked `scene.modify*` wrapper and
  raises when Cascadeur returns `False` (callback failed, traceback only in
  Cascadeur's event log) instead of reporting false success.
- `set_controller_position` / `set_controller_rotation` — the MCP layer forwards a
  nested `{"transform": {...}}` envelope that the migrated handler did not read;
  both keyframing tools now accept it (and the legacy flat keys).
- `get_active_layer` / `set_active_layer` redefined on the timeline layer
  selection (`Scene.get_layers_selector` / `Session.take_layers_selector`).
  2026.2 has no separate "active layer" API; responses carry
  `"semantics": "timeline-layer-selection"`.
- `save_scene` now uses the working `csc.view.Scene.save` path and the client waits
  for the file, instead of trusting `DataSourceManager.save_scene_as` (which returns
  without writing on 2026.2.3).
- `screenshot_viewport` now reports the asynchronous render and the client polls for
  the PNG, instead of failing because the file lands ~150 ms later.
- `set_current_frame` uses the live-verified direct
  `csc.domain.Scene.set_current_frame(frame)` call (the 2025.3 modify-session
  indirection silently did nothing on 2026.2.3).
- `csc://schema` now reflects the live 2026.2.3 API surfaced from the running
  Cascadeur instance rather than a cached 2025.3.x dump.

## [0.6.0] — 2026-05-25

### Fixed

- **`model.layers_editor()` everywhere** — `session.layers_editor()` doesn't
  exist; all 8 dispatcher sites that called it (`layer_add`, `layer_delete`,
  `bake_range`, `keyframe_add`, `keyframe_remove`, `active_layer_set`,
  `layer_visible_set`, `layer_locked_set`) were throwing `AttributeError` and
  returning errors silently. Fixed to use `model.layers_editor()` (the correct
  parameter in the `modify_with_session` callback).
- **Two-step keyframe write** — `keyframe_set` and `set_controller_scale`
  failed on scenes with only a T-pose (1 frame) because writing to frame N>0
  requires the animation data arrays to be extended first.  Added a
  `modify_with_session` pre-pass that calls
  `layers_editor.set_fixed_interpolation_or_key_if_need(layer_id, frame, True)`
  on every layer before the `modify_update` write step.
- **Quaternion rotation readback** — `csc.math.Quaternion.x/y/z/w` are
  callable methods, not properties. `telemetry_read` and `object_transform_get`
  were calling `float(q.x)` on the bound-method object, which raised
  `TypeError` and fell through to the `rotation_euler` fallback.  Fixed with a
  `callable()` guard; both now return `rotation: [qx, qy, qz, qw]`.
- **Layer names in `list_layers`** — `csc.layers.Header.name` is a plain
  string property, not a method. The previous `h.name() if callable(...)` path
  always evaluated to `str(h)` → `"<csc.layers.Header object at 0x…>"`.  Fixed
  to read `getattr(h, "name", None)` directly.
- **`screenshot_viewport` path now optional** — dispatcher auto-generates a
  temp path (`poppet_screenshot_<ts>.png`) when none is supplied.  MCP tool
  signature updated to `path: str | None = None`.

### Changed

- `.gitignore` — added `_test_*.pkl` to ignore live-test pickle artifacts.

## [0.5.0] — 2026-05-24

### Added

- **`selection_extend(object_names)` / `selection_subtract(object_names)`** —
  set-union and set-difference operations on the current selection. Lets
  Claude build a complex selection incrementally (e.g., add both feet to
  whatever's already selected, then subtract a stray IK helper).
- **`read_telemetry_range(controller_ids, frame_start, frame_end, step, local)`** —
  bulk-read controller transforms across an inclusive frame range with a
  configurable step. Walks the update graph once instead of once per frame,
  so it's much faster than N×M telemetry_read calls for dense reads.
- **`.gitattributes`** — pins LF line endings for all source files; ends the
  recurring CRLF conversion warnings on Windows checkouts.
- **`CONTRIBUTING.md`** — how to clone, install, add a tool (dispatcher +
  MCP wrapper + tests + docs), Python 3.8 compat rules for cascadeur_side/,
  branch + PR conventions, release process.
- **`.github/ISSUE_TEMPLATE/{bug_report,feature_request}.md`** — bug + feature
  request templates with the diagnostic fields (install_check output,
  dispatcher log) prefilled.
- **`.github/pull_request_template.md`** — Summary + Test plan + Related
  issues skeleton with the standard verification checklist.

### Changed

- MCP tool count: **40 → 43**.
- Dispatcher count: **41 → 44**.

## [0.4.0] — 2026-05-24

### Added

- **`set_controller_scale(controller_id, frame, sx, sy, sz, local)`** —
  writes to Local Scale / Scale node at the given frame. Mirrors
  set_controller_position; useful for stretchy IK / non-uniform scale targets.
- **Proper `add_keyframe` / `remove_keyframe` dispatchers.** v0.1's MCP
  tools routed through keyframe_set with placeholder transform dicts that
  the dispatcher didn't understand. v0.4 adds dedicated `keyframe_add` /
  `keyframe_remove` dispatchers using `session.layers_editor()
  .set_fixed_interpolation_or_key_if_need(...)` and `.unset_section(...)`,
  patterns from `commands/animation_scripts/{keyframe_reduction,reverse_animation}.py`.
  The MCP tools (`add_keyframe`, `remove_keyframe`) now actually work.
- **Release automation** — `.github/workflows/release.yml` builds + publishes
  on tag push (Trusted Publishing or `PYPI_API_TOKEN`), attaches dist
  artifacts to the GitHub release with the matching CHANGELOG section as
  notes.
- **`scripts/install_check.py`** — diagnostic that walks the Cascadeur-side
  install + settings.json keys + MCP server importability + queue dirs.
- **`Makefile`** — convenience targets for install/dev/test/lint/format/
  build/smoke/clean/release-test/release-prod.
- README badges (CI, license, python, Cascadeur version) +
  **`docs/mcp_client_configs.md`** with copy-paste config for Claude Code,
  Claude Desktop, Cursor/Windsurf, env vars, local dev install, smoke test.

### Fixed

- MCP-level `add_keyframe(layer_id, frame)` and `remove_keyframe(layer_id, frame)`
  were silently no-ops in v0.1-0.3 because the dispatcher path didn't honor
  the `transform={"add": True}` / `{"remove": True}` shape. Now they route
  through real `keyframe_add` / `keyframe_remove` dispatchers.

### Changed

- MCP tool count: **39 → 40** (set_controller_scale added; add/remove_keyframe
  already counted).
- Dispatcher count: **38 → 41**.

## [0.3.0] — 2026-05-24

### Added

- **`selection_filter(pattern, mode)`** — replace the current selection with
  every object whose name matches `pattern`. Modes: `contains` (default),
  `prefix`, `suffix`, `regex`. Returns count + first 50 matched names.
- **`get_active_layer()` / `set_active_layer(layer_id)`** — read and switch
  the currently-active editing layer. Tries multiple API method names
  (`current_layer_id`, `active_layer_id`, `selected_layer_id`,
  `set_current_layer`, `set_active_layer`, `set_selected_layer`) and
  reports which one resolved.
- **`scripts/demo_v03_layer_ops.py`** — 2-stage batch demo of layer
  add/delete/undo/redo/bake_range, with the second stage parameterized off
  the first stage's responses (so it doesn't need a hand-typed layer id).
- **`scripts/demo_import_fbx_roundtrip.py`** — export → re-import test
  with configurable `--target {scene,animation}`.
- USAGE.md cookbook sections for layer ops, undo, selection filtering,
  scene snapshots, and viewport screenshots.

### Changed

- MCP tool count: **36 → 39**.
- USAGE.md "First contact" updated to describe auto-drain on focus + drain
  dialog as the preferred drain paths (manual Process Pending now last
  resort, not the default).

## [0.2.0] — 2026-05-24

### Added

- **Auto-drain via Cascadeur events.** New `cascadeur_side/poppet_events/`
  package wires `scene_activated` and `scene_opened` handlers that call
  `process_pending.run(scene)` whenever the Cascadeur window regains focus.
  Removes the per-call manual "Process Pending" click for most workflows.
  `install.ps1`/`install.sh` register the events package via
  `Python.Events` in `settings.json`.
- **`Commands → cascadeur-mcp → Status / Drain Dialog`** — opens a `csc.view.DialogManager`
  dialog showing queue depth + a one-click drain button + an "Open Queue Dir"
  shortcut. Useful when running without the events handler or for debugging.
- **11 new dispatcher tools** (also exposed as MCP tools):
  - `save_scene(path)`, `load_scene(path)`, `new_scene()` — DataSourceManager
    + SceneManager. Tries multiple API call shapes to handle Cascadeur drift.
  - `get_object_hierarchy()` — walks parent/child via `model_viewer`.
  - `get_object_transform(name, frame, local)` — Position + Rotation + Scale
    on one object at a frame.
  - `list_object_attributes(name)` — discovers settable node names on a
    controller's root_group (so the LLM doesn't have to guess).
  - `set_layer_visible(layer_id, visible)`, `set_layer_locked(layer_id, locked)`.
  - `delete_object(name)`, `duplicate_object(name)` — `model_editor` first,
    `Scene.Edit.*` action ID fallback.
  - `screenshot_viewport(path)` — `csc.tools.RenderToFile.editor.take_image`
    with `Viewport.*` action ID fallback.
  - `add_layer(name, parent_id?)` / `delete_layer(layer_id)` — wraps
    `session.layers_editor().create_layer/delete_layer`.
  - `undo()` / `redo()` — wraps `Scene.Undo` / `Scene.Redo` action IDs.
  - `bake_range(layer_id, frame_start, frame_end)` — bulk-bake per-frame
    keys via `set_fixed_interpolation_or_key_if_need`, pattern from
    `commands/animation_scripts/reverse_animation.py`.
- **CI** — `.github/workflows/ci.yml`: ruff lint, syntax check on
  `cascadeur_side/` under real Python 3.8 (matches Cascadeur's embedded
  interpreter), pytest matrix (ubuntu + windows × py3.11 + py3.12), MCP
  stdio smoke (`scripts/mcp_smoke_test.py`).
- **`USAGE.md`** — cookbook of common workflows (spec §4 sparse-control loop,
  telemetry reads, batch controller moves, escape hatch via `execute_csc_code`,
  schema fetch) + a controller-naming reference for the bundled Cascy biped.
- **`TROUBLESHOOTING.md`** — settings.json `.bak` restore, "menu missing"
  checklist, tool-call timeout fallback, FBX export sanity, auto-nudge
  failure modes, stale-schema refresh path.
- **`tests/` (73 tests, 1 skipped)** — framing, dispatch routing, vec/quat
  helpers, `CascadeurConnection` file-sync client, all v0.2 dispatchers.

### Changed

- **`set_current_frame` works now.** Rewrote `_d_frame_set` to use
  `scene.modify_update_with_session(label, mod)` with
  `session.set_current_frame(N)` inside the callback. Pattern lifted from
  bundled `commands/export_to_roblox.py:169`. The bare
  `scene.set_current_frame` / `session.set_current_frame` outside a session
  is silently no-op in Cascadeur 2025.3.3.
- `import_fbx` MCP tool now accepts `target = "scene" | "animation"` (was
  hard-coded to "scene").
- MCP tool count: **20 → 36** + 1 resource (`csc://schema`).

### Fixed

- Cascadeur API drift defense — every new dispatcher tries multiple
  method-name variants (`save_scene`/`save`, `create_application_scene`/
  `create_scene`/`new_scene`, `get_parent_id`/`get_parent`, etc.) and
  reports which one worked so future Cascadeur updates surface as
  structured errors instead of crashes.

## [0.1.0] — 2026-05-21

### Added

- Initial release: file-sync architecture (request/response JSON files in
  `%LOCALAPPDATA%\cascadeur-mcp\`), 19 dispatchers, 20 MCP tools, FastMCP
  stdio server, `Commands → cascadeur-mcp → Process Pending` drain command,
  `Commands → cascadeur-mcp → Refresh Schema`, `csc://schema` MCP resource,
  best-effort Windows-API auto-nudge (`_nudge.py`), `install.ps1` +
  `install.sh`, demo scripts (`demo_batch_spec4.py`, `demo_mcp_client.py`,
  `mcp_smoke_test.py`, `poc_client.py`).
- Verified end-to-end against Cascadeur 2025.3.3 + the bundled Cascy
  sample character: spec §4 sparse-control loop completes and exports a
  2.88 MB binary FBX.
