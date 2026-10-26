"""Wire-format tests for the expression payloads shipped to Cascadeur.

These do not need a Cascadeur install: they compile and evaluate the expressions
locally against the real in-app runtime source.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from poppet_mcp import _expression
from poppet_mcp.runtime import load_source, runtime_version, source_digest

REQUEST = json.dumps({"command": "ping", "params": {}})


def _eval_expression(expression: str) -> str:
    namespace = {"csc": types.SimpleNamespace(), "scene": None, "app": None}
    return eval(compile(expression, "<test>", "eval"), namespace)


@pytest.fixture(autouse=True)
def _clean_runtime_module():
    sys.modules.pop(_expression.RUNTIME_MODULE, None)
    yield
    sys.modules.pop(_expression.RUNTIME_MODULE, None)


def test_dispatch_expression_is_one_eval_able_line():
    expression = _expression.dispatch_expression(REQUEST, source_digest())
    assert "\n" not in expression
    compile(expression, "<test>", "eval")


def test_bootstrap_expression_is_one_eval_able_line():
    expression = _expression.bootstrap_expression(REQUEST, source_digest(), load_source())
    assert "\n" not in expression
    compile(expression, "<test>", "eval")


def test_dispatch_without_runtime_returns_bootstrap_marker():
    expression = _expression.dispatch_expression(REQUEST, source_digest())
    payload = json.loads(_eval_expression(expression))
    assert payload == {_expression.BOOTSTRAP_MARKER: True}


def test_bootstrap_loads_runtime_and_dispatch_answers_ping():
    expression = _expression.bootstrap_expression(REQUEST, source_digest(), load_source())
    payload = json.loads(_eval_expression(expression))
    assert payload["status"] == "success"
    assert payload["result"]["pong"] is True
    assert payload["result"]["runtime_version"] == runtime_version()
    assert sys.modules[_expression.RUNTIME_MODULE].RUNTIME_VERSION == runtime_version()


def test_dispatch_after_bootstrap_reuses_module():
    bootstrap = _expression.bootstrap_expression(REQUEST, source_digest(), load_source())
    _eval_expression(bootstrap)
    payload = json.loads(
        _eval_expression(_expression.dispatch_expression(REQUEST, source_digest()))
    )
    assert payload["status"] == "success"
    assert payload["result"]["pong"] is True


def test_digest_mismatch_triggers_bootstrap_marker():
    expression = _expression.dispatch_expression(REQUEST, "0" * 64)
    payload = json.loads(_eval_expression(expression))
    assert payload == {_expression.BOOTSTRAP_MARKER: True}


def test_bootstrap_stamps_shipped_source_digest():
    _eval_expression(_expression.bootstrap_expression(REQUEST, source_digest(), load_source()))
    module = sys.modules[_expression.RUNTIME_MODULE]
    assert module.SOURCE_DIGEST == source_digest()


def test_edited_runtime_source_changes_digest(monkeypatch):
    """Editing the shipped runtime must invalidate an already-loaded module."""
    import hashlib

    from poppet_mcp import runtime

    original = runtime.load_source()
    original_digest = runtime.source_digest()
    edited = original + "\n# edited\n"
    monkeypatch.setattr(runtime, "load_source", lambda: edited)
    monkeypatch.setattr(runtime, "_cached_digest", None)
    assert runtime.source_digest() != original_digest
    assert runtime.source_digest() == hashlib.sha256(edited.encode()).hexdigest()


def test_unknown_command_is_reported_as_structured_error():
    request = json.dumps({"command": "not_a_command", "params": {}})
    expression = _expression.bootstrap_expression(request, source_digest(), load_source())
    payload = json.loads(_eval_expression(expression))
    assert payload["status"] == "error"
    assert "unknown command" in payload["message"]


def test_expression_handles_unicode_and_quotes_in_params():
    request = json.dumps(
        {"command": "ping", "params": {"note": 'he said "caf\u00e9" \\o/'}},
        ensure_ascii=False,
    )
    expression = _expression.bootstrap_expression(request, source_digest(), load_source())
    payload = json.loads(_eval_expression(expression))
    assert payload["status"] == "success"
