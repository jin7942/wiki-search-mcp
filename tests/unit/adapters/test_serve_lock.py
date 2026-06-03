"""watcher 소유권 락 회귀 테스트 (v0.5.0, 동시 MCP 클라이언트 지원).

v0.3.0~0.4.0 에서는 serve 단일 인스턴스 락이 두 번째 serve 를 sys.exit(0) 으로
종료시켜, 같은 vault 에 Claude Code + Claude Desktop 이 동시에 붙지 못했다.

v0.5.0 부터 serve 락은 "watcher 소유권" 표식으로 의미가 바뀐다:
- 락을 잡은 serve 만 watcher(자동 reindex)를 돌린다.
- 락을 못 잡은 serve 는 종료하지 않고 검색 전용으로 계속 동작한다.
- reindex 동시성 안전은 indexer 의 cross-process reindex flock 이 보장한다.
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


def test_reindex_lock_file_is_shared_path(tmp_path: Path) -> None:
    """reindex 락은 serve/daemon 락과 별개의 vault-공유 경로여야 한다."""
    from wiki_search_mcp.infrastructure.daemon.paths import (
        reindex_lock_file,
        serve_lock_file,
        state_lock_file,
    )

    wiki = tmp_path / "vault"
    wiki.mkdir()
    assert reindex_lock_file(wiki).name == "reindex.lock"
    assert reindex_lock_file(wiki) != serve_lock_file(wiki)
    assert reindex_lock_file(wiki) != state_lock_file(wiki)
    # 같은 vault 면 항상 같은 경로 (cross-process 공유의 전제)
    assert reindex_lock_file(wiki) == reindex_lock_file(wiki)


def test_first_serve_owns_watcher(tmp_path: Path) -> None:
    """첫 serve 는 watcher 소유권 락을 잡는다 (True)."""
    from wiki_search_mcp.adapters.mcp import server

    wiki = tmp_path / "vault"
    wiki.mkdir()
    try:
        assert server._acquire_watcher_lock(wiki) is True
    finally:
        if server._serve_lock is not None:
            server._serve_lock.release()
            server._serve_lock = None


def test_second_serve_runs_search_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """두 번째 serve 는 watcher 락을 못 잡아도 종료하지 않고 False 만 반환.

    (False = 검색 전용 모드. server.main 은 sys.exit 하지 않는다.)
    """
    from wiki_search_mcp.infrastructure.daemon.paths import (
        serve_lock_file,
        serve_pid_file,
    )
    from wiki_search_mcp.infrastructure.daemon.pidfile import PidLock
    from wiki_search_mcp.adapters.mcp import server

    wiki = tmp_path / "vault"
    wiki.mkdir()

    holder = PidLock(serve_lock_file(wiki), serve_pid_file(wiki))
    holder.acquire()
    try:
        # 두 번째 serve: 락 실패 → False (검색 전용), 예외/종료 없음
        assert server._acquire_watcher_lock(wiki) is False
    finally:
        holder.release()


def test_cross_process_lock_serializes(tmp_path: Path) -> None:
    """cross_process_lock 은 같은 경로에 대해 동시 획득을 막고, 해제 후 재획득 가능."""
    from wiki_search_mcp.infrastructure.daemon.paths import reindex_lock_file
    from wiki_search_mcp.infrastructure.daemon.pidfile import cross_process_lock

    wiki = tmp_path / "vault"
    wiki.mkdir()
    lock_path = reindex_lock_file(wiki)

    with cross_process_lock(lock_path, timeout=1.0) as locked_outer:
        assert locked_outer is True
        # 같은 프로세스라도 flock 은 fd 단위라 별도 fd 로 LOCK_NB 시도 시 대기→timeout.
        with cross_process_lock(lock_path, timeout=0.3) as locked_inner:
            assert locked_inner is False  # 이미 점유 중 → timeout 으로 False

    # 해제 후 다시 획득 가능
    with cross_process_lock(lock_path, timeout=1.0) as locked_again:
        assert locked_again is True
