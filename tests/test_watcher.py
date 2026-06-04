"""WikiWatcher 테스트

파일 감시 및 디바운싱 기능을 테스트합니다.
"""

import tempfile
import threading
import time
from pathlib import Path


from wiki_search_mcp.infrastructure.watcher.watcher import DebouncedReindexHandler, WikiWatcher


class TestDebouncedReindexHandler:
    """DebouncedReindexHandler 테스트."""

    def test_single_event_triggers_callback(self):
        """단일 이벤트가 콜백을 트리거."""
        call_count = 0
        lock = threading.Lock()

        def callback():
            nonlocal call_count
            with lock:
                call_count += 1

        handler = DebouncedReindexHandler(
            reindex_callback=callback,
            debounce_seconds=0.1,
        )

        # 이벤트 시뮬레이션
        class MockEvent:
            is_directory = False
            src_path = "/tmp/test.md"
            event_type = "modified"

        handler.on_any_event(MockEvent())

        # 디바운스 후 콜백 호출 대기
        time.sleep(0.3)

        with lock:
            assert call_count == 1

        handler.cancel()

    def test_rapid_events_debounced(self):
        """연속 이벤트는 디바운싱되어 1회만 호출."""
        call_count = 0
        lock = threading.Lock()

        def callback():
            nonlocal call_count
            with lock:
                call_count += 1

        handler = DebouncedReindexHandler(
            reindex_callback=callback,
            debounce_seconds=0.2,
        )

        class MockEvent:
            is_directory = False
            src_path = "/tmp/test.md"
            event_type = "modified"

        # 0.05초 간격으로 5번 이벤트 발생
        for _ in range(5):
            handler.on_any_event(MockEvent())
            time.sleep(0.05)

        # 마지막 이벤트 후 디바운스 대기
        time.sleep(0.4)

        with lock:
            assert call_count == 1

        handler.cancel()

    def test_ignore_non_md_files(self):
        """비-md 파일은 무시."""
        call_count = 0

        def callback():
            nonlocal call_count
            call_count += 1

        handler = DebouncedReindexHandler(
            reindex_callback=callback,
            debounce_seconds=0.1,
        )

        class MockEvent:
            is_directory = False
            src_path = "/tmp/test.txt"
            event_type = "modified"

        handler.on_any_event(MockEvent())
        time.sleep(0.2)

        assert call_count == 0

        handler.cancel()

    def test_ignore_directory_events(self):
        """디렉토리 이벤트는 무시."""
        call_count = 0

        def callback():
            nonlocal call_count
            call_count += 1

        handler = DebouncedReindexHandler(
            reindex_callback=callback,
            debounce_seconds=0.1,
        )

        class MockEvent:
            is_directory = True
            src_path = "/tmp/subdir"
            event_type = "created"

        handler.on_any_event(MockEvent())
        time.sleep(0.2)

        assert call_count == 0

        handler.cancel()

    def test_cancel_pending_timer(self):
        """cancel()이 대기 중인 타이머를 취소."""
        call_count = 0

        def callback():
            nonlocal call_count
            call_count += 1

        handler = DebouncedReindexHandler(
            reindex_callback=callback,
            debounce_seconds=0.5,
        )

        class MockEvent:
            is_directory = False
            src_path = "/tmp/test.md"
            event_type = "modified"

        handler.on_any_event(MockEvent())
        time.sleep(0.1)

        # 타이머 실행 전에 취소
        handler.cancel()
        time.sleep(0.6)

        assert call_count == 0

    def test_cancel_waits_for_running_callback(self):
        """콜백 실행 중 cancel()은 완료를 기다린다(graceful shutdown).

        과거: 타이머 발화 후 _timer=None 이 되면 cancel 이 무효라 콜백이
        백그라운드에서 계속 실행됐다. 이제 cancel 이 진행 중 콜백 완료를
        대기해야 한다.
        """
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def slow_callback():
            started.set()
            release.wait(timeout=2.0)
            finished.set()

        handler = DebouncedReindexHandler(
            reindex_callback=slow_callback,
            debounce_seconds=0.1,
        )

        class MockEvent:
            is_directory = False
            src_path = "/tmp/test.md"
            event_type = "modified"

        handler.on_any_event(MockEvent())
        assert started.wait(timeout=2.0), "콜백이 시작되지 않음"

        # 콜백 실행 중 cancel 호출 → 별도 스레드에서 (블로킹되므로)
        cancel_returned = threading.Event()

        def do_cancel():
            handler.cancel(wait_timeout=2.0)
            cancel_returned.set()

        t = threading.Thread(target=do_cancel)
        t.start()

        # 콜백이 아직 안 끝났으므로 cancel 은 리턴하지 않아야 함
        time.sleep(0.2)
        assert not cancel_returned.is_set(), "cancel 이 콜백 완료를 기다리지 않음"

        # 콜백 완료시키기
        release.set()
        assert cancel_returned.wait(timeout=2.0), "cancel 이 끝내 리턴 안 함"
        assert finished.is_set()
        t.join(timeout=2.0)

    def test_no_callback_after_stopping(self):
        """cancel(중지요청) 후 발화하는 타이머는 콜백을 실행하지 않는다."""
        call_count = 0

        def callback():
            nonlocal call_count
            call_count += 1

        handler = DebouncedReindexHandler(
            reindex_callback=callback,
            debounce_seconds=0.3,
        )

        class MockEvent:
            is_directory = False
            src_path = "/tmp/test.md"
            event_type = "modified"

        handler.on_any_event(MockEvent())
        time.sleep(0.05)
        handler.cancel()  # _stopping set

        # 중지 후 새 이벤트가 와도 예약/실행되지 않아야 함
        handler.on_any_event(MockEvent())
        time.sleep(0.5)
        assert call_count == 0


class TestWikiWatcher:
    """WikiWatcher 테스트."""

    def test_start_and_stop(self):
        """워처 시작/종료."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pages_path = Path(tmpdir) / "pages"
            pages_path.mkdir()

            watcher = WikiWatcher(
                pages_path=pages_path,
                reindex_callback=lambda: None,
                debounce_seconds=0.1,
            )

            assert not watcher.is_running

            result = watcher.start()
            assert result is True
            assert watcher.is_running

            watcher.stop()
            assert not watcher.is_running

    def test_start_nonexistent_path(self):
        """존재하지 않는 경로에서 시작 실패."""
        watcher = WikiWatcher(
            pages_path=Path("/nonexistent/path"),
            reindex_callback=lambda: None,
        )

        result = watcher.start()
        assert result is False
        assert not watcher.is_running

    def test_double_start(self):
        """이미 실행 중인 워처 재시작 시도."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pages_path = Path(tmpdir) / "pages"
            pages_path.mkdir()

            watcher = WikiWatcher(
                pages_path=pages_path,
                reindex_callback=lambda: None,
            )

            watcher.start()
            result = watcher.start()  # 두 번째 시작 시도

            assert result is False
            assert watcher.is_running

            watcher.stop()

    def test_get_status(self):
        """상태 조회."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pages_path = Path(tmpdir) / "pages"
            pages_path.mkdir()

            watcher = WikiWatcher(
                pages_path=pages_path,
                reindex_callback=lambda: None,
                debounce_seconds=3.0,
            )

            status = watcher.get_status()
            assert status["enabled"] is True
            assert status["running"] is False
            assert status["debounce_seconds"] == 3.0

            watcher.start()
            status = watcher.get_status()
            assert status["running"] is True

            watcher.stop()

    def test_file_change_triggers_callback(self):
        """파일 변경 시 콜백 호출."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pages_path = Path(tmpdir) / "pages"
            pages_path.mkdir()

            call_count = 0
            lock = threading.Lock()

            def callback():
                nonlocal call_count
                with lock:
                    call_count += 1

            watcher = WikiWatcher(
                pages_path=pages_path,
                reindex_callback=callback,
                debounce_seconds=0.2,
            )
            watcher.start()

            # watchdog이 감시를 시작할 시간 확보
            time.sleep(0.1)

            # 파일 생성
            test_file = pages_path / "test.md"
            test_file.write_text("# Test")

            # 디바운스 + 여유 시간
            time.sleep(0.5)

            with lock:
                assert call_count >= 1

            watcher.stop()

    def test_subdirectory_file_change(self):
        """하위 디렉토리의 파일 변경 감지."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pages_path = Path(tmpdir) / "pages"
            subdir = pages_path / "infra"
            subdir.mkdir(parents=True)

            call_count = 0
            lock = threading.Lock()

            def callback():
                nonlocal call_count
                with lock:
                    call_count += 1

            watcher = WikiWatcher(
                pages_path=pages_path,
                reindex_callback=callback,
                debounce_seconds=0.2,
            )
            watcher.start()

            time.sleep(0.1)

            # 하위 디렉토리에 파일 생성
            test_file = subdir / "nginx.md"
            test_file.write_text("# Nginx Config")

            time.sleep(0.5)

            with lock:
                assert call_count >= 1

            watcher.stop()

    def test_multiple_rapid_changes(self):
        """연속적인 파일 변경 시 디바운싱."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pages_path = Path(tmpdir) / "pages"
            pages_path.mkdir()

            call_count = 0
            lock = threading.Lock()

            def callback():
                nonlocal call_count
                with lock:
                    call_count += 1

            watcher = WikiWatcher(
                pages_path=pages_path,
                reindex_callback=callback,
                debounce_seconds=0.3,
            )
            watcher.start()

            time.sleep(0.1)

            test_file = pages_path / "test.md"

            # 0.05초 간격으로 5번 수정
            for i in range(5):
                test_file.write_text(f"# Version {i}")
                time.sleep(0.05)

            # 마지막 수정 후 디바운스 + 여유 시간
            time.sleep(0.6)

            with lock:
                # 디바운싱으로 1회만 호출되어야 함
                assert call_count == 1

            watcher.stop()
