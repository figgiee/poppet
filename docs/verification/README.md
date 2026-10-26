# 1.0 live verification evidence

Verification date: 2026-10-26
Target: **Cascadeur 2026.2.3.0.16863** (per-user install,
`C:\Users\sandv\AppData\Local\Cascadeur`), Windows, scene
`<install>\samples\Cascy.casc` (289 objects, 13 animation layers).

## Automated runs

| Run | Command | Result | Evidence |
|---|---|---|---|
| Offline unit + protocol tests | `pytest tests` | 210 passed, 1 skipped | `tests/` |
| Tool-level live verification | `python scripts/live_verify.py --scene <Cascy> --screenshot ... --mutations` | **43 / 44 steps passed** | [`live-verify.json`](live-verify.json) |
| MCP stdio end-to-end | `python scripts/live_e2e_mcp.py` | passed, 45 tools registered | [`live-e2e-mcp.txt`](live-e2e-mcp.txt) |

The single failing step is `duplicate_object` — a known 2026.2.3 issue (the scene
clipboard paste modify callback fails; the tool surfaces a clear error rather than a
false success). Workaround documented in `TROUBLESHOOTING.md`.

## What was exercised live

- **Transport:** `/health`, runtime bootstrap + `ping`, live `csc://schema` dump
  (106,448 bytes), port auto-discovery via `server.json` (server on 8766 because
  another local program owns 8765).
- **Scene/rig reads:** `scene_info`, `list_objects` (289), `list_layers` (13),
  `object_transform_get`, `list_object_attributes`, `object_hierarchy`, `get_keyframes`,
  `get_active_layer`, `frame_get`, `read_telemetry`, `read_telemetry_range`.
- **Selection:** `selection_set`, `selection_extend`, `selection_subtract`,
  `selection_filter`, `selection_clear`.
- **Mutations + undo (unsaved sample scene):** `keyframe_set` (position written and
  read back), `controller_scale_set`, `keyframe_add`, `keyframe_remove`, `bake_range`,
  layer hide/show/lock/unlock, `layer_add`/`layer_delete`, `autopose_run` action,
  `undo`, `redo`, `frame_set`, `new_scene`.
- **File/IO:** `load_scene` (Cascy), `save_scene` (4,068,639-byte .casc),
  `export_fbx` (2,998,416-byte binary FBX), `screenshot_viewport` (2,207,359-byte PNG;
  async render polled by the client).
- **MCP path:** real stdio handshake (`poppet 1.0.0`), 45 tools listed,
  `get_script_server_status`, `get_scene_info`, `list_layers`, `get_current_frame`,
  `run_script`, `execute_csc_code` all passed through `poppet-mcp`.

## Environment note (important for reproducing)

Cascadeur 2026.2.3's built-in script server starves its background HTTP thread while
the app is idle (the embedded interpreter holds the GIL in the Qt idle loop). Poppet's
`poppet-bootstrap` console snippet starts the server and installs a 10 ms PySide
`QTimer` that keeps the interpreter ticking and drives `scene_idle`; all live runs
above were made with that keeper installed. See `docs/architecture.md` and
`TROUBLESHOOTING.md`.

## Not exercised live in 1.0

`run_autophysics` (action fired only for AutoPosing), `import_fbx`,
`set_controller_rotation` (same verified write path as position), `delete_object`,
`set_active_layer`, and the object-delete path. These remain covered by unit tests and
the 2026.2.3 stub audit (`docs/research/python-api-diff.md`) but should be re-checked
when next working in those areas.
