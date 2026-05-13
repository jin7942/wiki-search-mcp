"""PidLock 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_search_mcp.core.exceptions import DaemonError
from wiki_search_mcp.infrastructure.daemon.pidfile import PidLock


def test_acquire_then_release(tmp_path: Path) -> None:
    lock = PidLock(tmp_path / "daemon.lock", tmp_path / "daemon.pid")
    with lock:
        assert (tmp_path / "daemon.pid").exists()
    assert not (tmp_path / "daemon.pid").exists()


def test_duplicate_acquire_raises(tmp_path: Path) -> None:
    a = PidLock(tmp_path / "daemon.lock", tmp_path / "daemon.pid")
    b = PidLock(tmp_path / "daemon.lock", tmp_path / "daemon.pid")
    a.acquire()
    try:
        with pytest.raises(DaemonError) as exc:
            b.acquire()
        assert exc.value.context.code == "ALREADY_RUNNING"
    finally:
        a.release()


def test_reacquire_after_release(tmp_path: Path) -> None:
    lock_path = tmp_path / "daemon.lock"
    pid_path = tmp_path / "daemon.pid"
    a = PidLock(lock_path, pid_path)
    a.acquire()
    a.release()
    b = PidLock(lock_path, pid_path)
    b.acquire()
    b.release()


def test_is_alive_when_no_pidfile(tmp_path: Path) -> None:
    alive, pid = PidLock.is_alive(tmp_path / "missing.pid")
    assert (alive, pid) == (False, None)


def test_is_alive_detects_dead_pid(tmp_path: Path) -> None:
    p = tmp_path / "daemon.pid"
    # 일반적으로 존재 불가능한 매우 큰 PID로 죽은 프로세스 시뮬레이션
    p.write_text("999999", encoding="utf-8")
    alive, pid = PidLock.is_alive(p)
    assert alive is False
    assert pid == 999999


def test_is_alive_detects_self(tmp_path: Path) -> None:
    import os

    p = tmp_path / "daemon.pid"
    p.write_text(str(os.getpid()), encoding="utf-8")
    alive, pid = PidLock.is_alive(p)
    assert alive is True
    assert pid == os.getpid()
