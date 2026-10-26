# cascadeur-mcp — Usage cookbook (1.0)

Workflows for driving Cascadeur 2026.2.3+ from Claude (or any MCP client) through
cascadeur-mcp. Tool list: [README.md](README.md). Design: [docs/architecture.md](docs/architecture.md).

## Before you start

Cascadeur 2026.2.3+ with a scene open; **Scripts → MCP → Start script server** started
(Event Log: `[Cascadeur MCP] listening at http://127.0.0.1:8765/mcp`); cascadeur-mcp registered
in your client ([configs](docs/mcp_client_configs.md)). No Cascadeur-side install, no
drain step. The first call bootstraps cascadeur-mcp's ~70 KB in-app runtime (slower); after
that each call is one loopback round trip. Signatures match `src/poppet_mcp/server.py`.

## First contact

```text
get_script_server_status()   # connected? url, server_version, runtime_version, has_scene
get_scene_info()             # scene name, frame, counts — is a scene open?
list_objects(name_contains="Box")   # the animatable controllers
list_layers()                       # layers + key counts
```

If the status call fails, fix the connection first
([TROUBLESHOOTING.md](TROUBLESHOOTING.md)); it is the cheapest call in the toolkit.

## Inspect the scene

```text
list_objects()                                      # id, name, type
get_object_hierarchy()                              # {id, name, parent_id, child_ids}
get_object_transform(object_name="pelvis_Box", frame=0)
list_object_attributes(object_name="pelvis_Box")    # settable attributes
```

On the bundled `Cascy.casc` sample, `get_scene_info` reports roughly
`object_count: 289`, `layer_count: 13` — a quick "real scene loaded" check.

## Headline loop: pose → AutoPose → AutoPhysics → read back

```text
set_controller_position(controller_id="pelvis_Box", frame=0, x=0, y=0, z=30)
set_controller_position(controller_id="foot_Box_l", frame=0, x=-8, y=0, z=0)
set_controller_position(controller_id="foot_Box_r", frame=0, x=8, y=0, z=0)

run_autoposing()                 # resolve joint rotations from the anchors
run_autophysics(timeout_sec=5)   # gravity/collisions; polls for convergence

read_telemetry(controller_ids=["pelvis_Box", "foot_Box_l", "foot_Box_r"], frames=[0])
```

- `run_autophysics` returns `{"converged": true}` or
  `{"converged": false, "status": "timeout"}`. Keep `timeout_sec` well under the
  script server's ~30 s cap (5–10 s is a good solve budget; ~25 s hard ceiling).
- A timed-out solve may still have applied changes — read telemetry before re-running.
- `read_telemetry` returns position + Euler rotation per controller/frame;
  `read_telemetry_range` handles a frame range in one update-graph walk.

Batch poses before solving — multiple `set_controller_position` calls then one
`run_autoposing()` resolves the whole pose.

## Keyframe authoring

```text
set_controller_position(controller_id="hand_Box_r", frame=12, x=20, y=10, z=20)
set_controller_rotation(controller_id="hand_Box_r", frame=12, qx=0, qy=0, qz=0, qw=1)
set_controller_scale(controller_id="chest_Box", frame=12, sx=1, sy=1.1, sz=1)

add_keyframe(layer_id="<layer id>", frame=12)
remove_keyframe(layer_id="<layer id>", frame=12)

add_layer(name="cascadeur-mcp_Bake")        # response includes the new layer id
bake_range(layer_id="<new id>", frame_start=0, frame_end=60)
undo()
redo()
```

Selection helpers make batch edits practical:

```text
selection_filter(pattern="_Box", mode="suffix")        # every controller
selection_filter(pattern="foot_Box_", mode="prefix")   # both feet
selection_extend(object_names=["hand_Box_l"])
selection_subtract(object_names=["hand_Box_r"])
```

Caveats: `list_layers` visibility/lock fields and `set_layer_visible` /
`set_layer_locked` are flagged by the static API audit — verify the effect rather
than trusting `status: success`. `get_active_layer` / `set_active_layer` are
experimental (Cascadeur keys go to each object's own layer).

## Save, load, capture

```text
save_scene(path="C:/work/snapshots/before.casc")
screenshot_viewport(path="C:/work/snapshots/before.png")
load_scene(path="C:/work/snapshots/before.casc")
new_scene()
```

`screenshot_viewport()` without a path generates a timestamped file. Use absolute
paths with forward slashes; the parent directory must exist. Check `exists` in the
response — capture depends on the Cascadeur build.

## FBX and scene IO

```text
export_fbx(path="C:/work/out/cascadeur-mcp_demo.fbx")
import_fbx(path="C:/work/in/model.fbx", target="scene")
import_fbx(path="C:/work/in/anim.fbx", target="animation")
```

Export is dialog-free binary FBX (baked animation, Y-up); `Cascy` yields ~2.9 MB.
Large scenes can exceed the per-call cap — if a call times out, check the file before
retrying. Import semantics are less exercised than export; verify visually.

## Escape hatches

### `execute_csc_code` — typed runtime, arbitrary Python

Runs through cascadeur-mcp's in-app runtime with `csc`, `scene`, `app` in scope. Returns the
expression value (or `None` for statements). Wrap mutations in
`scene.modify_with_session(...)` to keep undo working.

```text
execute_csc_code(code="scene.model_viewer().get_objects_count()")

execute_csc_code(code="""
viewer = scene.model_viewer()
ids = viewer.get_objects()
[(viewer.get_object_name(i), str(viewer.get_object_type(i))) for i in ids[:10]]
""")
```

### `call_action` — menu/toolbar commands

```text
call_action(action_id="Scene.Undo")
call_action(action_id="AutoPosingTool.AutoPosing")
call_action(action_id="Timeline.Play")
```

Action IDs: <https://cascadeur.com/help/category/301>. Fire-and-forget: no return
value, no completion signal. For AutoPhysics, prefer `run_autophysics()`.

### `run_script` — raw script server pass-through

Sends Python straight to Cascadeur's built-in script server (no `poppet_rt`) and
returns its raw reply: `{"ok": true, "value": "2", "messages": []}`.

```text
run_script(code="1 + 1")
run_script(code="print('hello from Cascadeur')")
```

Use for debugging the transport, one-off statements, or comparing raw output with a
typed tool. `value` is the repr of the expression; in-app failures return
`{"ok": false, "error": "<traceback>"}` without raising. Same `scene_idle` path and
~30 s cap.

## Long operations and the 30 s cap

Cascadeur's script server waits ~30 s for `scene_idle` and drops requests that miss
it; handlers that run longer trip cascadeur-mcp's timeout even though they may still finish
in-app. So: **chunk** long work (bake 50 frames at a time; read telemetry in ranges),
**start/poll** rather than block, **checkpoint** with `save_scene`, and treat
**timeouts as unknown outcomes** — read state back before retrying. Keep
`POPPET_TIMEOUT` above ~30 s (default 35); raising it does not extend the server cap.

## Diagnostics

```text
get_script_server_status()
# {connected, url, server_version, runtime_version, python, has_scene, ...}
# when down: {connected: false, error: "<actionable reason>"}
```

Terminal probe, no MCP client needed:

```bash
python -m poppet_mcp.cascadeur_connection
# {"ok": true, "health": {...}, "ping": {...}}
```

`ping` goes through the in-app runtime, so success proves the whole chain:
cascadeur-mcp → script server → `poppet_rt` → `csc`.

## Cascy controller cheatsheet

Controllers are the `_Box` objects — animate those; bare names (`pelvis`, `thigh_l`,
…) are skeleton joints. Main ones: `pelvis_Box` (root translation), `chest_Box`,
`head_Box`, `hand_Box_l/r`, `foot_Box_l/r` (IK targets driven by AutoPosing),
`knee_Box_l/r`, `elbow_Box_l/r` (pole vectors). Confirm with
`list_objects(name_contains="Box")`.

## Quick pitfalls

Set `pelvis_Box`, not `pelvis`; rotation is a quaternion `(qx,qy,qz,qw)` while
telemetry returns Euler angles; `call_action` never blocks, so poll if you need
completion; most tools need an open scene. Port 8765 busy → see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md#port-8765-is-already-in-use).

## Before you start (2026.2.3)

Cascadeur's built-in script server stalls while the app is idle, so run cascadeur-mcp's
bootstrap once per Cascadeur session before using any tool:

```bash
uvx cascadeur-bootstrap     # then paste the printed exec(open(...)) line in
                         # Cascadeur: Window -> Python Console, Execute
```

Open a scene first. The client finds the server port automatically from
`%LOCALAPPDATA%\cascadeur-mcp\server.json`; set `POPPET_URL` only to override it.
