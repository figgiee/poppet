# Changelog

All notable changes to Poppet — Cascadeur MCP. Follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning per
[SemVer](https://semver.org/).

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
- **`Commands → Poppet → Status / Drain Dialog`** — opens a `csc.view.DialogManager`
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
  `%LOCALAPPDATA%\poppet-mcp\`), 19 dispatchers, 20 MCP tools, FastMCP
  stdio server, `Commands → Poppet → Process Pending` drain command,
  `Commands → Poppet → Refresh Schema`, `csc://schema` MCP resource,
  best-effort Windows-API auto-nudge (`_nudge.py`), `install.ps1` +
  `install.sh`, demo scripts (`demo_batch_spec4.py`, `demo_mcp_client.py`,
  `mcp_smoke_test.py`, `poc_client.py`).
- Verified end-to-end against Cascadeur 2025.3.3 + the bundled Cascy
  sample character: spec §4 sparse-control loop completes and exports a
  2.88 MB binary FBX.
