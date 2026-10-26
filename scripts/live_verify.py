"""Comprehensive live verification against a running Cascadeur 2026.2.3.

Unlike ``live_check.py`` (a fast smoke test), this exercises the whole typed tool
surface on a real character scene and writes a machine-readable report used as
release evidence.

Usage::

    python scripts/live_verify.py --url http://127.0.0.1:8766 \\
        --scene "C:/Users/.../samples/Cascy.casc"

Prerequisites: Cascadeur is running with an open scene and cascadeur-mcp's console
bootstrap has started its script server (see README).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from poppet_mcp.cascadeur_connection import CascadeurConnection

RESULTS: list[dict] = []


def step(connection: CascadeurConnection, name: str, command: str, params: dict | None = None):
    """Run one tool command, record PASS/FAIL, and return the result (or None)."""
    started = time.perf_counter()
    try:
        result = connection.request(command, params or {})
    except Exception as exc:  # noqa: BLE001 - the report wants every failure
        elapsed = round((time.perf_counter() - started) * 1000)
        RESULTS.append(
            {"step": name, "command": command, "ok": False, "ms": elapsed, "error": str(exc)[:2000]}
        )
        print(f"FAIL {name}: {exc}")
        return None
    elapsed = round((time.perf_counter() - started) * 1000)
    RESULTS.append(
        {
            "step": name,
            "command": command,
            "params": params or {},
            "ok": True,
            "ms": elapsed,
            "result": _compact(result),
        }
    )
    print(f"PASS {name} ({elapsed} ms): {json.dumps(_compact(result), default=str)[:200]}")
    return result


def _compact(value):
    """Trim large payloads so the JSON report stays readable."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == "schema_json":
                out["schema_json_size"] = len(item)
            elif isinstance(item, (list, dict)) and len(json.dumps(item, default=str)) > 4000:
                out[key] = f"<{type(item).__name__} len={len(item)} truncated>"
            else:
                out[key] = item
        return out
    if isinstance(value, list):
        return value[:50]
    return value


def _mutations(connection: CascadeurConnection, names: list[str], layer_ids: list[str]) -> None:
    """Exercise mutating tools on a loaded sample scene (no save is performed)."""
    if not names:
        print("SKIP mutations: no objects in scene")
        return
    controller = names[0]
    layer = layer_ids[0] if layer_ids else None

    step(
        connection,
        "keyframe_set_position",
        "keyframe_set",
        {"controller_id": controller, "frame": 5, "transform": {"position": [0.0, 95.0, -5.0]}},
    )
    step(
        connection,
        "object_transform_after_set",
        "object_transform_get",
        {"object_name": controller, "frame": 5},
    )
    step(
        connection,
        "set_controller_scale",
        "controller_scale_set",
        {"controller_id": controller, "frame": 5, "scale": [1.0, 1.0, 1.0]},
    )

    if layer:
        step(connection, "add_keyframe", "keyframe_add", {"layer_id": layer, "frame": 7})
        step(connection, "remove_keyframe", "keyframe_remove", {"layer_id": layer, "frame": 7})
        step(
            connection,
            "bake_range",
            "bake_range",
            {"layer_id": layer, "frame_start": 0, "frame_end": 2},
        )
        step(connection, "layer_hide", "layer_visible_set", {"layer_id": layer, "visible": False})
        step(connection, "layer_show", "layer_visible_set", {"layer_id": layer, "visible": True})
        step(connection, "layer_lock", "layer_locked_set", {"layer_id": layer, "locked": True})
        step(connection, "layer_unlock", "layer_locked_set", {"layer_id": layer, "locked": False})

    new_layer = step(connection, "add_layer", "layer_add", {"name": "cascadeur_mcp_live_test"})
    if new_layer and new_layer.get("layer_id"):
        step(
            connection,
            "delete_layer",
            "layer_delete",
            {"layer_id": new_layer["layer_id"]},
        )

    duplicate = step(
        connection, "duplicate_object", "object_duplicate", {"object_name": controller}
    )
    added = []
    if isinstance(duplicate, dict):
        added = duplicate.get("new_objects") or duplicate.get("created") or []
    for created in added[:3]:
        name = created.get("name") if isinstance(created, dict) else created
        if name:
            step(connection, "delete_duplicate", "object_delete", {"object_name": name})

    step(connection, "autopose", "autopose_run", {})
    step(
        connection,
        "export_fbx",
        "fbx_export",
        {"path": "C:/Users/sandv/Desktop/cascadeur-mcp/.live-cascy.fbx"},
    )
    step(
        connection,
        "save_scene_copy",
        "save_scene",
        {"path": "C:/Users/sandv/Desktop/cascadeur-mcp/.live-cascy-copy.casc"},
    )
    step(connection, "undo_after_mutations", "undo", {})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Live-verify cascadeur-mcp against Cascadeur 2026.2.3."
    )
    parser.add_argument("--url", default=None)
    parser.add_argument("--scene", default=None, help="Optional .casc file to load before testing")
    parser.add_argument("--report", default="docs/verification/live-verify.json")
    parser.add_argument(
        "--screenshot", default=None, help="Optional PNG path for the screenshot step"
    )
    parser.add_argument(
        "--mutations",
        action="store_true",
        help="Also exercise mutating tools on the loaded sample scene",
    )
    args = parser.parse_args(argv)

    connection = CascadeurConnection(url=args.url)
    print(f"cascadeur-mcp live verification -> {connection.url}\n")

    status = step(connection, "ping", "ping")
    if status is None:
        print("\nCannot reach the script server; run the console bootstrap first (README).")
        return 1
    step(connection, "runtime_ping", "ping")
    health = None
    try:
        health = connection.health()
        RESULTS.append({"step": "health", "ok": True, "result": health})
        print(f"PASS health: {health}")
    except Exception as exc:  # noqa: BLE001
        RESULTS.append({"step": "health", "ok": False, "error": str(exc)})
        print(f"FAIL health: {exc}")

    if args.scene:
        step(connection, "load_scene", "load_scene", {"path": args.scene})

    info = step(connection, "scene_info", "scene_info") or {}
    objects = step(connection, "list_objects", "objects_list", {"name_contains": None}) or {}
    layers = step(connection, "list_layers", "layers_list") or {}
    step(connection, "selection_get", "selection_get")
    step(connection, "frame_get", "frame_get")

    scene_name = info.get("scene_name")
    object_count = info.get("object_count")
    print(f"\nscene={scene_name!r} objects={object_count} layers={layers.get('count')}\n")

    # Selection round-trip on real object names (if any).
    names = [obj["name"] for obj in objects.get("objects", [])][:3]
    if names:
        step(connection, "selection_set", "selection_set", {"object_names": names})
        step(connection, "selection_extend", "selection_extend", {"object_names": names[:1]})
        step(connection, "selection_subtract", "selection_subtract", {"object_names": names[1:2]})
        step(
            connection,
            "selection_filter",
            "selection_filter",
            {"pattern": names[0], "mode": "contains"},
        )
        step(connection, "selection_clear", "selection_clear")
        step(
            connection,
            "object_transform_get",
            "object_transform_get",
            {"object_name": names[0], "frame": 0},
        )
        step(
            connection,
            "list_object_attributes",
            "object_attributes_list",
            {"object_name": names[0]},
        )
        step(connection, "object_hierarchy", "object_hierarchy")

    layer_ids = [layer["id"] for layer in layers.get("layers", [])]
    if layer_ids:
        step(
            connection,
            "get_keyframes",
            "keyframes_get",
            {"layer_id": layer_ids[0], "frame_start": 0, "frame_end": 5},
        )
        step(connection, "active_layer_get", "active_layer_get")
        if object_count and names:
            step(
                connection,
                "read_telemetry",
                "telemetry_read",
                {"controller_ids": names[:2], "frames": [0]},
            )
            step(
                connection,
                "read_telemetry_range",
                "telemetry_read_range",
                {
                    "controller_ids": names[:2],
                    "frame_start": 0,
                    "frame_end": 4,
                    "step": 2,
                    "local": True,
                },
            )

    step(connection, "frame_set", "frame_set", {"frame": 3})
    step(connection, "frame_get_after_set", "frame_get")
    step(connection, "schema_size", "schema_get", {})
    step(connection, "undo", "undo")
    step(connection, "redo", "redo")

    if args.screenshot:
        step(connection, "screenshot_viewport", "viewport_screenshot", {"path": args.screenshot})

    if args.mutations:
        _mutations(connection, names, layer_ids)

    failures = [row for row in RESULTS if not row["ok"]]
    report = {
        "cascadeur": "2026.2.3",
        "url": connection.url,
        "scene": scene_name,
        "object_count": object_count,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total": len(RESULTS),
        "passed": len(RESULTS) - len(failures),
        "failed": len(failures),
        "results": RESULTS,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"\n{report['passed']}/{report['total']} steps passed")
    print(f"report: {report_path}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
