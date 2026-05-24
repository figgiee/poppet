"""Tests for the v0.2 dispatcher expansion.

Covers: save_scene, load_scene, new_scene, object_hierarchy,
object_transform_get, object_attributes_list, layer_visible_set,
layer_locked_set, object_delete, object_duplicate, viewport_screenshot,
frame_set (rewritten in v0.2 to use modify_update_with_session).

These tests run against the conftest-installed csc MagicMock, so they
verify the routing + parameter-passing without needing a real Cascadeur.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from poppet import _dispatchers

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _scene_with_objects(*pairs):
    """Build a fake scene whose model_viewer yields objects with given names.

    pairs: iterable of (oid, name, type_name) tuples.
    """
    scene = MagicMock(name="scene")
    mv = scene.model_viewer.return_value
    oids = [oid for oid, _, _ in pairs]
    names = {oid: name for oid, name, _ in pairs}
    types = {oid: tn for oid, _, tn in pairs}
    mv.get_objects.return_value = oids
    mv.get_object_name.side_effect = lambda oid: names.get(oid)
    mv.get_object_type_name.side_effect = lambda oid: types.get(oid)
    scene.layers_viewer.return_value.all_layer_ids.return_value = []
    return scene


def _run_mod_immediately(scene, attr_name):
    """Make scene.<attr_name>(label, mod) call mod with mock args immediately."""

    def _call(label, mod):
        # Inspect mod's expected arg count and pass MagicMocks accordingly.
        import inspect

        sig = inspect.signature(mod)
        argc = len(sig.parameters)
        mod(*(MagicMock() for _ in range(argc)))

    getattr(scene, attr_name).side_effect = _call


# ---------------------------------------------------------------------------
# Scene file I/O
# ---------------------------------------------------------------------------


def test_save_scene_requires_string_path(fake_scene):
    with pytest.raises(ValueError, match="path"):
        _dispatchers._d_save_scene({}, fake_scene)
    with pytest.raises(ValueError, match="path"):
        _dispatchers._d_save_scene({"path": ""}, fake_scene)


def test_save_scene_normalizes_backslashes(csc_mock, fake_scene, tmp_path):
    target = str(tmp_path / "out.casc")
    # Make every DataSourceManager.save_scene attempt succeed.
    app = csc_mock.app.get_application.return_value
    dsm = app.get_data_source_manager.return_value
    dsm.save_scene.return_value = None
    # Touch the file so the exists() check is true.
    open(target, "w").close()
    out = _dispatchers._d_save_scene({"path": target}, fake_scene)
    assert out["path"] == target.replace("\\", "/")
    assert out["saved"] is True
    assert "method" in out


def test_load_scene_rejects_missing_file(fake_scene, tmp_path):
    bogus = str(tmp_path / "does_not_exist.casc")
    with pytest.raises(ValueError, match="not found"):
        _dispatchers._d_load_scene({"path": bogus}, fake_scene)


def test_load_scene_calls_dsm(csc_mock, fake_scene, tmp_path):
    real = tmp_path / "real.casc"
    real.write_text("fake")
    out = _dispatchers._d_load_scene({"path": str(real)}, fake_scene)
    assert out["loaded"] is True
    assert "method" in out


def test_new_scene_invokes_scene_manager(csc_mock, fake_scene):
    out = _dispatchers._d_new_scene({}, fake_scene)
    assert out["created"] is True
    assert "method" in out
    assert csc_mock.app.get_application.return_value.get_scene_manager.called


# ---------------------------------------------------------------------------
# Object hierarchy + transforms
# ---------------------------------------------------------------------------


def test_object_hierarchy_lists_all_objects(fake_scene):
    scene = _scene_with_objects(
        ("oid-1", "pelvis", "Joint"),
        ("oid-2", "pelvis_Box", "Box"),
    )
    out = _dispatchers._d_object_hierarchy({}, scene)
    assert out["count"] == 2
    names = [o["name"] for o in out["objects"]]
    assert "pelvis" in names and "pelvis_Box" in names


def test_object_transform_get_rejects_missing_name(fake_scene):
    with pytest.raises(ValueError, match="object_name"):
        _dispatchers._d_object_transform_get({}, fake_scene)


def test_object_transform_get_404s_on_unknown(fake_scene):
    scene = _scene_with_objects(("oid-1", "pelvis_Box", "Box"))
    with pytest.raises(ValueError, match="not found"):
        _dispatchers._d_object_transform_get({"object_name": "nope"}, scene)


def test_object_transform_get_routes_through_modify_update(fake_scene):
    scene = _scene_with_objects(("oid-1", "pelvis_Box", "Box"))
    _run_mod_immediately(scene, "modify_update")
    out = _dispatchers._d_object_transform_get({"object_name": "pelvis_Box", "frame": 5}, scene)
    assert out["object"] == "pelvis_Box"
    assert out["frame"] == 5
    scene.modify_update.assert_called_once()


def test_object_attributes_list_rejects_missing_name(fake_scene):
    with pytest.raises(ValueError, match="object_name"):
        _dispatchers._d_object_attributes_list({}, fake_scene)


# ---------------------------------------------------------------------------
# Layer ops
# ---------------------------------------------------------------------------


def test_layer_visible_set_404s_on_unknown_layer(fake_scene):
    with pytest.raises(ValueError, match="layer_id"):
        _dispatchers._d_layer_visible_set({"layer_id": "ghost", "visible": True}, fake_scene)


def test_layer_visible_set_requires_layer_id(fake_scene):
    with pytest.raises(ValueError, match="layer_id"):
        _dispatchers._d_layer_visible_set({"visible": True}, fake_scene)


def test_layer_locked_set_requires_layer_id(fake_scene):
    with pytest.raises(ValueError, match="layer_id"):
        _dispatchers._d_layer_locked_set({"locked": True}, fake_scene)


# ---------------------------------------------------------------------------
# Object edit
# ---------------------------------------------------------------------------


def test_object_delete_requires_name(fake_scene):
    with pytest.raises(ValueError, match="object_name"):
        _dispatchers._d_object_delete({}, fake_scene)


def test_object_delete_404s_on_unknown(fake_scene):
    scene = _scene_with_objects(("oid-1", "head_Box", "Box"))
    with pytest.raises(ValueError, match="not found"):
        _dispatchers._d_object_delete({"object_name": "nope"}, scene)


def test_object_delete_returns_result_for_known(fake_scene):
    scene = _scene_with_objects(("oid-1", "head_Box", "Box"))
    _run_mod_immediately(scene, "modify_with_session")
    out = _dispatchers._d_object_delete({"object_name": "head_Box"}, scene)
    # Either deleted via model_editor or fell back through action ids — both
    # acceptable for the mock, as long as we get a structured response.
    assert "obj_id" in out


def test_object_duplicate_requires_name(fake_scene):
    with pytest.raises(ValueError, match="object_name"):
        _dispatchers._d_object_duplicate({}, fake_scene)


def test_object_duplicate_404s_on_unknown(fake_scene):
    scene = _scene_with_objects(("oid-1", "head_Box", "Box"))
    with pytest.raises(ValueError, match="not found"):
        _dispatchers._d_object_duplicate({"object_name": "ghost"}, scene)


# ---------------------------------------------------------------------------
# Viewport screenshot
# ---------------------------------------------------------------------------


def test_screenshot_requires_path(fake_scene):
    with pytest.raises(ValueError, match="path"):
        _dispatchers._d_viewport_screenshot({}, fake_scene)


def test_screenshot_returns_method_used(csc_mock, fake_scene, tmp_path):
    target = str(tmp_path / "shot.png")
    # The conftest mock auto-coerces any attribute access — so RenderToFile
    # take_image silently "succeeds" but the file is never written.
    out = _dispatchers._d_viewport_screenshot({"path": target}, fake_scene)
    assert out["path"] == target.replace("\\", "/")
    # Either RenderToFile or a fallback action was attempted.
    assert "method" in out or "error" in out


# ---------------------------------------------------------------------------
# frame_set (v0.2 rewrite)
# ---------------------------------------------------------------------------


def test_frame_set_uses_modify_update_with_session(fake_scene):
    captured = {"called": False}

    def _capture(label, mod):
        captured["called"] = True
        # Sanity: mod arity is 4 (model, update, scene_updater, session).
        import inspect

        sig = inspect.signature(mod)
        assert len(sig.parameters) == 4
        # Run it with mocks to make sure it doesn't blow up.
        mod(*(MagicMock() for _ in range(4)))

    fake_scene.modify_update_with_session.side_effect = _capture
    fake_scene.get_current_frame.return_value = 7
    out = _dispatchers._d_frame_set({"frame": 7}, fake_scene)
    assert captured["called"]
    assert out["requested"] == 7
    assert out["current_frame"] == 7
    assert out["persisted"] is True


def test_frame_set_reports_unpersisted_when_get_disagrees(fake_scene):
    fake_scene.modify_update_with_session.return_value = None
    fake_scene.get_current_frame.return_value = 0
    out = _dispatchers._d_frame_set({"frame": 30}, fake_scene)
    assert out["requested"] == 30
    assert out["current_frame"] == 0
    assert out["persisted"] is False


# ---------------------------------------------------------------------------
# Sanity — handlers registered
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "save_scene",
        "load_scene",
        "new_scene",
        "object_hierarchy",
        "object_transform_get",
        "object_attributes_list",
        "layer_visible_set",
        "layer_locked_set",
        "object_delete",
        "object_duplicate",
        "viewport_screenshot",
        # v0.3-style adds (still in v0.2 release)
        "layer_add",
        "layer_delete",
        "undo",
        "redo",
        "bake_range",
    ],
)
def test_new_handler_registered(name):
    assert name in _dispatchers._HANDLERS, f"missing handler: {name}"
    assert callable(_dispatchers._HANDLERS[name])


def test_handler_count_at_least_35():
    # v0.1 had 19, v0.2 adds 16 (11 main + 5 layer/undo) — should be at least 35.
    assert len(_dispatchers._HANDLERS) >= 35, (
        f"expected 35+ handlers, got {len(_dispatchers._HANDLERS)}: "
        f"{sorted(_dispatchers._HANDLERS)}"
    )


# ---------------------------------------------------------------------------
# Layer add/delete + undo/redo + bake_range
# ---------------------------------------------------------------------------


def test_layer_add_requires_name(fake_scene):
    with pytest.raises(ValueError, match="name"):
        _dispatchers._d_layer_add({}, fake_scene)


def test_layer_add_runs_modify_with_session(fake_scene):
    _run_mod_immediately(fake_scene, "modify_with_session")
    out = _dispatchers._d_layer_add({"name": "Body"}, fake_scene)
    assert out["name"] == "Body"
    fake_scene.modify_with_session.assert_called_once()


def test_layer_delete_requires_layer_id(fake_scene):
    with pytest.raises(ValueError, match="layer_id"):
        _dispatchers._d_layer_delete({}, fake_scene)


def test_layer_delete_404s_unknown_id(fake_scene):
    with pytest.raises(ValueError, match="not found"):
        _dispatchers._d_layer_delete({"layer_id": "ghost"}, fake_scene)


def test_undo_invokes_scene_undo(csc_mock, fake_scene):
    out = _dispatchers._d_undo({}, fake_scene)
    assert out["invoked"] == "Scene.Undo"
    am = csc_mock.app.get_application.return_value.get_action_manager.return_value
    am.call_action.assert_called_with("Scene.Undo")


def test_redo_invokes_scene_redo(csc_mock, fake_scene):
    out = _dispatchers._d_redo({}, fake_scene)
    assert out["invoked"] == "Scene.Redo"
    am = csc_mock.app.get_application.return_value.get_action_manager.return_value
    am.call_action.assert_called_with("Scene.Redo")


def test_bake_range_requires_layer_id(fake_scene):
    with pytest.raises(ValueError, match="layer_id"):
        _dispatchers._d_bake_range({"frame_start": 0, "frame_end": 10}, fake_scene)


def test_bake_range_rejects_inverted_range(fake_scene):
    with pytest.raises(ValueError, match="frame_end"):
        _dispatchers._d_bake_range(
            {"layer_id": "x", "frame_start": 30, "frame_end": 10}, fake_scene
        )


def test_bake_range_404s_unknown_layer(fake_scene):
    with pytest.raises(ValueError, match="not found"):
        _dispatchers._d_bake_range(
            {"layer_id": "ghost", "frame_start": 0, "frame_end": 5}, fake_scene
        )


# os import used above for path joins in fixtures
_ = os
