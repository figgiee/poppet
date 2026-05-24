"""Tests for the vec / quaternion helpers in cascadeur_side.poppet._dispatchers."""

from __future__ import annotations

import math

import pytest
from poppet import _dispatchers

# --- _vec_to_list ---------------------------------------------------------


class _Vec3Like:
    """Stand-in for a csc.math.Vec3f — exposes .x/.y/.z float attributes."""

    def __init__(self, x: float, y: float, z: float):
        self.x = x
        self.y = y
        self.z = z


def test_vec_to_list_with_xyz_attrs():
    v = _Vec3Like(1.5, -2.0, 3.25)
    assert _dispatchers._vec_to_list(v) == [1.5, -2.0, 3.25]


def test_vec_to_list_with_plain_list():
    assert _dispatchers._vec_to_list([1.0, 2.0, 3.0]) == [1.0, 2.0, 3.0]


def test_vec_to_list_with_tuple():
    assert _dispatchers._vec_to_list((4.0, 5.0, 6.0)) == [4.0, 5.0, 6.0]


def test_vec_to_list_with_none_returns_none():
    assert _dispatchers._vec_to_list(None) is None


def test_vec_to_list_coerces_ints_to_floats():
    result = _dispatchers._vec_to_list([1, 2, 3])
    assert result == [1.0, 2.0, 3.0]
    assert all(isinstance(x, float) for x in result)


def test_vec_to_list_with_numpy_if_available():
    np = pytest.importorskip("numpy")
    arr = np.array([7.0, 8.0, 9.0])
    assert _dispatchers._vec_to_list(arr) == [7.0, 8.0, 9.0]


def test_vec_to_list_with_unparseable_returns_none():
    # An object with no .xyz attrs and no indexing support.
    class Opaque:
        pass

    assert _dispatchers._vec_to_list(Opaque()) is None


def test_vec_to_list_attr_path_preferred_when_both_available():
    # A type that exposes both attribute and indexed access — attribute path wins.
    class Both:
        x = 1.0
        y = 2.0
        z = 3.0

        def __getitem__(self, i):
            raise AssertionError("attribute path should be tried first")

    assert _dispatchers._vec_to_list(Both()) == [1.0, 2.0, 3.0]


# --- _quat_to_euler_xyz ---------------------------------------------------


def _close(a, b, eps=1e-9):
    return all(abs(x - y) <= eps for x, y in zip(a, b, strict=True))


def test_quat_identity_is_zero_euler():
    rx, ry, rz = _dispatchers._quat_to_euler_xyz(0.0, 0.0, 0.0, 1.0)
    assert _close([rx, ry, rz], [0.0, 0.0, 0.0])


def test_quat_90deg_around_x():
    # 90deg rotation around X-axis: q = (sin(pi/4), 0, 0, cos(pi/4))
    s = math.sin(math.pi / 4)
    c = math.cos(math.pi / 4)
    rx, ry, rz = _dispatchers._quat_to_euler_xyz(s, 0.0, 0.0, c)
    assert _close([rx, ry, rz], [math.pi / 2, 0.0, 0.0], eps=1e-12)


def test_quat_90deg_around_z():
    s = math.sin(math.pi / 4)
    c = math.cos(math.pi / 4)
    rx, ry, rz = _dispatchers._quat_to_euler_xyz(0.0, 0.0, s, c)
    assert _close([rx, ry, rz], [0.0, 0.0, math.pi / 2], eps=1e-12)


def test_quat_gimbal_lock_clamps_pitch():
    # sin(pitch) = 1.0 exactly → asin would domain-error; helper must clamp to +pi/2.
    # Construct a quaternion where 2*(qw*qy - qz*qx) >= 1.
    # Pure +Y 90deg rotation: q = (0, sin(pi/4), 0, cos(pi/4)). Plug in:
    #   sinp = 2*(c*s - 0*0) = 2*c*s = sin(pi/2) = 1.0.
    s = math.sin(math.pi / 4)
    c = math.cos(math.pi / 4)
    _, ry, _ = _dispatchers._quat_to_euler_xyz(0.0, s, 0.0, c)
    assert ry == pytest.approx(math.pi / 2, abs=1e-12)


def test_quat_180_around_z():
    # 180deg around Z: q = (0, 0, 1, 0). Expected yaw = +/-pi (atan2 picks sign).
    _, _, rz = _dispatchers._quat_to_euler_xyz(0.0, 0.0, 1.0, 0.0)
    assert abs(abs(rz) - math.pi) < 1e-9
