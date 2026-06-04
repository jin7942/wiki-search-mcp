from __future__ import annotations

"""Wiki File Watcher - 파일 변경 시 자동 reindex 트리거.

watchdog을 사용하여 wiki/pages 디렉토리의 .md 파일 변경을 감시합니다.
디바운싱을 적용하여 연속 변경 시 마지막 변경 후 일정 시간 대기 후 reindex합니다.
"""

import logging
import threading
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class DebouncedReindexHandler(FileSystemEventHandler):
    """파일 변경 감지 후 디바운싱하여 reindex 트리거.

    연속 변경 시 마지막 변경으로부터 debounce_seconds 후에
    단 한 번만 reindex_callback을 호출합니다.

    Attributes:
        debounce_seconds: 디바운스 딜레이 (초)
        reindex_callback: reindex 실행 함수
    """

    def __init__(
        self,
        reindex_callback: Callable[[], None],
        debounce_seconds: float = 2.0,
    ):
        """DebouncedReindexHandler 초기화.

        Args:
            reindex_callback: 디바운싱 후 호출할 콜백 함수
            debounce_seconds: 디바운스 딜레이 (초)
        """
        super().__init__()
        self.reindex_callback = reindex_callback
        self.debounce_seconds = debounce_seconds
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        # 중지 요청 플래그: set 이면 타이머가 발화해도 콜백을 실행하지 않는다.
        self._stopping = threading.Event()
        # 콜백 실행 중 표시: cancel()/stop() 이 진행 중 콜백 완료를 대기할 수 있다.
        self._idle = threading.Event()
        self._idle.set()  # 초기 상태: 실행 중 아님

    def _schedule_reindex(self) -> None:
        """타이머 리셋 후 reindex 예약."""
        with self._lock:
            # 중지 중이면 새 예약을 하지 않는다.
            if self._stopping.is_set():
                return
            if self._timer is not None:
                self._timer.cancel()

            self._timer = threading.Timer(
                self.debounce_seconds,
                self._execute_reindex,
            )
            self._timer.daemon = True
            self._timer.start()

    def _execute_reindex(self) -> None:
        """reindex 콜백 실행."""
        with self._lock:
            self._timer = None
            # 중지 요청됐으면 콜백 자체를 실행하지 않는다(stop 중 불필요한
            # 장시간 reindex 진입 방지).
            if self._stopping.is_set():
                return
            # 콜백 시작 — idle 해제(실행 중 표시).
            self._idle.clear()

        logger.info("Auto-reindex triggered")
        try:
            self.reindex_callback()
        except Exception as e:
            logger.error(f"Auto-reindex failed: {e}")
        finally:
            # 콜백 종료 — stop()/cancel() 이 대기 중이면 깨운다.
            self._idle.set()

    def on_any_event(self, event: FileSystemEvent) -> None:
        """파일시스템 이벤트 처리.

        .md 파일의 생성, 수정, 삭제, 이동 이벤트만 처리합니다.
        디렉토리 이벤트는 무시합니다.

        Args:
            event: watchdog 파일시스템 이벤트
        """
        if event.is_directory:
            return

        src_path = str(event.src_path)

        # .md 파일만 처리
        if not src_path.endswith(".md"):
            return

        # 이벤트 타입 필터링 (created, modified, deleted, moved)
        if event.event_type in ("created", "modified", "deleted", "moved"):
            logger.debug(f"File {event.event_type}: {src_path}")
            self._schedule_reindex()

    def cancel(self, *, wait_timeout: float = 5.0) -> None:
        """대기 중인 타이머 취소 + 진행 중 콜백 완료 대기.

        타이머 발화 직후(``_timer=None``)부터 콜백 실행 중인 구간에서는
        타이머 cancel 만으로는 콜백을 막을 수 없다. 그래서:

        1. ``_stopping`` 을 set 해 아직 발화 안 한 타이머가 콜백을 실행하지
           않도록 한다.
        2. 대기 중 타이머가 있으면 cancel.
        3. 이미 콜백이 실행 중이면 ``wait_timeout`` 까지 완료를 기다린다
           (graceful shutdown 이 백그라운드 reindex 와 겹치지 않게).

        Args:
            wait_timeout: 진행 중 콜백 완료를 기다릴 최대 초.
        """
        with self._lock:
            self._stopping.set()
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

        # 락 밖에서 대기(콜백이 _execute_reindex 안에서 _idle.set 하므로
        # 락을 잡은 채 기다리면 데드락).
        self._idle.wait(timeout=wait_timeout)


class WikiWatcher:
    """wiki/pages 디렉토리를 감시하는 백그라운드 워처.

    daemon 스레드로 실행되어 메인 프로세스 종료 시 자동 정리됩니다.

    Attributes:
        pages_path: 감시할 pages 디렉토리 경로
        debounce_seconds: 디바운스 딜레이 (초)
        reindex_callback: reindex 실행 함수
    """

    def __init__(
        self,
        pages_path: Path,
        reindex_callback: Callable[[], None],
        debounce_seconds: float = 2.0,
    ):
        """WikiWatcher 초기화.

        Args:
            pages_path: wiki/pages 디렉토리 경로
            reindex_callback: 파일 변경 시 호출할 reindex 함수
            debounce_seconds: 디바운스 딜레이 (초)
        """
        self.pages_path = pages_path
        self.reindex_callback = reindex_callback
        self.debounce_seconds = debounce_seconds
        self._observer: Observer | None = None
        self._handler: DebouncedReindexHandler | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        """워처 실행 여부."""
        return self._running and self._observer is not None

    def start(self) -> bool:
        """파일 감시 시작.

        Returns:
            True: 시작 성공
            False: 이미 실행 중이거나 pages 경로가 없음
        """
        if self._running:
            logger.warning("WikiWatcher already running")
            return False

        if not self.pages_path.exists():
            logger.warning(f"Pages path does not exist: {self.pages_path}")
            return False

        self._handler = DebouncedReindexHandler(
            reindex_callback=self.reindex_callback,
            debounce_seconds=self.debounce_seconds,
        )

        self._observer = Observer()
        self._observer.daemon = True
        self._observer.schedule(
            self._handler,
            str(self.pages_path),
            recursive=True,
        )

        self._observer.start()
        self._running = True

        logger.info(f"WikiWatcher started: {self.pages_path}")
        return True

    def stop(self) -> None:
        """파일 감시 중지."""
        if not self._running:
            return

        if self._handler is not None:
            self._handler.cancel()
            self._handler = None

        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None

        self._running = False
        logger.info("WikiWatcher stopped")

    def get_status(self) -> dict:
        """워처 상태 반환.

        Returns:
            {
                "enabled": bool,
                "running": bool,
                "watching_path": str,
                "debounce_seconds": float
            }
        """
        return {
            "enabled": True,
            "running": self.is_running,
            "watching_path": str(self.pages_path),
            "debounce_seconds": self.debounce_seconds,
        }
