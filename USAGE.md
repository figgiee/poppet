# Poppet — Usage Cookbook

Common workflows for driving Cascadeur 2025.3.x from Claude (or any MCP client) via Poppet. See [README.md](README.md) for the full tool table and architecture.

The pattern under every recipe: Claude calls a tool, Poppet writes a request file, you click **Commands → Poppet → Process Pending** in Cascadeur once to drain the queue, Poppet returns the result. Auto-nudge tries to do that click for you on Windows; treat it as best-effort.

## First contact

Five steps from zero to a working `get_scene_info` call.

1. Install the Cascadeur side: `.\scripts\install.ps1` from the repo root. Copies `cascadeur_side/poppet/` into `%LOCALAPPDATA%\Nekki Limited\Cascadeur\user_scripts\poppet\` and additively extends `settings.json` (`Python.Path` + `Python.Commands`). Backs up `settings.json` to `settings.json.bak` first.
2. Install the MCP server side: `pip install -e .` (or `uvx poppet-mcp` once published).
3. Restart Cascadeur. Open any scene (the bundled `Cascy.casc` sample is the easiest target). Verify **Commands → Poppet → Process Pending** appears in the menu.
4. Wire the server into your MCP client. Claude Code: `claude mcp add poppet -- uvx poppet-mcp`. Claude Desktop: add a `poppet` entry to `claude_desktop_config.json` (snippet in the README).
5. Ask Claude "what's in my Cascadeur scene?". Claude calls `get_scene_info`, Poppet queues the request, you click **Process Pending** once, you get back `{frame, object_count, layer_count, selection_count, scene_name}`. On Cascy that's `object_count: 289, layer_count: 13`.

If step 5 hangs, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — most cases are "did you actually click Process Pending?" or "did auto-nudge silently fail?".

## Cookbook

Each recipe is a self-contained sequence of MCP tool calls. The tool names and signatures match `src/poppet_mcp/server.py`. Wherever you see one of these in a code block, picture Claude issuing it to the MCP server and you (or auto-nudge) draining once per call — or batching them in one drain if you queue several first.

### Set sparse keys + AutoPose + AutoPhysics + export FBX

The headline workflow — spec §4. Claude lays down a handful of milestone positions on hip/foot controllers, asks Cascadeur to fill in plausible joint angles via AutoPosing, applies gravity and momentum via AutoPhysics, reads back what the solver produced, and writes an FBX. The bundled `Cascy.casc` character is the canonical target.

```text
get_scene_info()
list_objects(name_contains="Box")

set_controller_position(controller_id="pelvis_Box", frame=0, x=0, y=0, z=30)
set_selection(object_names=["foot_Box_l", "foot_Box_r"])

run_autoposing()
run_autophysics(timeout_sec=5)

read_telemetry(
    controller_ids=["pelvis_Box", "foot_Box_l", "foot_Box_r"],
    frames=[0],
)
export_fbx(path="C:/work/out/poppet_demo.fbx")
```

This is the exact sequence `scripts/demo_batch_spec4.py` runs end-to-end. On Cascy, the FBX comes out around 2.9 MB binary.

### Inspect the scene

The three orientation calls. Use these as the first thing in any session — they cost almost nothing and give Claude enough grounding to plan the rest. `get_scene_info` is one round trip; `list_objects` returns every object's UUID/name/type and accepts a substring filter; `list_layers` returns the 13 animation layers (on Cascy) with key counts.

```text
get_scene_info()
list_objects()
list_objects(name_contains="Box")    # just the animatable controllers
list_layers()
```

### Read controller telemetry across a frame range

`read_telemetry` accepts a list of controller IDs and a list of frame indexes and returns positions + Euler rotations for each combination. Cheap way to verify what AutoPosing/AutoPhysics actually produced, or to extract a baked animation for analysis.

```text
read_telemetry(
    controller_ids=["pelvis_Box", "foot_Box_l", "foot_Box_r", "hand_Box_l", "hand_Box_r"],
    frames=[0, 5, 10, 15, 20, 25, 30],
)
```

Returns a nested dict keyed by controller name → frame → `{position: [x,y,z], rotation_euler: [rx,ry,rz]}`.

### Move multiple controllers in one batch

Each `set_controller_position` is one queued request — but they all drain in a single Process Pending click as long as you don't await between them. Run AutoPosing once at the end to let the solver smooth out the result.

```text
set_controller_position(controller_id="pelvis_Box",  frame=10, x=0, y=0, z=35)
set_controller_position(controller_id="foot_Box_l",  frame=10, x=-8, y=0, z=0)
set_controller_position(controller_id="foot_Box_r",  frame=10, x=8,  y=0, z=0)
set_controller_position(controller_id="hand_Box_l",  frame=10, x=-20, y=10, z=20)
set_controller_position(controller_id="hand_Box_r",  frame=10, x=20,  y=10, z=20)

run_autoposing()
```

One drain → all five positions land and the pose resolves. The dispatcher logs one `ok` line per request in `dispatcher.log` so you can audit what landed.

### Invoke an arbitrary Cascadeur action

`call_action` is the universal escape hatch for menus and toolbar commands — any action ID listed at https://cascadeur.com/help/category/301 works. Fire-and-forget: no return value, no completion signal. For solves like AutoPhysics that need to converge, prefer the wrapped `run_autophysics()` which polls scene state.

```text
call_action(action_id="Scene.Undo")
call_action(action_id="File.Save")
call_action(action_id="AutoPosingTool.AutoPosing")
call_action(action_id="Timeline.Play")
call_action(action_id="Viewport.FOV increase")
```

If you discover an action ID that's worth wrapping (consistent return shape, slow enough to need polling), file an issue — Poppet's high-level tools are all just wrappers over `call_action` plus result extraction.

### Use the escape hatch

`execute_csc_code` runs arbitrary Python inside Cascadeur's embedded interpreter, with `csc` and `scene` already in scope. Returns the repr of the last expression (or `{"repr": "None"}` for pure statements). Wrap mutations in `scene.modify_with_session(lambda s: ...)` so undo keeps working.

```text
execute_csc_code(code="scene.model_viewer().get_objects_count()")

execute_csc_code(code="""
viewer = scene.model_viewer()
ids = viewer.get_objects()
[(viewer.get_object_name(i), str(viewer.get_object_type(i))) for i in ids[:10]]
""")

execute_csc_code(code="""
import csc
def mutate(s):
    sel = s.take_selector()
    sel.select(['pelvis_Box'])
scene.modify_with_session(mutate)
""")
```

Reach for this only when no higher-level tool fits. Anything you find yourself doing twice is a candidate for promotion to a real tool.

### Read the live csc schema

The `csc://schema` resource exposes a JSON dump of the actual `csc.*` API on your installed Cascadeur version — every module, class, method signature. Generated by **Commands → Poppet → Refresh Schema** and cached at `%LOCALAPPDATA%\poppet-mcp\csc_schema.json`. Around 134 KB on 2025.3.3. Use it as ground truth when the help-site docs lag a release.

```text
# In your MCP client, request the resource:
csc://schema

# In execute_csc_code, dump a single method's signature live:
execute_csc_code(code="import inspect, csc.view; inspect.signature(csc.view.Scene.set_current_frame)")
```

Refresh after every Cascadeur update — see [TROUBLESHOOTING.md](TROUBLESHOOTING.md) "Schema is stale".

## Common controllers in the bundled Cascy character

Cascy uses the standard Cascadeur biped naming. **Controllers** are the `_Box`-suffixed objects — those are what you animate. The bare names (no `_Box`) are the underlying skeleton joints; setting positions on those still works but doesn't drive AutoPosing the way controllers do.

| Controller | Controls |
|---|---|
| `pelvis_Box` | Pelvis / root translation. Move this to translate the whole character. |
| `chest_Box` | Upper torso / ribcage. Affects spine bend. |
| `head_Box` | Head orientation and look-at. |
| `hand_Box_l` | Left hand IK target — wrist position + rotation. |
| `hand_Box_r` | Right hand IK target. |
| `foot_Box_l` | Left foot IK target — drives the whole leg via AutoPosing. |
| `foot_Box_r` | Right foot IK target. |
| `knee_Box_l` | Left knee pole vector — bias knee orientation when foot is anchored. |
| `knee_Box_r` | Right knee pole vector. |
| `elbow_Box_l` | Left elbow pole vector. |
| `elbow_Box_r` | Right elbow pole vector. |

This is the standard Cascadeur biped scheme — names are stable across the bundled samples and any character built with the default rig. To confirm what exists in your scene, run `list_objects(name_contains="Box")` and read the response.
