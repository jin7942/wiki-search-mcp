"""OS 서비스 유닛 생성 회귀 테스트 (v0.3.0, P2 자동 재기동).

launchd plist / systemd service 텍스트가 daemon 자동 재기동에 필요한 핵심
지시(KeepAlive / Restart=always)와 올바른 ExecStart 를 담는지 고정한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_search_mcp.infrastructure.daemon.service_unit import (
    build_launchd_unit,
    build_systemd_unit,
    resolve_cli_path,
)

_CLI = "/usr/local/bin/wiki-search-mcp"
_WIKI = Path("/home/u/vault")
_LOG = Path("/home/u/.local/state/wiki-search-mcp/abc/daemon.log")


class TestLaunchd:
    def test_keepalive_and_runatload(self) -> None:
        u = build_launchd_unit(_WIKI, _CLI, _LOG)
        assert "<key>KeepAlive</key>" in u.content
        assert "<true/>" in u.content
        assert "RunAtLoad" in u.content

    def test_program_arguments_contains_foreground_start(self) -> None:
        u = build_launchd_unit(_WIKI, _CLI, _LOG)
        assert _CLI in u.content
        assert "daemon" in u.content
        assert "start" in u.content
        assert "--foreground" in u.content
        assert str(_WIKI) in u.content

    def test_label_and_path(self) -> None:
        u = build_launchd_unit(_WIKI, _CLI, _LOG)
        assert u.kind == "launchd"
        assert u.label.startswith("com.wiki-search-mcp.")
        assert u.unit_path.name.endswith(".plist")
        assert "LaunchAgents" in str(u.unit_path)

    def test_fallback_cli_split_into_args(self) -> None:
        """폴백 형태(``<python> -m ...``)는 공백으로 split 되어 각 argv 가 된다."""
        cli = "/venv/bin/python -m wiki_search_mcp.adapters.cli.main"
        u = build_launchd_unit(_WIKI, cli, _LOG)
        assert "<string>/venv/bin/python</string>" in u.content
        assert "<string>-m</string>" in u.content
        assert "<string>wiki_search_mcp.adapters.cli.main</string>" in u.content


class TestSystemd:
    def test_restart_always(self) -> None:
        u = build_systemd_unit(_WIKI, _CLI, _LOG)
        assert "Restart=always" in u.content
        assert "WantedBy=default.target" in u.content

    def test_exec_start(self) -> None:
        u = build_systemd_unit(_WIKI, _CLI, _LOG)
        assert f"ExecStart={_CLI} daemon start {_WIKI} --foreground" in u.content

    def test_logs_to_daemon_log_file(self) -> None:
        """daemon logs 와 일관되도록 StandardOutput/Error 가 로그 파일을 가리킨다."""
        u = build_systemd_unit(_WIKI, _CLI, _LOG)
        assert f"StandardOutput=append:{_LOG}" in u.content
        assert f"StandardError=append:{_LOG}" in u.content

    def test_label_and_path(self) -> None:
        u = build_systemd_unit(_WIKI, _CLI, _LOG)
        assert u.kind == "systemd"
        assert u.unit_path.name.endswith(".service")
        assert "systemd/user" in str(u.unit_path)


def test_same_wiki_same_label() -> None:
    """같은 vault 는 항상 같은 label 을 받아 idempotent install/uninstall 가능."""
    a = build_systemd_unit(_WIKI, _CLI, _LOG)
    b = build_launchd_unit(_WIKI, _CLI, _LOG)
    assert a.label == b.label


def test_resolve_cli_path_returns_something() -> None:
    cli = resolve_cli_path()
    assert cli
    # 콘솔 스크립트 절대경로 또는 ``python -m`` 폴백
    assert "wiki-search-mcp" in cli or "wiki_search_mcp.adapters.cli.main" in cli
