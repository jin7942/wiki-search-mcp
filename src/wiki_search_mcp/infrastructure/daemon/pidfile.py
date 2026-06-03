"""PID 파일 + ``fcntl.flock`` 기반 단일 인스턴스 보장.

POSIX 전용. Windows는 v0.2.0 미지원 (사용자에게 README에서 명시).
"""

from __future__ import annotations

import errno
import fcntl
import logging
import os
import signal
import time
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType

from wiki_search_mcp.core.exceptions import DaemonError

logger = logging.getLogger(__name__)


@contextmanager
def cross_process_lock(
    lock_path: Path, *, timeout: float = 30.0, poll_interval: float = 0.1
) -> Iterator[bool]:
    """여러 프로세스가 공유하는 임계구역 flock (blocking, timeout).

    ``PidLock`` 과 달리 단일 인스턴스 표식이 아니라 reindex 같은 쓰기 구간을
    프로세스 간에 직렬화하기 위한 락이다. 같은 ``lock_path`` 를 쓰는 다른
    프로세스가 락을 쥐고 있으면 ``timeout`` 까지 대기하다가, 끝내 못 잡으면
    ``False`` 를 yield 한다 (호출자가 skip 하거나 강행할지 결정).

    Args:
        lock_path: flock 대상 파일 경로 (vault 별 단일 경로여야 의미가 있다).
        timeout: 락 획득 대기 최대 초.
        poll_interval: non-blocking 재시도 간격(초).

    Yields:
        락을 획득했으면 ``True``, timeout 으로 실패했으면 ``False``.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    acquired = False
    deadline = time.monotonic() + max(timeout, 0.0)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    logger.warning(
                        "cross_process_lock timeout after %.1fs: %s",
                        timeout,
                        lock_path,
                    )
                    break
                time.sleep(poll_interval)
        yield acquired
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        else:
            os.close(fd)


def _read_pid(pid_path: Path) -> int | None:
    """PID 파일 내용을 정수로 읽기. 실패 시 ``None``."""
    try:
        text = pid_path.read_text(encoding="utf-8").strip()
        return int(text) if text else None
    except (FileNotFoundError, ValueError, OSError):
        return None


def _pid_alive(pid: int) -> bool:
    """프로세스가 살아있는지 ``kill -0`` 으로 확인."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # 다른 사용자 소유 프로세스라도 살아있으면 True
        return True
    except OSError as e:
        if e.errno == errno.ESRCH:
            return False
        return True


class PidLock:
    """flock 기반 단일 인스턴스 락.

    ``with PidLock(lock_path, pid_path):`` 형식으로 사용. 중복 실행 시 ``DaemonError("ALREADY_RUNNING")``.
    """

    def __init__(self, lock_path: Path, pid_path: Path):
        self._lock_path = Path(lock_path)
        self._pid_path = Path(pid_path)
        self._fd: int | None = None

    def acquire(self) -> None:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            os.close(fd)
            existing = _read_pid(self._pid_path)
            raise DaemonError.of(
                f"daemon already running (pid={existing})",
                code="ALREADY_RUNNING",
                details={"pid": existing},
            ) from e
        self._fd = fd
        self._pid_path.write_text(str(os.getpid()), encoding="utf-8")
        logger.debug("PidLock acquired: lock=%s pid=%s", self._lock_path, os.getpid())

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None
        try:
            self._pid_path.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self) -> "PidLock":
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()

    @staticmethod
    def is_alive(pid_path: Path) -> tuple[bool, int | None]:
        """PID 파일 기준으로 daemon이 살아있는지 확인."""
        pid = _read_pid(Path(pid_path))
        if pid is None:
            return False, None
        return _pid_alive(pid), pid

    @staticmethod
    def terminate(pid: int, *, timeout: float = 10.0) -> bool:
        """SIGTERM → timeout → SIGKILL. 성공 시 True.

        Args:
            pid: 종료할 프로세스 PID
            timeout: SIGTERM 후 대기할 최대 초

        Returns:
            정상 종료 또는 강제 종료 성공 시 True, 권한 부족 등 실패 시 False
        """
        import time

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not _pid_alive(pid):
                return True
            time.sleep(0.2)

        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False

        time.sleep(0.5)
        return not _pid_alive(pid)
