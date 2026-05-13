"""Daemon paths 헬퍼 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_search_mcp.infrastructure.daemon import paths as paths_mod


def test_state_dir_uses_xdg_state_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    d = paths_mod.state_dir(wiki)
    assert d.exists() and d.is_dir()
    assert str(d).startswith(str(tmp_path / "state" / "wiki-search-mcp"))


def test_distinct_wikis_get_distinct_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    a = tmp_path / "wiki-a"
    b = tmp_path / "wiki-b"
    a.mkdir()
    b.mkdir()
    assert paths_mod.state_dir(a) != paths_mod.state_dir(b)


def test_helper_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    assert paths_mod.pid_file(wiki).name == "daemon.pid"
    assert paths_mod.state_lock_file(wiki).name == "daemon.lock"
    assert paths_mod.log_file(wiki).name == "daemon.log"
    assert paths_mod.status_file(wiki).name == "daemon_status.json"
    assert paths_mod.pending_jsonl(wiki).name == "pending.jsonl"
    assert paths_mod.applied_jsonl(wiki).name == "applied.jsonl"
