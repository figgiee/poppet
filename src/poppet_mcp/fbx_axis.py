"""Read and patch the axis settings in a binary FBX file's GlobalSettings block.

Unreal writes Z-up FBX files. Cascadeur's Unreal rigs (such as the stock
``UE5_Manny.casc``) already carry the Z-up to Y-up turn in their ``root`` joint, so
importing an Unreal clip lets Cascadeur convert the axes a second time and the
character lands on its back. Declaring the file Y-up skips Cascadeur's conversion
and the clip lands upright. Only integer properties are patched, in place, so
the file layout does not change.
"""

from __future__ import annotations

import shutil
import struct
from pathlib import Path
from typing import Any

MAGIC = b"Kaydara FBX Binary  "
AXIS_KEYS = (
    "UpAxis",
    "UpAxisSign",
    "FrontAxis",
    "FrontAxisSign",
    "CoordAxis",
    "CoordAxisSign",
    "OriginalUpAxis",
    "UnitScaleFactor",
)
# What Cascadeur needs to read an Unreal export without converting it again.
UNREAL_AS_Y_UP = {"UpAxis": 1, "UpAxisSign": 1, "FrontAxis": 2, "FrontAxisSign": 1}


def _read_props(data: bytes, off: int, n: int) -> tuple[list[tuple[str, Any, int]], int]:
    props = []
    fixed = {"Y": ("<h", 2), "C": ("<B", 1), "I": ("<i", 4), "F": ("<f", 4), "D": ("<d", 8)}
    fixed["L"] = ("<q", 8)
    for _ in range(n):
        t = chr(data[off])
        off += 1
        if t in fixed:
            fmt, size = fixed[t]
            props.append((t, struct.unpack_from(fmt, data, off)[0], off))
            off += size
        elif t in "SR":
            ln = struct.unpack_from("<I", data, off)[0]
            off += 4
            props.append((t, data[off : off + ln], off))
            off += ln
        elif t in "fdlib":
            _, _, clen = struct.unpack_from("<III", data, off)
            off += 12
            props.append((t, None, off))
            off += clen
        else:
            raise ValueError(f"unknown FBX property type {t!r} at byte {off}")
    return props, off


def _walk(data: bytes, off: int, version: int, path: list[str], out: list) -> None:
    wide = version >= 7500
    head = struct.Struct("<QQQ" if wide else "<III")
    while off + head.size < len(data):
        end, nprops, _ = head.unpack_from(data, off)
        name_len = data[off + head.size]
        if end == 0:
            return
        start = off + head.size + 1
        name = data[start : start + name_len].decode("ascii", "replace")
        props, after = _read_props(data, start + name_len, nprops)
        out.append((path + [name], props))
        if after < end:
            _walk(data, after, version, path + [name], out)
        off = end


def read_global_settings(data: bytes) -> dict[str, tuple[Any, str, int]]:
    """``{property: (value, type code, byte offset of the value)}`` for GlobalSettings."""
    if data[:20] != MAGIC:
        raise ValueError("not a binary FBX file (ASCII FBX is not supported)")
    version = struct.unpack_from("<I", data, 23)[0]
    nodes: list = []
    _walk(data, 27, version, [], nodes)
    res: dict[str, tuple[Any, str, int]] = {"_version": (version, "I", 23)}
    for path, props in nodes:
        if path[:1] == ["GlobalSettings"] and path[-1] == "P" and props:
            key = props[0][1].decode("utf-8", "replace")
            if props[-1][0] in "IDF":
                res[key] = props[-1][1], props[-1][0], props[-1][2]
    return res


def axis_report(path: str | Path) -> dict[str, Any]:
    gs = read_global_settings(Path(path).read_bytes())
    return {k: gs[k][0] for k in AXIS_KEYS if k in gs}


def patch_axes(src: str | Path, dst: str | Path, values: dict[str, int]) -> dict[str, Any]:
    """Copy ``src`` to ``dst`` with the given integer GlobalSettings properties set."""
    data = bytearray(Path(src).read_bytes())
    gs = read_global_settings(bytes(data))
    for key, val in values.items():
        if key not in gs:
            raise ValueError(f"{key} is not in the file's GlobalSettings")
        _, kind, off = gs[key]
        if kind != "I":
            raise ValueError(f"{key} is not an integer property")
        struct.pack_into("<i", data, off, int(val))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_bytes(bytes(data))
    return axis_report(dst)


def prepare_unreal_fbx(src: str | Path, dst: str | Path) -> dict[str, Any]:
    """Write a copy of an Unreal FBX that Cascadeur imports upright onto an Unreal rig."""
    before = axis_report(src)
    if before.get("UpAxis") == 2:
        after = patch_axes(src, dst, UNREAL_AS_Y_UP)
        patched = True
    else:
        shutil.copyfile(src, dst)
        after, patched = before, False
    return {
        "source": str(src),
        "prepared": str(dst),
        "before": before,
        "after": after,
        "patched": patched,
    }
