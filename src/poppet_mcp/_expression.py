"""Build the single Python *expression* Cascadeur's script server evaluates.

Cascadeur 2026.2's built-in server (``scripts/mcp/script_server/server.py``)
compiles submitted code with ``mode="eval"`` first and only falls back to
``exec`` on ``SyntaxError``. The response body differs by path: the ``eval``
path returns the value's ``repr`` in ``result["value"]``, while the ``exec``
path always returns an empty string. So everything we submit has to be **one
expression** if we want data back.

We therefore wrap arbitrarily large multi-statement programs in a lambda that
``exec``s them in a private namespace and yields a result variable::

    (lambda __ns__: (exec(compile(<source>, "<cascadeur-mcp>", "exec"), __ns__),
                     __ns__.get("__cascadeur_mcp_result__"))[1])(
        {"csc": csc, "scene": scene, "app": app})

``csc``, ``scene`` and ``app`` come from the namespace the script server already
injects, so the wrapped program has the same privileges as any bundled script.

The submitted program itself runs in two modes:

* **dispatch** (steady state) — call ``poppet_rt.dispatch(...)`` if the runtime
  module is already loaded and its source digest matches the source this client
  ships.
* **bootstrap** (first call, after a Cascadeur restart, or after upgrading
  cascadeur-mcp) — execute the runtime source into a fresh ``poppet_rt`` module in
  ``sys.modules``, stamp its source digest, then dispatch.

The digest doubles as the wire-contract identity: a Cascadeur process holding an
older runtime can never answer tool calls with stale handlers, because the client
only trusts a module whose stamped digest matches the source it would ship.
"""

from __future__ import annotations

RUNTIME_MODULE = "poppet_rt"
RESULT_VAR = "__cascadeur_mcp_result__"
DIGEST_ATTR = "SOURCE_DIGEST"
BOOTSTRAP_MARKER = "__cascadeur_mcp_bootstrap_required__"


def wrap_expression(source: str) -> str:
    """Wrap a multi-statement program into one ``eval``-able expression."""
    return (
        "(lambda __ns__: (exec(compile("
        + repr(source)
        + ', "<cascadeur-mcp>", "exec"), __ns__), __ns__.get("'
        + RESULT_VAR
        + '"))[1])('
        + '{"csc": csc, "scene": scene, "app": app})'
    )


def build_dispatch_source(request_json: str, digest: str) -> str:
    """Program for steady-state calls: dispatch through the loaded runtime."""
    return (
        "import json as __json__\n"
        "import sys\n"
        f'__m__ = sys.modules.get("{RUNTIME_MODULE}")\n'
        f'if __m__ is not None and getattr(__m__, "{DIGEST_ATTR}", "") == {digest!r}:\n'
        f"    {RESULT_VAR} = __m__.dispatch({request_json!r}, scene, csc, app)\n"
        "else:\n"
        f"    {RESULT_VAR} = __json__.dumps({{{BOOTSTRAP_MARKER!r}: True}})\n"
    )


def build_bootstrap_source(request_json: str, digest: str, runtime_source: str) -> str:
    """Program for (re)loading the runtime into Cascadeur, then dispatching."""
    return (
        "import sys\n"
        "import types\n"
        f'__m__ = sys.modules.get("{RUNTIME_MODULE}")\n'
        f'if __m__ is None or getattr(__m__, "{DIGEST_ATTR}", "") != {digest!r}:\n'
        f'    __m__ = types.ModuleType("{RUNTIME_MODULE}")\n'
        "    exec(compile("
        + repr(runtime_source)
        + f', "<{RUNTIME_MODULE}>", "exec"), __m__.__dict__)\n'
        f"    __m__.{DIGEST_ATTR} = {digest!r}\n"
        f'    sys.modules["{RUNTIME_MODULE}"] = __m__\n'
        f"{RESULT_VAR} = __m__.dispatch({request_json!r}, scene, csc, app)\n"
    )


def dispatch_expression(request_json: str, digest: str) -> str:
    """Full ``eval``-able expression for the steady-state path."""
    return wrap_expression(build_dispatch_source(request_json, digest))


def bootstrap_expression(request_json: str, digest: str, runtime_source: str) -> str:
    """Full ``eval``-able expression for the bootstrap path."""
    return wrap_expression(build_bootstrap_source(request_json, digest, runtime_source))
