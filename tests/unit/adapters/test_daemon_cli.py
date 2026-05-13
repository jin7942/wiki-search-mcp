"""daemon CLI 단위 테스트 — DaemonRunner는 mock."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from wiki_search_mcp.adapters.cli.main import main
from wiki_search_mcp.adapters.cli import daemon_cli


@pytest.fixture(autouse=True)
def _xdg_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def test_daemon_help_lists_subcommands() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["daemon", "--help"])
    assert result.exit_code == 0
    assert "start" in result.output
    assert "stop" in result.output
    assert "status" in result.output
    assert "rollback" in result.output


def test_status_when_not_running(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    runner = CliRunner()
    result = runner.invoke(main, ["daemon", "status", str(wiki)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["alive"] is False
    assert data["pid"] is None


def test_stop_when_not_running(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    runner = CliRunner()
    result = runner.invoke(main, ["daemon", "stop", str(wiki)])
    assert result.exit_code != 0
    assert "실행 중이 아닙니다" in result.output


def test_resolve_wiki_path_from_explicit_arg(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    resolved = daemon_cli._resolve_wiki_path(str(wiki))
    assert resolved == wiki.resolve()


def test_resolve_wiki_path_from_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wiki = tmp_path / "vault"
    wiki.mkdir()
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "wiki-search": {
                        "command": "wiki-search-mcp",
                        "args": ["serve", str(wiki)],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(daemon_cli, "_CONFIG_LOCATIONS", (cfg,))
    resolved = daemon_cli._resolve_wiki_path(None)
    assert resolved == wiki.resolve()


def test_resolve_wiki_path_raises_when_no_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(daemon_cli, "_CONFIG_LOCATIONS", (tmp_path / "missing.json",))
    with pytest.raises(click.ClickException) as exc:
        daemon_cli._resolve_wiki_path(None)
    assert "wiki 경로를 찾을 수 없습니다" in exc.value.message


def test_resolve_wiki_path_raises_when_config_missing_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setattr(daemon_cli, "_CONFIG_LOCATIONS", (cfg,))
    with pytest.raises(click.ClickException):
        daemon_cli._resolve_wiki_path(None)


def test_status_without_arg_uses_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wiki = tmp_path / "vault"
    wiki.mkdir()
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "wiki-search": {"command": "wiki-search-mcp", "args": ["serve", str(wiki)]}
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(daemon_cli, "_CONFIG_LOCATIONS", (cfg,))
    runner = CliRunner()
    result = runner.invoke(main, ["daemon", "status"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["alive"] is False
    assert Path(data["wiki_path"]) == wiki.resolve()


def test_start_foreground_invokes_runner(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    fake_runner = MagicMock()
    fake_class = MagicMock(return_value=fake_runner)
    runner = CliRunner()
    with patch("wiki_search_mcp.adapters.cli.daemon_cli._check_claude_cli_or_die"), patch(
        "wiki_search_mcp.adapters.cli.daemon_cli._check_claude_logged_in_or_hint"
    ), patch("wiki_search_mcp.infrastructure.daemon.runner.DaemonRunner", fake_class):
        result = runner.invoke(
            main,
            ["daemon", "start", str(wiki), "--foreground", "--rate-per-minute", "10"],
        )
    assert result.exit_code == 0, result.output
    fake_class.assert_called_once()
    opts = fake_class.call_args.args[0]
    assert opts.rate_per_minute == 10
    fake_runner.start.assert_called_once()
