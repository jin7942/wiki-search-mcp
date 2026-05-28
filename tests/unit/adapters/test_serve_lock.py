"""serve 단일 인스턴스 락 회귀 테스트 (v0.3.0, P2 중복 기동 방지).

같은 vault 에 대해 MCP serve 가 중복 기동되면 file watcher 가 같은 파일을 두 번
보고 reindex 가 중복 트리거되어 LanceDB 매니페스트 race 가 날 수 있다. serve 진입점이
serve 전용 PidLock 을 잡아 두 번째 인스턴스를 거부해야 한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _xdg_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def test_serve_lock_files_are_separate_from_daemon(tmp_path: Path) -> None:
    """serve 락/PID 파일은 daemon 것과 구분되어야 한다 (둘이 공존 가능)."""
    from wiki_search_mcp.infrastructure.daemon.paths import (
        pid_file,
        serve_lock_file,
        serve_pid_file,
        state_lock_file,
    )

    wiki = tmp_path / "vault"
    wiki.mkdir()
    assert serve_pid_file(wiki) != pid_file(wiki)
    assert serve_lock_file(wiki) != state_lock_file(wiki)
    assert serve_pid_file(wiki).name == "serve.pid"
    assert serve_lock_file(wiki).name == "serve.lock"


def test_second_serve_lock_rejected(tmp_path: Path) -> None:
    """첫 serve 가 락을 잡으면 두 번째 acquire 시도는 ALREADY_RUNNING 으로 거부."""
    from wiki_search_mcp.core.exceptions import DaemonError
    from wiki_search_mcp.infrastructure.daemon.paths import (
        serve_lock_file,
        serve_pid_file,
    )
    from wiki_search_mcp.infrastructure.daemon.pidfile import PidLock

    wiki = tmp_path / "vault"
    wiki.mkdir()

    first = PidLock(serve_lock_file(wiki), serve_pid_file(wiki))
    first.acquire()
    try:
        second = PidLock(serve_lock_file(wiki), serve_pid_file(wiki))
        with pytest.raises(DaemonError) as exc:
            second.acquire()
        assert exc.value.context.code == "ALREADY_RUNNING"
    finally:
        first.release()


def test_acquire_serve_lock_returns_false_when_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_acquire_serve_lock`` 은 이미 락이 잡혀 있으면 False 를 반환해야 한다.

    server.main() 은 False 면 ``sys.exit(0)`` 으로 깨끗하게 빠진다.
    """
    from wiki_search_mcp.adapters.mcp import server
    from wiki_search_mcp.infrastructure.daemon.paths import (
        serve_lock_file,
        serve_pid_file,
    )
    from wiki_search_mcp.infrastructure.daemon.pidfile import PidLock

    wiki = tmp_path / "vault"
    wiki.mkdir()

    holder = PidLock(serve_lock_file(wiki), serve_pid_file(wiki))
    holder.acquire()
    try:
        assert server._acquire_serve_lock(wiki) is False
    finally:
        holder.release()


def test_acquire_serve_lock_succeeds_when_free(tmp_path: Path) -> None:
    from wiki_search_mcp.adapters.mcp import server

    wiki = tmp_path / "vault"
    wiki.mkdir()
    try:
        assert server._acquire_serve_lock(wiki) is True
    finally:
        if server._serve_lock is not None:
            server._serve_lock.release()
            server._serve_lock = None
