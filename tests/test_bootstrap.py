"""Tests for Poppet's Cascadeur-side bootstrap and port discovery."""

from __future__ import annotations

import io
import json

from poppet_mcp import bootstrap_cli
from poppet_mcp import cascadeur_connection as conn


def test_bootstrap_source_is_valid_python_and_has_the_keeper():
    from importlib import resources

    # Read the shipped script as text; importing it would execute main().
    source = (
        resources.files("poppet_mcp").joinpath("cascadeur_bootstrap.py").read_text(encoding="utf-8")
    )
    compile(source, "<bootstrap>", "exec")
    assert "QTimer" in source
    assert "scene_idle_manager.run" in source
    assert "server.json" in source
    # Executed inside Cascadeur: it imports Cascadeur's own modules only.
    assert "import scripts.mcp.script_server.server as server_module" in source


def test_bootstrap_cli_writes_file_and_prints_console_line(tmp_path, capsys):
    target = tmp_path / "cascadeur_bootstrap.py"
    assert bootstrap_cli.main(["--write", str(target), "--port", "8766"]) == 0
    written = target.read_text(encoding="utf-8")
    assert "DEFAULT_PORT = 8766" in written
    compile(written, "<bootstrap>", "exec")
    out = capsys.readouterr().out
    assert "Python Console" in out
    assert f'exec(open(r"{target}").read())' in out


def test_discovered_url_reads_server_json(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\fake-localappdata")
    monkeypatch.setattr(
        "builtins.open",
        lambda *args, **kwargs: io.StringIO(json.dumps({"ok": True, "port": 8766})),
    )
    assert conn._discovered_url() == "http://127.0.0.1:8766"


def test_discovered_url_falls_back_on_bad_payload(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\fake-localappdata")
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO("not json"))
    assert conn._discovered_url() is None


def test_connection_prefers_env_then_discovery(monkeypatch):
    monkeypatch.setenv("POPPET_URL", "")
    monkeypatch.setattr(conn, "_discovered_url", lambda: "http://127.0.0.1:8766")
    assert conn.CascadeurConnection().url == "http://127.0.0.1:8766"

    monkeypatch.setenv("POPPET_URL", "http://127.0.0.1:9999")
    assert conn.CascadeurConnection().url == "http://127.0.0.1:9999"

    monkeypatch.setattr(conn, "_discovered_url", lambda: None)
    monkeypatch.delenv("POPPET_URL")
    assert conn.CascadeurConnection().url == conn.DEFAULT_URL


def test_runtime_screenshot_reports_async_render(monkeypatch):
    """The handler must not benchmark the renderer; the tool layer polls."""
    from tests.runtime_loader import runtime

    class _Csc:
        class tools:  # noqa: N801 - mimic the csc.tools namespace
            class RenderParameters:
                def __init__(self):
                    self.width = 0
                    self.height = 0
                    self.samples = 0

    class _App:
        def current_scene(self):
            return object()

        def get_tools_manager(self):
            return self

        def get_tool(self, name):
            return self

        def take_image(self, scene_view, render_parameters, file_name):
            return None

    class _CscModule:
        app = None

    module = _CscModule()
    module.app = _App()
    module.app.get_application = lambda: module.app
    module.tools = _Csc
    module.tools.RenderParameters = _Csc.tools.RenderParameters

    monkeypatch.setitem(__import__("sys").modules, "csc", module)
    monkeypatch.setattr(runtime.os.path, "exists", lambda p: False)
    monkeypatch.setattr(runtime.os, "makedirs", lambda *a, **k: None)

    result = runtime._d_viewport_screenshot({"path": r"C:\fake\shot.png"}, object())
    assert result["render_started"] is True
    assert result["exists"] is False
    assert result["path"].endswith("shot.png")
