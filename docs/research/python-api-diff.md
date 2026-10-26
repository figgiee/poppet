# Poppet × Cascadeur 2026.2.3 — Cascadeur-side Python API compatibility audit

Status: **research complete, static analysis only** (no Cascadeur launched, no poppet source modified).
Date: 2026-10-26. Author: api-diff teammate (task-2).

| | |
|---|---|
| OLD (built/verified against) | `C:\Program Files\Cascadeur` — `cascadeur.exe` 2025.3.3.0.14628 |
| NEW (target) | `C:\Users\sandv\AppData\Local\Cascadeur` — `cascadeur.exe` 2026.2.3.0.16863 |
| Poppet code audited | `cascadeur_side/poppet/_dispatchers.py` (44 handlers), `process_pending.py`, `refresh_schema.py`, `drain_dialog.py`, `_introspect.py`, `_paths.py`, `_framing.py`, `poppet_events/*`; tool surface `src/poppet_mcp/server.py` (43 tools + `csc://schema` resource) |
| Method | Diff of `resources/scripts/**` between installs; 2026.2 `.pyi` stubs (`resources/scripts/stubs`, **new in 2026.2**) as authoritative 2026.2 binding surface; 2025.3.3 evidence = old `pycsc` sources, old bundled scripts, and old `samples/api_document.py` (hand-written API reference shipped in both installs); old/new `pycsc` textual diff |

Confidence labels used below: **EVIDENCE** = read directly in a shipped file; **UNKNOWN** = cannot be established statically (runtime action IDs, some arities).

> Correction to the task premise: **both installs embed Python 3.11**, not 3.8/3.11. `python311.dll` is at each install root and the bundled numpy wheels are `cp311-win_amd64.pyd` in the 2025.3.3 install too. Poppet's "Python 3.8-compatible" constraint and the stale docstring in `_dispatchers.py:3` are unnecessary; there is no 3.8→3.11 migration to do. (`_framing.py` already uses `dict[str, Any]`, which would not parse on 3.8 anyway.)

---

## (a) Summary counts

**44 dispatcher handlers audited.** Of those, 43 are exposed as 43 MCP tools (`keyframe_set` backs two tools; `schema_get` backs the `csc://schema` resource; `echo` is internal).

| Status | Handlers | MCP tools |
|---|---|---|
| ✅ WORKS — no change needed | **32** | 31 |
| 🟡 NEEDS-FIX — API exists but poppet calls it incorrectly / via dead fallbacks | **8** | 8 |
| 🔴 BROKEN — no equivalent API in 2026.2 (2 of them were already broken in 2025.3.3) | **2** | 2 |
| ⬜ UNKNOWN — action-ID / runtime-dependent, not statically verifiable | **2** | 2 |
| **Total** | **44** | **43** |

**Platform modules (gate everything, audited separately):**

| Module | Status | Why |
|---|---|---|
| `cascadeur_side/poppet/process_pending.py` | 🟡 NEEDS-FIX | `command_name()` no longer recognised by 2026.2 command loader (see B1) |
| `cascadeur_side/poppet/refresh_schema.py` | 🟡 NEEDS-FIX | same |
| `cascadeur_side/poppet/drain_dialog.py` | 🟡 NEEDS-FIX | same; also wrong dialog-API shape (dict instead of `list[DialogButton]` — was already wrong in 2025.3.3) |
| `cascadeur_side/poppet_events/scene_activated/*`, `scene_opened/*` | ✅ WORKS | event contract `run(scene)` unchanged; `events_rule.py` semantics unchanged (only an empty-list guard added) |
| `cascadeur_side/poppet/_introspect.py` | ✅ WORKS | runtime reflection over `csc`; could be replaced by the new stubs (see E3) |
| `cascadeur_side/poppet/_paths.py`, `_framing.py` | ✅ WORKS | no `csc` API dependence |

**Bottom line:** the `csc.*` Python API itself is remarkably stable between 2025.3.3 and 2026.2.3. The single true *regression* that can stop poppet from working is the **command/action registration contract change** (`command_name()` → `name()`), which removes all three Poppet menu commands (including the manual drain trigger). Everything else in the 🟡/🔴 buckets is either a poppet bug that was already broken in 2025.3.3 or a call that 2026.2 unconditionally rejects.

---

## (b) Per-command table

Legend for paths: repo-relative paths are poppet. `NEW:`/`OLD:` prefixes mean
`C:\Users\sandv\AppData\Local\Cascadeur\resources\scripts\...` /
`C:\Program Files\Cascadeur\resources\scripts\...` (install root-relative shown after the prefix).
Line numbers are exact where given.

| # | Command (`_HANDLERS` key) | Status | Evidence (file + symbol) | Smallest fix |
|---|---|---|---|---|
| 1 | `echo` | ✅ WORKS | `_dispatchers.py::_d_echo` — no `csc` API | none |
| 2 | `exec_csc` | ✅ WORKS | `csc` module namespace unchanged: `NEW: stubs/csc/__init__.pyi`; `eval`/`exec` on 3.11 | none |
| 3 | `call_action` | ✅ WORKS (framework) | `NEW: stubs/csc/app/__init__.pyi:37 ActionManager.call_action(str)`; `app.get_action_manager()` at `:88` | none; action-ID existence is runtime/UNKNOWN |
| 4 | `scene_info` | ✅ WORKS | `Scene.get_current_frame` `NEW: stubs/csc/domain/__init__.pyi:269`; `ModelViewer.get_objects` `NEW: stubs/csc/model.pyi:960`; `Viewer.all_layer_ids` `NEW: stubs/csc/layers/__init__.pyi:677`; `view.Scene.name()` `NEW: stubs/csc/view/__init__.pyi:363` (2026.2 also documents it — old doc omitted it) | none |
| 5 | `selection_get` | ✅ WORKS | `Selection.ids` is a `@property` `NEW: stubs/csc/domain/__init__.pyi:371-373`; `selector()` `:305`; `selected()` `:419` | none |
| 6 | `selection_set` | ✅ WORKS | `Session.take_selector()` `NEW: stubs/csc/domain/__init__.pyi:557`; `Selector.select(ids, id=…)` `:417`; `ObjectId.null()` `NEW: stubs/csc/model.pyi:967` | none |
| 7 | `selection_clear` | ✅ WORKS | same as #6 (`select(set(), null)`) | none |
| 8 | `objects_list` | ✅ WORKS | `ModelViewer.get_objects()` / `get_object_name` / `get_object_type_name` `NEW: stubs/csc/model.pyi:955-963` | none |
| 9 | `layers_list` | 🟡 NEEDS-FIX | `Layer.obj_ids`, `is_visible`, `is_locked` are **properties** in 2026.2 `NEW: stubs/csc/layers/__init__.pyi:483-489`; poppet calls them as methods (`_dispatchers.py:266,274-280`) → `TypeError` swallowed by bare `except` → obj count / visibility / lock silently missing. `key_frame_indices()` *is* a method (`:467`) and works. `layer.header.name` works (Header field, `:393-395`) | drop the parens: `len(layer.obj_ids)`, `layer.is_visible`, `layer.is_locked` |
| 10 | `keyframes_get` | ✅ WORKS | `Layer.key_frame_indices() -> FramesIndices` `NEW: stubs/csc/layers/__init__.pyi:467`; `FramesIndices.__iter__` `NEW: stubs/csc/layers/index.pyi:64` | none |
| 11 | `keyframe_set` | ✅ WORKS (recommend hardening) | `Rotation.from_euler(vec3f)` overload `NEW: stubs/csc/math.pyi:135`; `Rotation.from_quaternion(w,x,y,z)` `:139-144`; `Rotation.to_quaternion` `:160`; `RegularData.value/set_value/data_id` `NEW: stubs/csc/update.pyi:798,865-874`; `SceneUpdater.run_update(set[DataId], frame)` `NEW: stubs/csc/domain/__init__.pyi:333` | replace Euler round-trip (`_dispatchers.py:428-429`) with `Rotation.from_quaternion(qw,qx,qy,qz)`; build the position/rotation value explicitly instead of `current + delta` (see D2) |
| 12 | `autopose_run` | ⬜ UNKNOWN | action id `"AutoPosingTool.AutoPosing"` not present in any 2026.2 shipped script; tool object `AutoPosingTool` *is* confirmed (`NEW: stubs/csc/tools/__init__.pyi:177`; `NEW: python/rig_mode/off.py:452 get_tool('AutoPosingTool')`). Old README marked it VERIFIED on 2025.3.3 | keep; verify action id at runtime, or drive `csc.tools.AutoPosingTool` (`activate/update/deactivate(session)`) inside a modify session |
| 13 | `autophysics_run` | ⬜ UNKNOWN | action id `"AutoPhysicsTool.Snap to Auto Physics"` not statically verifiable; tool name confirmed `NEW: python/rig_mode/on.py:326 get_tool('AutoPhysicsTool')`; `csc.tools.AutoPhysicTool` stub `NEW: stubs/csc/tools/__init__.pyi:167` | keep; verify action id at runtime (convergence poll uses live scene state, so it will report `converged:false` if the action is a no-op) |
| 14 | `telemetry_read` | ✅ WORKS | `Update.get_object_by_id` `NEW: stubs/csc/update.pyi:1124`; `Object.root_group()` `:751`; `Group.node_deep` `:434`; `RegularData.value(frame)` `:871-874`; `Rotation.to_quaternion()` `NEW: stubs/csc/math.pyi:160`; `Quaternion.x()/y()/z()/w()` are **methods** `NEW: stubs/csc/math.pyi:105-112` (poppet's `callable(...)` guard at `_dispatchers.py:592-597` already handles both) | none; optional: read quaternion via `to_quaternion()` then `.w()` etc. (already done) |
| 15 | `fbx_import` | ✅ WORKS | `FbxSceneLoader.get_fbx_loader(view_scene)` `NEW: stubs/csc/fbx.pyi:267`; `FbxLoader.import_scene(csc.Path, num_take=-1, is_set_offset=True)` `:217`; `import_animation(csc.Path, num_take=-1)` `:186`; bundled 2026.2 examples pass plain `str` (`NEW: stubs/csc/fbx.pyi:52,73`), so the `csc.Path` annotation does not block poppet | none |
| 16 | `fbx_export` | ✅ WORKS | `FbxLoader.export_all_objects(csc.Path)` `NEW: stubs/csc/fbx.pyi:116`; `set_settings` `:225`; `FbxSettings.mode/up_axis/bake_animation/apply_euler_filter` `:340-343`; enums `FbxSettingsMode.Binary` `:436-437`, `FbxSettingsAxis.Y` `:363-364`; bundled 2026.2 example: `fbx_scene_loader.export_all_objects(file_name)` with `str` `NEW: stubs/csc/fbx.pyi:334` | none |
| 17 | `frame_get` | ✅ WORKS | `Scene.get_current_frame(clamp_animation=True)` `NEW: stubs/csc/domain/__init__.pyi:269` | none |
| 18 | `frame_set` | ✅ WORKS | `Session.set_current_frame(frame)` `NEW: stubs/csc/domain/__init__.pyi:553` (inside `modify_update_with_session`, as poppet does); `Scene.set_current_frame(frame)` `:309` also exists now | none; `session.set_current_frame` inside the callback is still correct |
| 19 | `schema_get` | ✅ WORKS | `_introspect.dump_schema` reflects `csc`; `csc.Version` still exposed `NEW: stubs/csc/__init__.pyi:328`; `inspect.signature` failure path already handled | none; optionally serve the new `.pyi` stubs instead (E3) |
| 20 | `save_scene` | 🟡 NEEDS-FIX (low) | 2026.2 `DataSourceManager` has only `save_scene(scene_view[, handler])`, `save_scene_as(scene_view, full_file_name)`, `save_current_scene()` — `NEW: stubs/csc/app/__init__.pyi:204-241`. Poppet's variants `save_scene(cur,path)`, `save_scene(path,cur)`, `dsm.save(cur,path)` are all invalid (also were in 2025.3.3: `OLD: samples/api_document.py:800` lists only `save_scene(scene_view)`). It only works today via 4th fallback `view.Scene.save(path_name)` `NEW: stubs/csc/view/__init__.pyi:365` (2026.2 return changed `bool→None`; poppet ignores it) | make `dsm.save_scene_as(app.current_scene(), normalized)` the primary attempt; then check file exists |
| 21 | `load_scene` | ✅ WORKS | `DataSourceManager.load_scene(file_name: str) -> bool` `NEW: stubs/csc/app/__init__.pyi:193`; `dsm.open_scene` never existed (dead fallback) | none; optionally check the returned bool |
| 22 | `new_scene` | ✅ WORKS | `SceneManager.create_application_scene()` `NEW: stubs/csc/app/__init__.pyi:296`; `set_current_scene(view_scene)` `:324` | none |
| 23 | `object_hierarchy` | 🟡 NEEDS-FIX | `ModelViewer` exposes only `behaviour_viewer/data_viewer/get_object_name/get_object_type_name/get_objects` `NEW: stubs/csc/model.pyi:937-963` — **no parent/children methods** (same in 2025.3.3: `OLD: samples/api_document.py` ModelViewer section lists the same five). Parent/children purely via `Basic` behaviour: `BehaviourViewer.get_behaviour_by_name(oid,'Basic')` + `get_behaviour_object(basic,'parent')`; children `BehaviourViewer.get_children(oid)` then `get_behaviour_owner(beh)`. Confirmed usage in 2026.2's own `pycsc/common/hierarchy.py` (`set_parent`, `_get_parent_paths`) and `pycsc/datatypes/domain/scenes.py:get_selection` | replace the `getattr(mv, "get_parent_id"...)` loops with the `Basic.parent` + `get_children`/`get_behaviour_owner` pair (see D2) |
| 24 | `object_transform_get` | ✅ WORKS | same update-graph API as #14; `Rotation.to_quaternion()` and `.to_euler_angles()` both present `NEW: stubs/csc/math.pyi:156-160` | none |
| 25 | `object_attributes_list` | ✅ WORKS | `Group.nodes() -> set[Node]` `NEW: stubs/csc/update.pyi:446`; `Node.full_name()` `:633` (the `children()` fallback path is dead but harmless — `Group` has no `children()`) | none |
| 26 | `layer_visible_set` | 🟡 NEEDS-FIX | `Editor.set_visible_for_layer(is_v: bool, id: csc.Guid)` `NEW: stubs/csc/layers/__init__.pyi:331` — **poppet passes `(lid, visible)`** (`_dispatchers.py:1087`). Same arg order in 2025.3.3 (`OLD: samples/api_document.py:1564`, bundled example `:1641`). There is **no** `Layer.set_visible` in 2026.2 (only `Layer.is_visible` property), so the fallback also dies. Because the callback exception is swallowed by `modify_with_session`, the handler can report success with nothing changed (false success) | swap args: `ed.set_visible_for_layer(visible, lid)`; drop `layer.set_visible` fallback; report `modify_with_session` `False` as error |
| 27 | `layer_locked_set` | 🟡 NEEDS-FIX | `Editor.set_locked_for_layer(is_l: bool, id: csc.Guid)` `NEW: stubs/csc/layers/__init__.pyi:313`; same pre-existing arg-order bug (`_dispatchers.py:1116`), no `Layer.set_locked` fallback | swap args: `ed.set_locked_for_layer(locked, lid)` |
| 28 | `object_delete` | 🟡 NEEDS-FIX | `Session` has only `set_current_frame`, `take_layers_selector`, `take_selector` `NEW: stubs/csc/domain/__init__.pyi:547-558` (identical in 2025.3.3 `OLD: samples/api_document.py`, so `session.model_editor()` **never existed**). Correct API is `ModelEditor.delete_objects(ids: set[ObjectId], close_connections=True)` `NEW: stubs/csc/model.pyi:909`, available as the first `modify*` callback arg. 2026.2 pycsc itself wraps `set(ids)` before calling (`NEW: python/pycsc/datatypes/domain/viewers_editors.py:49-51`) — pass a set. Bundled dialog-free pattern: `NEW: python/common/delete_objects.py:48-56` (`model.delete_objects(sel_ids)` then `generate_update()`/`run_update(set(), frame)`). Fallback action ids `"Scene.Edit.Delete"/"Edit.Delete"/"Object.Delete"` are unverified inventions | `def mod(model, update, scene_updater): model.delete_objects({obj_id}); scene_updater.generate_update(); scene_updater.run_update(set(), scene.get_current_frame())` inside `scene.modify_update(...)`; treat `False` return as failure |
| 29 | `object_duplicate` | 🟡 NEEDS-FIX | implementation is select + `call_action("Scene.Edit.Duplicate"/"Edit.Duplicate"/"Object.Duplicate")`; those ids appear nowhere in either install. 2026.2 ships a dialog-free duplicate: `SceneClipboard.copy(view_scene)` + `SceneClipboard.paste_with_session(view_scene, session)` `NEW: stubs/csc/parts.pyi:87-100`, used by `NEW: python/commands/copy_paste_objects/duplicate.py:23-43` | copy/paste via `app.get_scene_clipboard()` inside `modify_update_with_session` (see D2) |
| 30 | `viewport_screenshot` | 🟡 NEEDS-FIX | `RenderToFile.take_image(scene_view, render_parameters, file_name)` — **3 args required** `NEW: stubs/csc/tools/__init__.pyi:381`; `RenderParameters` has `width/height/samples` `:360-370`. Poppet calls `rtf.take_image(normalized)` with 1 arg (`_dispatchers.py:1282`) → `TypeError`; falls back to three unverified `Viewport.*` action ids. (2025.3.3 arity unverifiable: `RenderToFile` is absent from both installs' `api_document.py`; poppet's own comment at `_dispatchers.py:1273-1278` shows they never checked arity) | `rp = csc.tools.RenderParameters(); rp.width=…; rp.height=…; rp.samples=…; rtf.take_image(app.current_scene(), rp, normalized)` |
| 31 | `layer_add` | ✅ WORKS | `Editor.create_layer(name, parent: csc.Guid, pos: int\|None=None)` `NEW: stubs/csc/layers/__init__.pyi:273` (matches poppet); `Viewer.root_id()` `:769`. Dead edge: `csc.layers.LayerId.null()` is not exported in 2026.2 (`stubs/csc/layers/__init__.pyi` header: "LayerId == FolderId == ItemId == Guid") — only reached if `root_id()` raises | replace fallback with `csc.Guid.null()` |
| 32 | `layer_delete` | ✅ WORKS | `Editor.delete_layer(id: csc.Guid)` `NEW: stubs/csc/layers/__init__.pyi:283` | none |
| 33 | `undo` | ✅ WORKS | `"Scene.Undo"` is used in 2026.2's own `ActionManager` docstring `NEW: stubs/csc/app/__init__.pyi:54` and bundled `NEW: python/commands/export_to_roblox.py:190` | none |
| 34 | `redo` | ✅ WORKS (runtime caveat) | same `ActionManager.call_action`; `"Scene.Redo"` not found verbatim in 2026.2 bundled scripts (only `Scene.Undo` is) | none; smoke-test once |
| 35 | `bake_range` | ✅ WORKS | `Editor.set_fixed_interpolation_or_key_if_need(id, frame, set_key)` `NEW: stubs/csc/layers/__init__.pyi:307`; 2026.2 bundled usage `NEW: python/commands/export_to_roblox.py:177` | none |
| 36 | `selection_filter` | ✅ WORKS | pure `ModelViewer` + `Selector.select` (#8, #6) | none |
| 37 | `active_layer_get` | 🔴 BROKEN | poppet probes `lv.current_layer_id/active_layer_id/selected_layer_id` (`_dispatchers.py:1471`). `csc.layers.Viewer` has none of them `NEW: stubs/csc/layers/__init__.pyi:652-789`; `Editor` has no current/active layer setter/getter either (`:251-338`). Same absence in 2025.3.3 (`OLD: samples/api_document.py` Viewer/Editor sections) → **was already broken**. Only "current layer" in 2026.2 is the *additive animation layer stack* index: `csc.additive_layers.get_manager(scene).get_current_layer_index()` `NEW: stubs/csc/additive_layers.pyi:58-66` (different concept), or the layers *selection* `scene.get_layers_selector()`/`Session.take_layers_selector()` | remove the tools, or redefine against `take_layers_selector()` (layer selection) / `additive_layers.Manager` (stack index) — decide semantics first |
| 38 | `active_layer_set` | 🔴 BROKEN | probes `le.set_current_layer/set_active_layer/set_selected_layer` (`_dispatchers.py:1782`); no such methods on `csc.layers.Editor` `NEW: stubs/csc/layers/__init__.pyi:251-338`; none in 2025.3.3 | same as #37; note the MCP docstring "subsequent keyframe writes land on it" is aspirational — Cascadeur keys go to each object's own layer |
| 39 | `keyframe_add` | ✅ WORKS | `Editor.set_fixed_interpolation_or_key_if_need` `NEW: stubs/csc/layers/__init__.pyi:307` | none |
| 40 | `keyframe_remove` | ✅ WORKS | `Editor.unset_section(pos: int, id: csc.Guid)` `NEW: stubs/csc/layers/__init__.pyi:335` — poppet's `(frame, lid)` order matches | none |
| 41 | `controller_scale_set` | ✅ WORKS (same hardening as #11) | same update-graph API as #11; scale node is `RegularData` with `value/set_value/data_id` `NEW: stubs/csc/update.pyi:798,865-874` | same vector-shape hardening as #11 |
| 42 | `selection_extend` | ✅ WORKS | `Selection.ids` property + `Selector.select` (#5, #6) | none |
| 43 | `selection_subtract` | ✅ WORKS | same as #42 | none |
| 44 | `telemetry_read_range` | ✅ WORKS | delegates to `telemetry_read` (#14) | none |

---

## (c) Breaking changes in 2026.2.3 — ordered by blast radius

### C1. Command/action registration contract changed — `command_name()` → `name()` (HIGHEST; poppet cannot be triggered)
- 2025.3.3 shipped `resources/scripts/python/commands_rule.py`; **2026.2 does not ship that file**. It ships `resources/scripts/python/python_actions_rule.py` instead (`EVIDENCE`).
- Old loader `get_commands()` collected modules with `run` and read `command_name()` / `command_description()` (`OLD: python/commands_rule.py`). New loader `get_action_info()` collects modules with `run` and reads `name()` / `description()` (`NEW: python/python_actions_rule.py`).
- Corpus proof of the rename: bundled command modules that define `def command_name` — **92 in 2025.3.3, 0 in 2026.2** (the 6 residual `command_name` hits in 2026.2 are helper files without a `run`, e.g. `python/common/delete_objects.py:6`); modules that define `def name(` — **0 old, 93 new**. New command style: `NEW: python/commands/add/add_transform.py:9-14` (`def name()` / `def description()` / `def run(scene)`), `NEW: python/scripts/mcp/start_server.py`.
- Impact on poppet: `process_pending.py:26`, `refresh_schema.py:14`, `drain_dialog.py:21` all define `command_name()` only → the new loader registers them **under an empty name string** (`action_name=''`), so they no longer appear as `Poppet.Process Pending`, etc. The user loses the manual drain trigger (and the new native MCP server's `MCP.Start script server` is registered with the new style, proving which contract the 2026.2 app consumes).
- Fix: add `name()`/`description()` to each of the three modules (keep `command_name()` too — each loader ignores the other's function, so one source tree stays compatible with both installs; see D1).

### C2. `csc.tools.RenderToFile.take_image` now requires 3 arguments (HIGH for `viewport_screenshot`)
- 2026.2: `take_image(scene_view: csc.view.Scene, render_parameters: csc.tools.RenderParameters, file_name: str)` `NEW: stubs/csc/tools/__init__.pyi:381`; `RenderParameters` `:360-370`.
- Poppet: `rtf.take_image(normalized)` (`_dispatchers.py:1282`).
- 2025.3.3 arity is not provable statically (`RenderToFile` is absent from the 2025.3.3 API reference and no bundled script uses it); what is certain is that 2026.2 **rejects the current 1-arg call**. Status 🟡, fix in D2.

### C3. `csc.math.Quaternion` component accessors are methods in 2026.2 stubs (MEDIUM; poppet already tolerant)
- 2025.3.3 `samples/api_document.py:3961+` documents `w/x/y/z` as **Properties**; 2026.2 stubs expose `def w(self) -> float`, `def x()`, `def y()`, `def z()` `NEW: stubs/csc/math.pyi:105-112`, plus a real constructor `Quaternion(w, x, y, z)` `:95` and `__mul__` `:97-102`.
- Poppet reads quaternions through `callable(q.x)` guards (`_dispatchers.py:592-597`, `:972-976`) → still WORKS. Any new code should use `q.x()`. Writes never construct `Quaternion` directly, so the ctor change is non-breaking for poppet.

### C4. Set-typed parameters are strict in 2026.2 (MEDIUM; affects `object_delete` after C1 fix)
- `ModelEditor.delete_objects(ids: set[ObjectId], close_connections: bool = True)` `NEW: stubs/csc/model.pyi:909`. 2026.2 pycsc converts before calling: `self.internal.delete_objects(set(ids), close_connections)` `NEW: python/pycsc/datatypes/domain/viewers_editors.py:49-51` (2025.3.3 wrapper passed the raw `ids` through: `OLD: .../viewers_editors.py:49-51`). Poppet passes a list (`_dispatchers.py:1150`) → pass a set.

### C5. Smaller signature/return/rename deltas (LOW; none used by poppet — recorded so the Lead does not re-derive them)
| Symbol | 2025.3.3 | 2026.2 |
|---|---|---|
| `csc.view.Scene.save` | `→ bool` (`OLD doc:…`) | `→ None` (`NEW: stubs/csc/view/__init__.pyi:365`) |
| `csc.view.ViewPort` class | `ViewPort` | renamed `Viewport` (`NEW: stubs/csc/view/__init__.pyi:459`); `view.Scene.view_ports`→`viewports()`; `Scene.set_left_bar_visible` / `event_log` removed |
| `csc.layers.Layer.cell` | listed in old doc | removed from 2026.2 stubs (Layer has `section/interval/key/actual_*` instead) |
| `csc.model.DataEditor.set_setting_value` | `(id, value, frame)` | **arg order** `(id, frame, value)` (`NEW: stubs/csc/model.pyi`) |
| `DataEditor.delete_data` / `delete_setting` | 1 arg | gained `clear_behaviour_fields: bool = True` |
| `ModelEditor.get_viewer` | `→ DataViewer` | `→ ModelViewer` |
| `ClusterEditor.add_cluster` | `name: str = ""` | default removed |
| `Buffer.insert_update_group_by_path` | returned `(GroupInfo, Dict[...])` | returns `csc.update.GroupId` |
| `csc.parts.Buffer` part paths | `objects/locator.casc` | **`objects/locator.partscasc`** — the whole `resources/scripts/parts` tree was re-extensioned (39 `.casc` old → 0, 66 `.partscasc` new). Only matters for code that constructs objects from parts (poppet does not) |
| `csc.update` / `model` type names | `csc.Guid`-based ids in APIs | new `BehaviourId`, `DescriptionId` types; 2026.2 pycsc uses `BehaviourId` (`NEW: stubs/csc/model.pyi:…BehaviourViewer`) |
| `csc.math.Rotation` | `to_euler_angles_x_y_z` | adds `to_euler_angles()` alias (`NEW: stubs/csc/math.pyi:156`) — poppet's fallback gets better |

### C6. Runtime/config-level changes (context, not `csc` API)
- New default `resources/settings.json` adds `Python.Scripts: ["scripts"]`; `Python.Path/Commands/Events` unchanged. The user config at `%LOCALAPPDATA%\Nekki Limited\Cascadeur\settings.json` (`Path`→`user_scripts`, `Commands`→`["commands","poppet"]`, `Events`→`["poppet_events"]`) remains valid in 2026.2 — install layout still works.
- `events_rule.py` contract unchanged (registers every module defining `run` inside `python/events/<event>/`), but 2026.2 **adds events**: `scene_idle`, `application_started`, `event_message` (new dirs + manager modules; old `events/*` contained only `__init__.py` + `example.py`).
- 2026.2 pycsc was substantially refactored (43 files, +1710/−1279; `update_datas/nodes/node_update.py` split into `descriptors/`, `object_node.py`, `group_nodes.py`, new `common/data_types.py`, `custom_enum_description.py`). Poppet does not import pycsc, so this is informational.
- `pycsc`-level helper modules poppet cites as pattern sources were **deleted** in 2026.2 (go_to_origin.py, keyframe_reduction.py, reverse_animation.py, rig_info/*, quick_export/*, nekki/*). Their replacements live in `python/models/*` and `python/scripts/*`. The APIs those patterns used still exist — only the citation paths in poppet's comments are stale.

### C7. Behavioural trap: `scene.modify*` returns `bool` and swallows callback exceptions (MEDIUM; documented by 2026.2 itself)
- 2026.2's own README says: “`scene.modify(...)`, `scene.modify_with_session(...)`, `scene.modify_update(...)`, `scene.modify_update_with_session(...)` … always check the return value. Callback exceptions can be logged to Cascadeur's event log while the MCP `/run` response still reports `ok: true`; these methods return `False` when the modify callback failed” (`NEW: python/scripts/mcp/script_server/README.md`; also `NEW: python/AGENTS.md`).
- Signature is `-> bool` in both versions (`NEW: stubs/csc/domain/__init__.pyi:289-303`; same in the 2025.3.3 doc), so this is not a 2026.2 signature regression — but poppet ignores every return value, and that turns the `session.model_editor()` / wrong-arg-order bugs into **false success responses** (`object_delete`, `layer_visible_set`, `layer_locked_set` report success while nothing changed). Add a checked wrapper (D3).

---

## Pre-existing poppet bugs the upgrade inherits (not 2026.2 regressions)

These are called out separately because they must be fixed anyway and should not be blamed on the new version:

1. `session.model_editor()` never existed — 2025.3.3 `csc.domain.Session` documented only `set_current_frame`, `take_layers_selector`, `take_selector` (`OLD: samples/api_document.py`, Session section; identical in 2026.2 `NEW: stubs/csc/domain/__init__.pyi:547-558`). `object_delete` strategy 1 always raised → false success.
2. `set_visible_for_layer` / `set_locked_for_layer` arg order was `(bool, Guid)` in 2025.3.3 too (`OLD: samples/api_document.py:1554,1564`; old bundled example `:1641,1643`; old pycsc `node_update.py:583`). `Layer.set_visible/set_locked` methods never existed (old doc lists them as properties).
3. `"current/active/selected layer"` APIs never existed in either version (Viewer/Editor).
4. `ModelViewer.get_parent_id/get_children_ids` never existed in either version.
5. `DataSourceManager.save_scene(scene_view, path)` never existed; only the `view.Scene.save(path)` fallback works.
6. `DialogManager.show_buttons_dialog(title, body, list[DialogButton])` took a list in 2025.3.3 too (`OLD: samples/api_document.py:532`); `drain_dialog.py:81-92` passes a dict → broken in both.
7. `object_duplicate`'s action ids are invented; no evidence in either install.
8. `keyframe_set`/`controller_scale_set` vector math: stubs type these data as `numpy.ndarray[float32[3,1]]`; `current + [dx,dy,dz]` broadcasts to `(3,3)` and `set_value` has a `[3,3]` overload, so on a shape-preserving runtime this writes a matrix into a Vec3 channel. Poppet's 2025.3.3 “verified” demo only proved the value round-trips for a zero vector. Harden by building the value explicitly (D2.11).
9. `drain_dialog.py`'s dialog path is unreachable-by-design (dict buttons); its fallback (`on_drain()` inline) does work.

---

## (d) Recommended minimal code changes (file / symbol level; no rewrites)

### D1. Menu commands — make 2026.2 register them (do this first)
In `cascadeur_side/poppet/process_pending.py`, `refresh_schema.py`, `drain_dialog.py` add, **keeping the old functions for 2025.3.3 compatibility** (each loader ignores the other's hooks, so one tree can serve both installs):

```python
def name():                 # 2026.2 loader (python_actions_rule.get_action_info)
    return "Poppet.Process Pending"

def description():
    return "Drain the Poppet request queue"
```

(Existing `command_name()` stays for the 2025.3.3 loader; the dot in `"Poppet.X"` matches the 2026.2 naming convention, e.g. `"Add.Transform"`, `"MCP.Start script server"`.)

### D2. `cascadeur_side/poppet/_dispatchers.py` — per symbol

1. **`_d_layers_list`** (≈244): `layer.obj_ids` → `len(layer.obj_ids)`; `layer.is_visible()` → `layer.is_visible`; `layer.is_locked()` → `layer.is_locked`; keep `layer.key_frame_indices()`.
2. **`_d_layer_visible_set`** (≈1071): `ed.set_visible_for_layer(visible, lid)` (args swapped); delete the `layer.set_visible(visible)` fallback; report error if `scene.modify_with_session(...)` returns `False`.
3. **`_d_layer_locked_set`** (≈1100): `ed.set_locked_for_layer(locked, lid)`; same fallback/return handling.
4. **`_d_object_delete`** (≈1134): replace strategy 1 with a `scene.modify_update` on the model editor:
   ```python
   def mod(model, update, scene_updater):
       model.delete_objects({obj_id})                 # set, per stubs/csc/model.pyi:909
       scene_updater.generate_update()
       scene_updater.run_update(set(), scene.get_current_frame())
   ok = scene.modify_update("Poppet: delete object", mod)
   ```
   Drop the three invented action ids; return `deleted: bool(ok)`.
5. **`_d_object_duplicate`** (≈1187): replace the action chain with the 2026.2 bundled dialog-free pattern (`NEW: python/commands/copy_paste_objects/duplicate.py`):
   `app.get_scene_clipboard().copy(view_scene)` before, then inside `scene.modify_update_with_session` → `clipboard.paste_with_session(view_scene, session)`; keep the before/after id diff.
6. **`_d_object_hierarchy`** (≈889): replace the `getattr(mv, "get_parent_id"/"get_children_ids"…)` loops with behaviour APIs:
   parent: `bv.get_behaviour_object(bv.get_behaviour_by_name(oid, "Basic"), "parent")`;
   children: `[bv.get_behaviour_owner(b) for b in bv.get_children(oid)]` (empty `ObjectId.is_null()` ⇒ no parent).
7. **`_d_viewport_screenshot`** (≈1252): strategy 1 becomes
   ```python
   rp = csc.tools.RenderParameters()
   rp.width, rp.height, rp.samples = 1920, 1080, 1     # or params from request
   rtf = app.get_tools_manager().get_tool("RenderToFile")
   rtf.take_image(app.current_scene(), rp, normalized)
   ```
   then verify the file exists. Drop/keep the `Viewport.*` action fallbacks only as a last resort (ids unverified).
8. **`_d_save_scene`** (≈765): primary attempt `dsm.save_scene_as(app.current_scene(), normalized)`; keep `view_scene.save(path)` as fallback; drop the three invalid signatures.
9. **`_d_layer_add`** (≈1320): `csc.layers.LayerId.null()` → `csc.Guid.null()` (2026.2 does not export `LayerId`; only reached on `root_id()` failure).
10. **`_d_active_layer_get` / `_d_active_layer_set`** (≈1466 / ≈1764): no replacement exists. Decide: (a) delete the two MCP tools (honest), or (b) redefine them as *layer selection* via `scene.get_layers_selector()` / `Session.take_layers_selector()` (`set_full_selection_by_parts([lid], first, last)`), or (c) if the product intent is 2026.2 additive animation layers, use `csc.additive_layers.get_manager(scene).get_current_layer_index()/set_current_layer_index(int)` — but that is an *index into the stacked additive-layer stack*, not the timeline layer id, so the MCP schema would change.
11. **`_d_keyframe_set`** (≈319) and **`_d_set_controller_scale`** (≈1668): replace `Rotation.from_euler(_quat_to_euler_xyz(...))` with `csc.math.Rotation.from_quaternion(qw, qx, qy, qz)` (argument order is `w,x,y,z` — `NEW: stubs/csc/math.pyi:139`), and replace `current + delta` with an explicit 3-value construction, e.g. `new_pos = [x, y, z]` or `np.asarray(current, dtype=np.float32).reshape(3,1) + np.asarray(delta, dtype=np.float32).reshape(3,1)`, then `attr.set_value(new_pos, frame)`. Verify the runtime array shape once via `exec_csc` (`attr.value(frame).shape`).
12. **`_d_autopose_run` / `_d_autophysics_run`**: no code change required for compatibility; runtime smoke-test the two action ids (`AutoPosingTool.AutoPosing`, `AutoPhysicsTool.Snap to Auto Physics`). Fallback if they are gone: drive the tool objects (`get_tool("AutoPosingTool")`, `get_tool("AutoPhysicsTool").editor(view_scene)`) — both tool names are confirmed present in 2026.2's own `rig_mode` scripts.

### D3. Check `modify*` return values (small helper, big correctness win)
Add in `_dispatchers.py`:
```python
def _checked_modify(scene, title, fn, with_session=False, with_update=False):
    ok = scene.modify_update_with_session(title, fn) if with_session and with_update else \
         scene.modify_with_session(title, fn)       if with_session else \
         scene.modify_update(title, fn)              if with_update else \
         scene.modify(title, fn)
    if not ok:                      # 2026.2 logs the callback traceback and returns False
        raise RuntimeError(f"Cascadeur rejected modify '{title}' (see cascadeur_log.log)")
    return ok
```
Use it for the mutation handlers that currently ignore the return (`selection_*`, `layer_*`, `object_delete`, `frame_set`, `keyframe_add/remove`, `bake_range`, `active_layer_set`).

### D4. Optional, high-value: auto-drain without a click (uses a **new 2026.2 event**)
Add `cascadeur_side/poppet_events/scene_idle/poppet_drain.py` with the same `run(scene)` body as the existing `scene_activated` handler. 2026.2 dispatches `scene_idle` continuously (see E2), so the request queue drains without focus changes or the Process Pending click. Keep `scene_activated`/`scene_opened` for 2025.3.3 compatibility. No settings change needed (`poppet_events` is already in `Python.Events`).

### D5. Docs/tests only
- `README.md` tool table: update status column per section (b); `SEARCH` for `[VERIFIED]` claims that now depend on the new contract.
- `src/poppet_mcp/server.py` docstrings for `get_active_layer`/`set_active_layer` and `add_layer(name=…)` describe behaviour Cascadeur does not have; align or remove.
- `_dispatchers.py` header docstring: "embedded Python 3.8" → 3.11.

### D6. Strategic option (not minimal, flag to Lead)
2026.2 ships an in-app MCP script server (`NEW: python/scripts/mcp/script_server/`, `.mcp.json`, `AGENTS.md`). Poppet's external FastMCP server could either (a) keep its schema-rich tool layer but replace the file-sync transport with a direct HTTP call to `http://127.0.0.1:8765/mcp` (`run_script`), or (b) be superseded. This is a product decision; see (e).

---

## (e) What got easier in 2026.2

**E1. Cascadeur 2026.2 ships a native in-app MCP server** — the biggest capability change and direct prior art for poppet:
- `NEW: resources/scripts/python/scripts/mcp/script_server/server.py` (≈530 lines): a `ThreadingHTTPServer` on `127.0.0.1:8765` with `GET /health`, `POST /run` (`{"code": …}`) and `POST /mcp` (`initialize`, `tools/list`, `tools/call` for tool `run_script`).
- Scripts execute on the **next `scene_idle`** event, with `scene`, `csc`, `app` in scope; stdout is captured and returned; supports MCP resources (`cascadeur://docs/python-api`, `cascadeur://modules`).
- Start/stop via commands `MCP.Start script server` / `MCP.Stop script server` (`NEW: python/scripts/mcp/start_server.py`), and `NEW: python/.mcp.json` declares the server for MCP clients.
- `NEW: python/AGENTS.md` documents the caveat poppet also needs: check `modify*` return values, exceptions go to the event log only.
- Consequence for poppet: the file-sync + manual-drain architecture is no longer necessary; the drain-queue design can be replaced by direct HTTP, or poppet can proxy to this server while keeping its richer tool semantics.

**E2. Idle + message events** (this is what makes E1 possible, and what poppet lacked in 2025.3.3):
- `import events` now exposes `scene_idle_manager`, `application_started_manager`, `event_message_manager` in addition to the six scene events (`NEW: python/events/__init__.py`).
- `events.scene_idle_manager.subscribe(cb) -> id`, `.unsubscribe(id)`, `.unsubscribe_all()`, `.execute_when_idle(one_shot_cb)` — see `NEW: python/events/idle/idle_manager.py`, `scene_idle/scene_idle_manager.py`, and live sample `NEW: python/samples/idle_event_test.py`.
- `event_message_manager` receives `(scene, full_message, level, simple_message)` and exposes `csc.MessageLevel.__members__` names — the native server uses it to return Cascadeur's log messages; poppet could use it to replace its `dispatcher.log`/event-log guesses and to surface errors from swallowed `modify*` callbacks.
- In 2025.3.3, `python/events/*` had only empty `__init__.py` + an `example.py` per event; there was no idle/application/message machinery (this matches the README's "no usable in-process scheduler" finding — that finding is now obsolete).

**E3. `.pyi` stubs are shipped** — `NEW: resources/scripts/stubs/csc/**` (29 files) gives exact 2026.2 signatures, enums and property-vs-method distinctions in the install itself (2025.3.3 had no stubs). Poppet can:
- serve/parse these in `schema_get` / `_introspect` instead of runtime reflection (faster, stable, no `inspect.signature` failures on pybind11 builtins);
- type-check `cascadeur_side` offline in CI against the target install's stub tree;
- stop guessing API drift with try/except fallback chains.

**E4. Math conveniences** (partly already present in 2025.3.3, but now explicit in stubs):
- `csc.math.Quaternion(w, x, y, z)` constructor and method-style accessors (`NEW: stubs/csc/math.pyi:95,105-112`), `Quaternion.__mul__` (`:97-102`).
- `Rotation.from_quaternion(w,x,y,z)` / `from_quaternion(Quaternion)` (`NEW: stubs/csc/math.pyi:137-144`) and `Rotation.to_euler_angles()` alias (`:156`) — poppet's quaternion→euler→Rotation round-trip is unnecessary and less accurate.
- `csc.layers.Layer.actual_key/actual_section/key/interval` give direct interpolation-cell access — a cleaner way to implement `keyframe_*` if richer semantics are wanted.

**E5. New animation-layer capability: additive layers** — `csc.additive_layers` (new module, absent from 2025.3.3 docs; new-only in the stub class diff):
`get_manager(scene)`, `add_stacked_layer()`, `get/set_current_layer_index(int)`, `set_stacked_layer_enabled(bool,int)`, `set_stacked_layer_weight(float,int)` (`NEW: stubs/csc/additive_layers.pyi:58-74`). If poppet's layer tools are meant to manage *animation layers* rather than interpolation keys, this is the 2026.2-native API; it can also give `active_layer_*` a well-defined meaning (index-based).

**E6. Script hot-reload was rewritten** — `NEW: python/reloader.py` is 8.4 KB vs the 580-byte 2025.3.3 version: discovers every module under the configured `Python.Path` roots, handles dependencies, ignores `__pycache__`, and explicitly stops/restarts the MCP server around a reload (`_MCP_SERVER_MODULE = "scripts.mcp.script_server.server"`). Practical effect: poppet's dispatcher edits should reload without restarting Cascadeur (worth verifying interactively).

**E7. Misc**: `csc.glb` import/export options module is present in 2026.2 stubs (`NEW: stubs/csc/glb.pyi`) — possible future non-FBX export; `csc.domain.assets.AssetsManager`; `csc.rig` QRT-oriented types (rigging overhaul, new `.partscasc` part format with `parts/final_rig/`); a new `python/models/` command structure (model+UI split) and `python/serializable/` JSON-serialization harness are shipped helpers poppet could reuse for state export.

---

## Appendix: truth sources / how to re-run the key checks

1. Stub inventory and signatures: `NEW: resources/scripts/stubs/csc/**/*.pyi`. Grep targets used above: `grep -r "def set_visible_for_layer" stubs/`, `grep -r "def take_image" stubs/`, etc.
2. Old-version signature ground truth: `OLD: resources/scripts/python/samples/api_document.py` (hand-maintained, incomplete — it omits `RenderToFile` entirely and was *not* updated for 2026.2, so its identical copy in NEW is NOT evidence of API stability; use stubs for 2026.2). Old pycsc sources and old bundled commands corroborate.
3. Command-contract check: compare `OLD: python/commands_rule.py` vs `NEW: python/python_actions_rule.py`, and count `def command_name` vs `def name(` across `python/commands/**` (92/0 → 0/93).
4. `pycsc` diff (informational): `git diff --no-index "C:\Program Files\Cascadeur\resources\scripts\python\pycsc" "C:\Users\sandv\AppData\Local\Cascadeur\resources\scripts\python\pycsc"`.
5. Runtime smoke-test list for whoever can launch Cascadeur (these are the only UNKNOWN/runtime items): `AutoPosingTool.AutoPosing` action; `AutoPhysicsTool.Snap to Auto Physics` action; `Scene.Redo`; `RenderToFile.take_image` with 3 args; `delete_objects` with a set; `attr.value(frame)` array shape (`.shape`) for Position/Rotation/Scale; whether the 3 menu commands appear under `Commands → Poppet` after adding `name()`.

---

## (f) Applied — task-3: 2026.2.3 handler fixes in the in-app runtime

The findings above were applied to the new source of truth, `src/poppet_mcp/runtime/inapp.py` (the `cascadeur_side/` tree is legacy and was not edited). Command names and parameter shapes are unchanged; every fix points at a verified 2026.2 stub in a code comment. Tests: `tests/test_runtime_2026.py` (new regression suite) plus updated `tests/test_new_dispatchers.py`; the shipped native-server integration tests (`tests/test_native_protocol.py`) exercise the patched source end-to-end through the real 2026.2 script server code.

| Handler | Status | What changed |
|---|---|---|
| all mutating handlers | **fixed** | New `_checked_modify()` helper wraps every `scene.modify*` call and raises `RuntimeError` when Cascadeur returns `False` (callback failed, traceback only in the event log). Applies to `selection_*`, `frame_set`, `keyframe_*`, `bake_range`, `layer_*`, `object_delete/duplicate`, `active_layer_set`, and the read handlers that run inside a modify session (`telemetry_read`, `object_transform_get`, `object_attributes_list`) — no more false "success". |
| `object_delete` | **fixed** | `ModelEditor.delete_objects({obj_id})` + `SceneUpdater.generate_update()`/`run_update(set(), frame)` inside `modify_update`. Removed `session.model_editor()` (never existed) and the invented `Scene.Edit.Delete` action fallbacks. |
| `layer_visible_set` / `layer_locked_set` | **fixed** | Verified argument order `set_visible_for_layer(bool, id)` / `set_locked_for_layer(bool, id)`; removed the non-existent `Layer.set_visible/set_locked` fallbacks; checked modify. |
| `layers_list` | **fixed** | Reads `Layer.obj_ids`, `Layer.is_visible`, `Layer.is_locked` as properties (they were being called as methods, so the fields silently vanished). |
| `object_duplicate` | **fixed** | Implemented with `Application.get_scene_clipboard()` + `SceneClipboard.copy`/`paste_with_session` (mirrors 2026.2's bundled duplicate command), with best-effort parent (`Basic.parent`) and layer (`move_obj_ids_in_layers`) restoration. Removed the invented duplicate action IDs. |
| `object_hierarchy` | **fixed** | Parent via `BehaviourViewer.get_behaviour_by_name(oid,"Basic")` + `get_behaviour_object(...,"parent")`; children via `BehaviourViewer.get_children` + `get_behaviour_owner`. Removed the ModelViewer parent/children getters that never existed. |
| `viewport_screenshot` | **fixed** | `RenderToFile.take_image(scene_view, RenderParameters(), file_name)` (3-arg 2026.2 signature, 1920×1080×1 defaults) and raises if no file was written. Removed the unverified `Viewport.*` action fallbacks. |
| `save_scene` | **fixed** | `DataSourceManager.save_scene_as(view_scene, path)` primary, `view.Scene.save(path)` fallback; verifies the file and raises otherwise. Removed the invalid 2-arg `save_scene` / `dsm.save` shapes. |
| `load_scene` / `new_scene` | **fixed** | Single verified call each: `DataSourceManager.load_scene(str) -> bool` (False raises) and `SceneManager.create_application_scene()` + `set_current_scene()`; removed `open_scene`/`create_scene`/`new_scene` guesses. |
| `keyframe_set` / `controller_scale_set` | **fixed** | Accept the MCP `{"transform": {"position"/"rotation"}}` envelope (plus legacy flat keys); rotation writes via `csc.math.Rotation.from_quaternion(w,x,y,z)` instead of a Euler round-trip; positions/scales are written as explicit 3-vectors (no `array + list` broadcasting); per-channel failures now raise. |
| `layer_add` | **fixed** | `csc.Guid.null()` root fallback (2026.2 does not export `csc.layers.LayerId`); checked modify; creation errors raise. |
| `active_layer_get` / `active_layer_set` | **redefined, not removed** | 2026.2 has no editing-active-layer API, and `csc.additive_layers.Manager` is index-based (it cannot accept the tool's timeline `layer_id`), so the tools now map to the verified **timeline layer selection**: `Scene.get_layers_selector()` / `Session.take_layers_selector()`, `LayersSelector.all_included_layer_ids/top_layer_id`, and `set_full_selection_by_parts([layer_id], 0, last_frame)`; responses carry `"semantics": "timeline-layer-selection"`. If removal is preferred instead, delete the two `_HANDLERS` entries and the two MCP tools. |
| `autopose_run` / `autophysics_run` | **unchanged** | Action IDs are not statically verifiable; still `AutoPosingTool.AutoPosing` / `AutoPhysicsTool.Snap to Auto Physics` (tool names confirmed in 2026.2). Needs a live test. |

Additional notes:
- `_d_keyframe_set` now accepts the MCP `transform` envelope, fixing a latent param mismatch between `src/poppet_mcp/server.py` (sends `transform={...}`) and the migrated handler (read flat `position`/`rotation_quat`), which would otherwise have made both keyframing tools raise.
- `object_duplicate` parent restoration remains best-effort: the bundled 2026.2 command additionally rewires transform connections via `pycsc` hierarchy helpers; a live test should confirm duplicated rig objects follow their parent. If not, adopt `pycsc`/`common.hierarchy.set_parents` in a follow-up.
- Still needing live Cascadeur verification: the two solver action IDs, `Scene.Redo` id, `RenderParameters` sizing, and whether `delete_objects` accepts the exact set instance built here.

