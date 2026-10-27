"""Regression tests for the Cascadeur 2026.2.3 compatibility fixes.

Each test pins one stub-grounded behaviour in the shipped in-app runtime
(``src/poppet_mcp/runtime/inapp.py``):

* mutate-safety: an explicit ``False`` from ``scene.modify*`` becomes an error;
* layer visibility/lock use the verified ``(bool, Guid)`` argument order;
* ``layers_list`` reads Layer properties instead of calling them as methods;
* ``object_delete`` deletes through ``ModelEditor.delete_objects(set)``;
* ``viewport_screenshot`` uses the 3-argument ``RenderToFile.take_image``;
* ``save_scene`` uses ``DataSourceManager.save_scene_as``;
* ``keyframe_set`` accepts the MCP ``transform`` envelope and writes through
  ``csc.math.Rotation.from_quaternion``;
* ``object_hierarchy`` reads the ``Basic`` behaviour parent/children;
* ``active_layer_*`` map onto the verified timeline layers selection.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from .runtime_loader import runtime as _dispatchers


def _scene_with_objects(*oids):
    scene = MagicMock(name="scene")
    mv = scene.model_viewer.return_value
    mv.get_objects.return_value = list(oids)
    mv.get_object_name.side_effect = lambda oid: f"name-{oid}"
    mv.get_object_type_name.return_value = "Box"
    scene.layers_viewer.return_value.all_layer_ids.return_value = []
    return scene


def _scene_with_layer(layer_id="L1"):
    scene = MagicMock(name="scene")
    lv = scene.layers_viewer.return_value
    lv.all_layer_ids.return_value = [layer_id]
    lv.layer.return_value = MagicMock(name="layer")
    return scene


# ---------------------------------------------------------------------------
# Mutate-safety — the priority-1 contract
# ---------------------------------------------------------------------------


def test_checked_modify_rejects_false():
    scene = MagicMock(name="scene")
    scene.modify_with_session.return_value = False
    with pytest.raises(RuntimeError, match="rejected"):
        _dispatchers._checked_modify(scene, "op", lambda *a: None, session=True)


@pytest.mark.parametrize("return_value", [None, True, MagicMock(name="truthy")])
def test_checked_modify_accepts_non_false(return_value):
    scene = MagicMock(name="scene")
    scene.modify_update.return_value = return_value
    assert _dispatchers._checked_modify(scene, "op", lambda *a: None, update=True) is not False


def test_checked_modify_dispatches_all_variants():
    scene = MagicMock(name="scene")
    cb = lambda *a: None  # noqa: E731
    _dispatchers._checked_modify(scene, "m1", cb)
    _dispatchers._checked_modify(scene, "m2", cb, session=True)
    _dispatchers._checked_modify(scene, "m3", cb, update=True)
    _dispatchers._checked_modify(scene, "m4", cb, session=True, update=True)
    scene.modify.assert_called_once_with("m1", cb)
    scene.modify_with_session.assert_called_once_with("m2", cb)
    scene.modify_update.assert_called_once_with("m3", cb)
    scene.modify_update_with_session.assert_called_once_with("m4", cb)


def test_mutation_handler_raises_when_modify_returns_false():
    scene = _scene_with_layer()
    scene.modify_with_session.return_value = False
    with pytest.raises(RuntimeError, match="rejected"):
        _dispatchers._d_layer_visible_set({"layer_id": "L1", "visible": False}, scene)


# ---------------------------------------------------------------------------
# Layer state — verified argument order + property reads
# ---------------------------------------------------------------------------


def _run_four_arg_callback(scene, attr_name, model=None):
    model = model or MagicMock(name="model")

    def _call(label, mod):
        mod(model, MagicMock(), MagicMock(), MagicMock())

    getattr(scene, attr_name).side_effect = _call
    return model


def test_layer_visible_set_argument_order():
    scene = _scene_with_layer()
    model = _run_four_arg_callback(scene, "modify_with_session")
    out = _dispatchers._d_layer_visible_set({"layer_id": "L1", "visible": False}, scene)
    editor = model.layers_editor.return_value
    # csc.layers.Editor.set_visible_for_layer(is_v: bool, id: csc.Guid)
    editor.set_visible_for_layer.assert_called_once_with(False, "L1")
    assert out["visible"] is False
    assert out["method"] == "set_visible_for_layer"


def test_layer_locked_set_argument_order():
    scene = _scene_with_layer()
    model = _run_four_arg_callback(scene, "modify_with_session")
    out = _dispatchers._d_layer_locked_set({"layer_id": "L1", "locked": True}, scene)
    editor = model.layers_editor.return_value
    # csc.layers.Editor.set_locked_for_layer(is_l: bool, id: csc.Guid)
    editor.set_locked_for_layer.assert_called_once_with(True, "L1")
    assert out["locked"] is True


def test_layers_list_reads_properties():
    scene = MagicMock(name="scene")
    lv = scene.layers_viewer.return_value
    lv.all_layer_ids.return_value = ["L1"]
    lv.frames_count.return_value = 24
    header = MagicMock(name="header")
    header.name = "Body"
    layer = MagicMock(name="layer")
    layer.header = header
    layer.obj_ids = {"o1", "o2"}
    layer.is_visible = True
    layer.is_locked = False
    layer.key_frame_indices.return_value = [0, 5]
    lv.layer.return_value = layer
    out = _dispatchers._d_layers_list({}, scene)
    row = out["layers"][0]
    assert row["name"] == "Body"
    assert row["obj_id_count"] == 2
    assert row["key_frame_count"] == 2
    assert row["is_visible"] is True
    assert row["is_locked"] is False
    assert out["frames_count"] == 24


# ---------------------------------------------------------------------------
# Object edit — verified 2026.2 APIs only
# ---------------------------------------------------------------------------


def test_object_delete_uses_set_and_scene_updater():
    scene = _scene_with_objects("oid-1")
    scene.get_current_frame.return_value = 7
    model = MagicMock(name="model")
    updater = MagicMock(name="scene_updater")
    scene.modify_update.side_effect = lambda label, mod: mod(model, MagicMock(), updater)
    out = _dispatchers._d_object_delete({"object_name": "name-oid-1"}, scene)
    # csc.model.ModelEditor.delete_objects(set[ObjectId], close_connections=True)
    model.delete_objects.assert_called_once_with({"oid-1"})
    updater.generate_update.assert_called_once()
    updater.run_update.assert_called_once_with(set(), 7)
    assert out["method"] == "ModelEditor.delete_objects"


def _install_fake_duplicate_command(monkeypatch, objects, creates=("oid-2",)):
    import sys
    import types

    def fake_run(_scene):
        objects.extend(creates)

    command = types.ModuleType("commands.copy_paste_objects.duplicate")
    command.run = fake_run
    package = types.ModuleType("commands")
    copy_paste = types.ModuleType("commands.copy_paste_objects")
    package.copy_paste_objects = copy_paste
    copy_paste.duplicate = command
    for name, module in (
        ("commands", package),
        ("commands.copy_paste_objects", copy_paste),
        ("commands.copy_paste_objects.duplicate", command),
    ):
        monkeypatch.setitem(sys.modules, name, module)


def test_object_duplicate_prepare_selects_source(csc_mock, fake_scene):
    scene = _scene_with_objects("oid-1")
    scene.modify_update_with_session.side_effect = lambda label, mod: mod(
        MagicMock(), MagicMock(), MagicMock(), MagicMock()
    )
    out = _dispatchers._d_object_duplicate({"object_name": "name-oid-1"}, scene)
    assert out["stage"] == "selected"
    assert out["source_id"] == "oid-1"


def test_object_duplicate_finish_runs_bundled_command(csc_mock, fake_scene, monkeypatch):
    scene = _scene_with_objects("oid-1")
    mv = scene.model_viewer.return_value
    objects = ["oid-1"]
    mv.get_objects.side_effect = lambda: list(objects)
    _install_fake_duplicate_command(monkeypatch, objects)
    scene.modify_update_with_session.side_effect = lambda label, mod: mod(
        MagicMock(), MagicMock(), MagicMock(), MagicMock()
    )
    _dispatchers._d_object_duplicate({"object_name": "name-oid-1"}, scene)
    out = _dispatchers._d_object_duplicate_finish({"object_name": "name-oid-1"}, scene)
    assert out["method"] == "commands.copy_paste_objects.duplicate"
    assert out["new_objects"] == [{"id": "oid-2", "name": "name-oid-2"}]


def test_object_duplicate_finish_raises_when_command_creates_nothing(
    csc_mock, fake_scene, monkeypatch
):
    scene = _scene_with_objects("oid-1")
    objects = ["oid-1"]
    scene.model_viewer.return_value.get_objects.side_effect = lambda: list(objects)
    _install_fake_duplicate_command(monkeypatch, objects, creates=())
    scene.modify_update_with_session.side_effect = lambda label, mod: mod(
        MagicMock(), MagicMock(), MagicMock(), MagicMock()
    )
    _dispatchers._d_object_duplicate({"object_name": "name-oid-1"}, scene)
    with pytest.raises(RuntimeError, match="did not create"):
        _dispatchers._d_object_duplicate_finish({"object_name": "name-oid-1"}, scene)


# ---------------------------------------------------------------------------
# Viewport screenshot — 3-argument take_image
# ---------------------------------------------------------------------------


def test_screenshot_uses_three_arg_take_image(csc_mock, fake_scene, monkeypatch):
    monkeypatch.setattr(_dispatchers.os.path, "exists", lambda p: True)
    monkeypatch.setattr(_dispatchers.os.path, "getsize", lambda p: 99)
    monkeypatch.setattr(_dispatchers.os, "makedirs", lambda *a, **k: None)
    target = r"C:\fake\shot.png"
    out = _dispatchers._d_viewport_screenshot({"path": target}, fake_scene)
    app = csc_mock.app.get_application.return_value
    tool = app.get_tools_manager.return_value.get_tool.return_value
    args, _kwargs = tool.take_image.call_args
    # csc.tools.RenderToFile.take_image(scene_view, RenderParameters, file_name)
    assert len(args) == 3
    assert args[0] is app.current_scene.return_value
    assert args[1] is csc_mock.tools.RenderParameters.return_value
    assert args[2] == out["path"]
    assert out["method"] == "RenderToFile.take_image"


# ---------------------------------------------------------------------------
# Scene I/O — verified DataSourceManager / SceneManager entry points
# ---------------------------------------------------------------------------


def test_save_scene_prefers_view_scene_save(csc_mock, fake_scene, monkeypatch):
    monkeypatch.setattr(_dispatchers.os.path, "exists", lambda p: True)
    monkeypatch.setattr(_dispatchers.os.path, "getsize", lambda p: 10)
    monkeypatch.setattr(_dispatchers.os, "makedirs", lambda *a, **k: None)
    app = csc_mock.app.get_application.return_value
    # csc.view.Scene.save(str) is the 2026.2 path that actually writes the file.
    out = _dispatchers._d_save_scene({"path": r"C:\fake\out.casc"}, fake_scene)
    app.current_scene.return_value.save.assert_called_once_with("C:/fake/out.casc")
    assert out["saved"] is True
    assert out["method"] == "view.Scene.save"


def test_save_scene_reports_pending_when_file_lags(csc_mock, fake_scene, monkeypatch):
    monkeypatch.setattr(_dispatchers.os.path, "exists", lambda p: False)
    monkeypatch.setattr(_dispatchers.os.path, "getsize", lambda p: 0)
    monkeypatch.setattr(_dispatchers.os, "makedirs", lambda *a, **k: None)
    out = _dispatchers._d_save_scene({"path": r"C:\fake\out.casc"}, fake_scene)
    assert out["saved"] is True
    assert out["exists"] is False
    assert out["save_pending"] is True


def test_load_scene_raises_when_refused(csc_mock, fake_scene, monkeypatch):
    monkeypatch.setattr(_dispatchers.os.path, "exists", lambda p: True)
    dsm = csc_mock.app.get_application.return_value.get_data_source_manager.return_value
    dsm.load_scene.return_value = False
    with pytest.raises(RuntimeError, match="refused"):
        _dispatchers._d_load_scene({"path": r"C:\fake\a.casc"}, fake_scene)


def test_new_scene_sets_created_scene_current(csc_mock, fake_scene):
    sm = csc_mock.app.get_application.return_value.get_scene_manager.return_value
    view_scene = MagicMock(name="view-scene")
    sm.create_application_scene.return_value = view_scene
    out = _dispatchers._d_new_scene({}, fake_scene)
    # csc.app.SceneManager.create_application_scene / set_current_scene
    sm.set_current_scene.assert_called_once_with(view_scene)
    assert out["created"] is True
    assert out["method"] == "SceneManager.create_application_scene"


# ---------------------------------------------------------------------------
# Object hierarchy — Basic behaviour parent/children
# ---------------------------------------------------------------------------


def test_object_hierarchy_reads_basic_behaviour():
    scene = _scene_with_objects("child")
    mv = scene.model_viewer.return_value
    bv = mv.behaviour_viewer.return_value
    parent = MagicMock(name="parent-oid")
    parent.is_null.return_value = False
    child = MagicMock(name="child-oid")
    child.is_null.return_value = False
    bv.get_behaviour_by_name.return_value = "basic-beh"
    bv.get_behaviour_object.return_value = parent
    bv.get_children.return_value = ["child-beh"]
    bv.get_behaviour_owner.return_value = child
    out = _dispatchers._d_object_hierarchy({}, scene)
    entry = out["objects"][0]
    assert entry["parent_id"] == str(parent)
    assert entry["children_ids"] == [str(child)]


# ---------------------------------------------------------------------------
# keyframe_set — transform envelope + from_quaternion
# ---------------------------------------------------------------------------


def _keyframe_scene():
    scene = _scene_with_objects("oid-1")
    scene.modify_with_session.side_effect = lambda label, mod: mod(
        MagicMock(), MagicMock(), MagicMock(), MagicMock()
    )
    node = MagicMock(name="root-group")
    update = MagicMock(name="update")
    update.get_object_by_id.return_value.root_group.return_value = node
    updater = MagicMock(name="scene_updater")
    scene.modify_update.side_effect = lambda label, mod: mod(MagicMock(), update, updater)
    return scene, node, updater


def test_keyframe_set_accepts_transform_rotation_envelope(csc_mock, fake_scene):
    scene, node, updater = _keyframe_scene()
    rot_attr = MagicMock(name="rotation-attr")
    node.node_deep.side_effect = lambda name: rot_attr if name == "Local Rotation" else None
    out = _dispatchers._d_keyframe_set(
        {
            "controller_id": "name-oid-1",
            "frame": 3,
            "transform": {"rotation": [0.0, 0.0, 0.0, 1.0]},
        },
        scene,
    )
    # csc.math.Rotation.from_quaternion(w, x, y, z)
    csc_mock.math.Rotation.from_quaternion.assert_called_once_with(1.0, 0.0, 0.0, 0.0)
    rot_attr.set_value.assert_called_once()
    updater.run_update.assert_called_once()
    assert out["applied"]["rotation"] is True


def test_keyframe_set_position_envelope_writes_explicit_vector(csc_mock, fake_scene):
    scene, node, updater = _keyframe_scene()
    pos_attr = MagicMock(name="position-attr")
    node.node_deep.side_effect = lambda name: pos_attr if name == "Local Position" else None
    out = _dispatchers._d_keyframe_set(
        {
            "controller_id": "name-oid-1",
            "frame": 3,
            "transform": {"position": [1.5, 2.5, 3.5]},
        },
        scene,
    )
    pos_attr.set_value.assert_called_once_with([1.5, 2.5, 3.5], 3)
    assert out["applied"]["position"] is True
    assert out["applied"]["position_new"] == [1.5, 2.5, 3.5]


def test_keyframe_set_raises_when_node_missing(fake_scene):
    scene, node, _updater = _keyframe_scene()
    node.node_deep.return_value = None
    with pytest.raises(RuntimeError, match="Local Rotation"):
        _dispatchers._d_keyframe_set(
            {
                "controller_id": "name-oid-1",
                "frame": 3,
                "transform": {"rotation": [0.0, 0.0, 0.0, 1.0]},
            },
            scene,
        )


# ---------------------------------------------------------------------------
# active_layer_* — mapped onto the verified layers selection
# ---------------------------------------------------------------------------


def test_active_layer_get_reads_layers_selector(fake_scene):
    selector = MagicMock(name="layers-selector")
    selector.all_included_layer_ids.return_value = ["L1", "L2"]
    top = MagicMock(name="top-layer")
    top.is_null.return_value = False
    selector.top_layer_id.return_value = top
    fake_scene.get_layers_selector.return_value = selector
    header = MagicMock(name="header")
    header.name = "Body"
    fake_scene.layers_viewer.return_value.header.return_value = header
    out = _dispatchers._d_active_layer_get({}, fake_scene)
    # csc.layers.Selector.all_included_layer_ids / top_layer_id
    assert out["layer_ids"] == ["L1", "L2"]
    assert out["active_layer_id"] == str(top)
    assert out["active_layer_name"] == "Body"
    assert out["semantics"] == "timeline-layer-selection"


def test_active_layer_set_selects_full_animation_range(fake_scene):
    scene = _scene_with_layer()
    scene.data_viewer.return_value.get_animation_size.return_value = 101
    session = MagicMock(name="session")
    scene.modify_with_session.side_effect = lambda label, mod: mod(
        MagicMock(), MagicMock(), MagicMock(), session
    )
    out = _dispatchers._d_active_layer_set({"layer_id": "L1"}, scene)
    selector = session.take_layers_selector.return_value
    # csc.layers.Selector.set_full_selection_by_parts(list[Guid], int, int)
    selector.set_full_selection_by_parts.assert_called_once_with(["L1"], 0, 100)
    assert out["set"] is True
    assert out["frame_range"] == [0, 100]
    assert out["semantics"] == "timeline-layer-selection"


def test_active_layer_get_reports_selector_failure(fake_scene):
    fake_scene.get_layers_selector.side_effect = AttributeError("no selector")
    out = _dispatchers._d_active_layer_get({}, fake_scene)
    assert out["active_layer_id"] is None
    assert "error" in out
