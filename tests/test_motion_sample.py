"""Batched motion reads: exact frames/channels, bounded output and unchanged playhead."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from .runtime_loader import runtime


def scene_for(names=("foot", "hips"), missing_scale=False):
    scene = MagicMock()
    scene.get_current_frame.return_value = 8
    viewer = scene.model_viewer.return_value
    viewer.get_objects.return_value = list(range(len(names)))
    viewer.get_object_name.side_effect = names.__getitem__
    update = MagicMock()

    def object_for(index):
        def node(channel):
            if channel.endswith("Scale") and missing_scale:
                return None

            def value(frame):
                if channel.endswith("Rotation"):
                    return SimpleNamespace(
                        to_quaternion=lambda: SimpleNamespace(x=lambda: 0, y=0, z=0, w=lambda: 1)
                    )
                return [frame, index, 1 if channel.startswith("Local") else 0]

            return SimpleNamespace(value=value)

        return SimpleNamespace(root_group=lambda: SimpleNamespace(node_deep=node))

    update.get_object_by_id.side_effect = object_for
    scene.modify_update.side_effect = lambda label, callback: callback(
        MagicMock(), update, MagicMock()
    )
    return scene


def test_samples_exact_frames_in_one_context_without_playhead_change():
    scene = scene_for()
    out = runtime._d_motion_sample(
        {"object_names": ["foot", "hips"], "frame_start": 0, "frame_end": 8, "frame_step": 4}, scene
    )
    assert [r["frame"] for r in out["frames"]] == [0, 4, 8]
    assert out["frames"][1]["objects"]["hips"]["position"] == [4, 1, 0]
    assert out["frames"][0]["objects"]["foot"]["rotation"] == [0, 0, 0, 1]
    assert out["sample_count"] == 6 and out["playhead_unchanged"]
    scene.modify_update.assert_called_once()
    scene.set_current_frame.assert_not_called()


def test_local_channels_and_optional_missing_scale_are_explicit():
    scene = scene_for(missing_scale=True)
    out = runtime._d_motion_sample(
        {"object_names": ["foot"], "frame_start": 2, "frame_end": 2, "local": True}, scene
    )
    assert out["frames"][0]["objects"]["foot"]["position"] == [2, 0, 1]
    assert out["unavailable_channels"] == {"foot": ["scale"]}
    assert out["coordinate_space"] == "local"


def test_missing_position_channel_keeps_its_actionable_error():
    scene = scene_for(names=("point",))
    update = MagicMock()
    update.get_object_by_id.return_value.root_group.return_value.node_deep.return_value = None

    def native_context(label, callback):
        try:
            callback(MagicMock(), update, MagicMock())
            return True
        except Exception:
            return False

    scene.modify_update.side_effect = native_context
    with pytest.raises(ValueError, match="point.*no Local Position channel"):
        runtime._d_motion_sample(
            {"object_names": ["point"], "frame_start": 0, "frame_end": 0, "local": True},
            scene,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"frame_step": 0},
        {"frame_start": -1},
        {"frame_end": -1},
        {"frame_end": True},
        {"object_names": []},
        {"object_names": ["foot", "foot"]},
        {"object_names": ["missing"]},
        {"frame_end": 10000},
        {"local": "false"},
    ],
)
def test_bad_requests_fail_before_update(change):
    scene = scene_for()
    args = {"object_names": ["foot"], "frame_start": 0, "frame_end": 8, **change}
    with pytest.raises(ValueError):
        runtime._d_motion_sample(args, scene)
    scene.modify_update.assert_not_called()
    scene.set_current_frame.assert_not_called()


def test_ambiguous_names_do_not_select_arbitrary_object():
    scene = scene_for(("foot", "foot"))
    with pytest.raises(ValueError, match="found 2"):
        runtime._d_motion_sample(
            {"object_names": ["foot"], "frame_start": 0, "frame_end": 1}, scene
        )
    scene.modify_update.assert_not_called()
