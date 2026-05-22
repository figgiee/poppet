"""Reflect the csc.* namespace to JSON so the LLM has accurate signatures.

Implements spec §3 — dumps module/class/function tree with signatures and docstrings.
Cycle-guarded and depth-limited so it terminates on self-referential modules.
"""

import inspect
import json
import os
import sys


def extract_module_schema(module_obj, _seen=None, _depth=0, _max_depth=4):
    if _seen is None:
        _seen = set()
    if id(module_obj) in _seen or _depth > _max_depth:
        return {"_truncated": True}
    _seen.add(id(module_obj))

    schema = {}
    for name in dir(module_obj):
        if name.startswith("__"):
            continue
        try:
            attr = getattr(module_obj, name)
        except Exception as e:
            schema[name] = {"type": "unreadable", "error": str(e)}
            continue

        if inspect.ismodule(attr):
            schema[name] = extract_module_schema(attr, _seen, _depth + 1, _max_depth)
        elif inspect.isclass(attr):
            schema[name] = {
                "type": "class",
                "methods": [m for m in dir(attr) if not m.startswith("__")],
                "doc": (getattr(attr, "__doc__", "") or "").strip(),
            }
        elif callable(attr):
            try:
                sig = str(inspect.signature(attr))
            except (ValueError, TypeError):
                sig = "(...)"
            doc = getattr(attr, "__doc__", "") or ""
            schema[name] = {
                "type": "function",
                "signature": sig,
                "doc": doc.strip(),
            }
        else:
            schema[name] = {"type": "value", "repr": _safe_repr(attr)}
    return schema


def _safe_repr(obj):
    try:
        r = repr(obj)
        return r if len(r) <= 200 else r[:200] + "..."
    except Exception:
        return "<unrepresentable>"


def schema_cache_path():
    if sys.platform == "win32":
        base = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "poppet-mcp")
    else:
        base = os.path.expanduser("~/.local/share/poppet-mcp")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "csc_schema.json")


def dump_schema(path=None):
    import csc
    if path is None:
        path = schema_cache_path()
    schema = extract_module_schema(csc)
    payload = {
        "csc": schema,
        "cascadeur_version": _detect_version(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


def _detect_version():
    try:
        import csc
        v = getattr(csc, "Version", None)
        if v is None:
            return None
        # csc.Version may be a class/object — try several access patterns
        for attr in ("major", "minor", "patch", "to_string"):
            if hasattr(v, attr):
                continue
        return repr(v)
    except Exception:
        return None
