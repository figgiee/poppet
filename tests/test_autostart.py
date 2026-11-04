"""Tests for the optional Cascadeur-side autostart add-on."""

from __future__ import annotations

import json

from poppet_mcp import autostart_cli


def _settings(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {"Python": {"Path": [str(tmp_path / "user_scripts")], "Events": ["poppet_events"]}}
        ),
        encoding="utf-8",
    )
    return settings


def test_install_writes_handler_package_bootstrap_and_settings(tmp_path):
    user_scripts = tmp_path / "user_scripts"
    settings = _settings(tmp_path)
    bootstrap = tmp_path / "cascadeur-mcp" / "cascadeur_bootstrap.py"

    result = autostart_cli.install(
        user_scripts=user_scripts, settings_path=settings, bootstrap_path=bootstrap, port=8766
    )

    package = user_scripts / "poppet_autostart"
    assert (package / "application_started" / "autostart.py").is_file()
    for event in ("scene_created", "scene_opened", "scene_activated"):
        assert (package / event / "autostart_retry.py").is_file()
    assert bootstrap.is_file()
    assert "DEFAULT_PORT = 8766" in bootstrap.read_text(encoding="utf-8")
    assert result["settings_event_added"] is True
    events = json.loads(settings.read_text(encoding="utf-8"))["Python"]["Events"]
    assert "poppet_autostart" in events
    assert (tmp_path / "settings.json.cascadeur-mcp.backup").is_file()


def test_install_creates_settings_when_missing(tmp_path):
    user_scripts = tmp_path / "user_scripts"
    settings = tmp_path / "missing" / "settings.json"
    bootstrap = tmp_path / "bootstrap.py"
    result = autostart_cli.install(
        user_scripts=user_scripts, settings_path=settings, bootstrap_path=bootstrap
    )
    assert result["settings_event_added"] is True
    events = json.loads(settings.read_text(encoding="utf-8"))["Python"]["Events"]
    assert events == ["poppet_autostart"]
    compile(bootstrap.read_text(encoding="utf-8"), "<bootstrap>", "exec")


def test_installed_handler_is_valid_python(tmp_path):
    user_scripts = tmp_path / "user_scripts"
    settings = _settings(tmp_path)
    autostart_cli.install(
        user_scripts=user_scripts,
        settings_path=settings,
        bootstrap_path=tmp_path / "bootstrap.py",
    )
    handlers = user_scripts / "poppet_autostart"
    for handler in handlers.rglob("*.py"):
        compile(handler.read_text(encoding="utf-8"), str(handler), "exec")
    retry = (handlers / "scene_created" / "autostart_retry.py").read_text(encoding="utf-8")
    assert "server.is_running()" in retry
    assert "{{" not in retry and "namespace = {" in retry
    assert "cascadeur_bootstrap.py" in (
        handlers / "application_started" / "autostart.py"
    ).read_text(encoding="utf-8")


def test_install_is_idempotent(tmp_path):
    user_scripts = tmp_path / "user_scripts"
    settings = _settings(tmp_path)
    bootstrap = tmp_path / "bootstrap.py"
    autostart_cli.install(
        user_scripts=user_scripts, settings_path=settings, bootstrap_path=bootstrap
    )
    second = autostart_cli.install(
        user_scripts=user_scripts, settings_path=settings, bootstrap_path=bootstrap
    )
    assert second["settings_event_added"] is False
    events = json.loads(settings.read_text(encoding="utf-8"))["Python"]["Events"]
    assert events.count("poppet_autostart") == 1
    assert "poppet_events" in events


def test_uninstall_removes_package_and_settings_entry(tmp_path):
    user_scripts = tmp_path / "user_scripts"
    settings = _settings(tmp_path)
    bootstrap = tmp_path / "bootstrap.py"
    autostart_cli.install(
        user_scripts=user_scripts, settings_path=settings, bootstrap_path=bootstrap
    )
    result = autostart_cli.uninstall(user_scripts=user_scripts, settings_path=settings)
    assert result["package_removed"] is True
    assert not (user_scripts / "poppet_autostart").exists()
    assert (
        "poppet_autostart"
        not in json.loads(settings.read_text(encoding="utf-8"))["Python"]["Events"]
    )


def test_status_reports_installed_state(tmp_path):
    user_scripts = tmp_path / "user_scripts"
    settings = _settings(tmp_path)
    bootstrap = tmp_path / "bootstrap.py"
    before = autostart_cli.status(
        user_scripts=user_scripts, settings_path=settings, bootstrap_path=bootstrap
    )
    assert before["installed"] is False
    autostart_cli.install(
        user_scripts=user_scripts, settings_path=settings, bootstrap_path=bootstrap
    )
    after = autostart_cli.status(
        user_scripts=user_scripts, settings_path=settings, bootstrap_path=bootstrap
    )
    assert after["installed"] is True
    assert (
        autostart_cli.main(
            [
                "--status",
                "--user-scripts",
                str(user_scripts),
                "--settings",
                str(settings),
                "--bootstrap",
                str(bootstrap),
            ]
        )
        == 0
    )


def test_cli_install_and_uninstall_roundtrip(tmp_path):
    user_scripts = tmp_path / "user_scripts"
    settings = _settings(tmp_path)
    bootstrap = tmp_path / "bootstrap.py"
    common = [
        "--user-scripts",
        str(user_scripts),
        "--settings",
        str(settings),
        "--bootstrap",
        str(bootstrap),
    ]
    assert autostart_cli.main(["--install", *common]) == 0
    assert (user_scripts / "poppet_autostart").is_dir()
    assert autostart_cli.main(["--uninstall", *common]) == 0
    assert not (user_scripts / "poppet_autostart").exists()
