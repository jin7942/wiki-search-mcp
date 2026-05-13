"""DaemonRunner — 백그라운드 자동 분류 메인 루프.

흐름:
1. ``main()`` 진입 → PidLock 획득 → 로깅 셋업 → asyncio 루프 시작
2. 시작 시 ``ClassificationService.find_pending()``로 큐 채움
3. WikiWatcher가 파일 변경 감지하면 콜백으로 큐에 재투입
4. N개 worker가 큐에서 dequeue → LLM 분류 → confidence 분기:
   - ≥ threshold → FrontmatterWriter.apply() + applied.jsonl 기록 + 증분 reindex
   - <  threshold → pending.jsonl 기록
5. SIGTERM/SIGINT → graceful shutdown
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone
from pathlib import Path

from wiki_search_mcp.adapters.mcp.container import ServiceContainer
from wiki_search_mcp.core.exceptions import (
    ClassifierError,
    DocumentNotFoundError,
    RateLimitError,
)
from wiki_search_mcp.core.logging import setup_logging
from wiki_search_mcp.core.utils import resolve_pages_path
from wiki_search_mcp.infrastructure.daemon.options import DaemonOptions
from wiki_search_mcp.infrastructure.daemon.paths import (
    applied_jsonl,
    log_file,
    pending_jsonl,
    pid_file,
    state_lock_file,
    status_file,
)
from wiki_search_mcp.infrastructure.daemon.pidfile import PidLock
from wiki_search_mcp.infrastructure.daemon.ratelimit import SlidingWindowRateLimit
from wiki_search_mcp.infrastructure.daemon.statefile import StatusFile
from wiki_search_mcp.infrastructure.frontmatter.writer import FrontmatterWriter
from wiki_search_mcp.infrastructure.indexing import WikiIndexer
from wiki_search_mcp.infrastructure.jsonl.log import JsonlLog
from wiki_search_mcp.infrastructure.watcher import WikiWatcher
from wiki_search_mcp.services.classifier_service import ClassifierService
from wiki_search_mcp.services.llm.claude_code_provider import ClaudeCodeProvider

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DaemonRunner:
    """daemon 라이프사이클을 관리하는 단일 진입점."""

    def __init__(self, opts: DaemonOptions):
        self._opts = opts
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = asyncio.Event()
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=opts.queue_max)
        self._inflight: set[str] = set()

        self._container = ServiceContainer(
            str(opts.wiki_path),
            model_name=opts.embedding_model,
            ignore_patterns=opts.ignore_patterns,
        )
        self._indexer = WikiIndexer(
            str(opts.wiki_path),
            model_name=opts.embedding_model,
            ignore_patterns=opts.ignore_patterns,
        )
        self._writer = FrontmatterWriter(self._container.pages_path)

        provider = (
            opts.provider_factory()
            if opts.provider_factory is not None
            else ClaudeCodeProvider(model=opts.llm_model)
        )
        self._provider = provider
        self._classifier = ClassifierService(
            classification_service=self._container.classification_service,
            category_service=self._container.category_service,
            provider=provider,
            pages_path=self._container.pages_path,
        )

        self._rate = SlidingWindowRateLimit(
            opts.rate_per_minute,
            opts.rate_per_hour,
            opts.rate_per_day,
            max_wait_s=opts.rate_max_wait_s,
        )
        self._pending = JsonlLog(pending_jsonl(opts.wiki_path))
        self._applied = JsonlLog(applied_jsonl(opts.wiki_path))
        self._status = StatusFile(status_file(opts.wiki_path))

    # ------------------------------------------------------------------ start
    def start(self) -> None:
        """포그라운드 실행. PidLock 보유 상태로 asyncio 루프 진입."""
        with PidLock(state_lock_file(self._opts.wiki_path), pid_file(self._opts.wiki_path)):
            setup_logging(level=self._opts.log_level, log_file=log_file(self._opts.wiki_path))
            logger.info("daemon starting: wiki=%s", self._opts.wiki_path)
            asyncio.run(self._main())

    # ------------------------------------------------------------------ main
    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()

        # Provider healthcheck — 실패 시 즉시 종료
        try:
            await self._provider.healthcheck()
        except ClassifierError as e:
            self._status.write(
                {
                    "state": "failed",
                    "error": str(e),
                    "error_code": getattr(e.context, "code", None) if e.context else None,
                    "stopped_at": _utc_now(),
                }
            )
            logger.error("provider healthcheck failed: %s", e)
            return

        self._status.write(
            {
                "state": "running",
                "started_at": _utc_now(),
                "wiki_path": str(self._opts.wiki_path),
                "provider": self._provider.name,
                "llm_model": self._opts.llm_model,
                "confidence_threshold": self._opts.confidence_threshold,
                "applied_count": 0,
                "pending_count": 0,
                "error_count": 0,
            }
        )

        # 신호 핸들러
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                self._loop.add_signal_handler(sig, self._stop.set)
            except NotImplementedError:  # Windows
                pass

        # Watcher
        pages_path = resolve_pages_path(self._opts.wiki_path)
        watcher = WikiWatcher(
            pages_path=pages_path,
            reindex_callback=self._on_watch_event,
            debounce_seconds=self._opts.debounce,
        )
        watcher.start()

        # 초기 스캔
        await self._rescan()

        # Worker pool
        workers = [asyncio.create_task(self._worker(i)) for i in range(self._opts.concurrency)]

        try:
            await self._stop.wait()
        finally:
            logger.info("daemon stopping...")
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            watcher.stop()
            self._status.update(state="stopped", stopped_at=_utc_now())
            logger.info("daemon stopped.")

    # ---------------------------------------------------------------- watcher
    def _on_watch_event(self) -> None:
        """WikiWatcher 콜백 (별도 스레드). 안전하게 asyncio에 위임."""
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(asyncio.ensure_future, self._rescan())

    async def _rescan(self) -> None:
        """pending 목록을 다시 가져와 큐에 추가 (중복은 inflight 집합으로 회피)."""
        try:
            self._container.invalidate_all()
        except Exception:
            logger.debug("invalidate_all() failed", exc_info=True)
        # 인덱스 비어있을 수도 있음 — find_pending은 디스크 차집합도 함께 봄
        try:
            items = self._container.classification_service.find_pending(limit=200)
        except Exception:
            logger.exception("find_pending() failed")
            return
        for item in items:
            rel = item.path
            if rel in self._inflight:
                continue
            try:
                self._queue.put_nowait(rel)
            except asyncio.QueueFull:
                logger.warning("queue full; dropping enqueue for %s", rel)
                break

    # ---------------------------------------------------------------- worker
    async def _worker(self, idx: int) -> None:
        while not self._stop.is_set():
            try:
                rel = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if rel in self._inflight:
                self._queue.task_done()
                continue
            self._inflight.add(rel)
            try:
                await self._rate.acquire()
                await self._classify_and_apply(rel)
            except RateLimitError as e:
                self._pending.append(
                    {
                        "path": rel,
                        "reason": "rate_limited",
                        "wait_seconds": getattr(e.context, "details", {}).get("wait_seconds") if e.context else None,
                        "recorded_at": _utc_now(),
                    }
                )
                self._status.increment("error_count")
            except ClassifierError as e:
                self._pending.append(
                    {
                        "path": rel,
                        "reason": "classifier_error",
                        "code": getattr(e.context, "code", None) if e.context else None,
                        "message": str(e)[:200],
                        "recorded_at": _utc_now(),
                    }
                )
                self._status.increment("error_count")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("worker[%d] unexpected error on %s", idx, rel)
                self._status.increment("error_count")
            finally:
                self._inflight.discard(rel)
                self._queue.task_done()

    # ------------------------------------------------------------------ apply
    async def _classify_and_apply(self, rel: str) -> None:
        full = self._container.pages_path / rel
        try:
            mtime_before = full.stat().st_mtime
        except FileNotFoundError:
            return
        try:
            decision = await self._classifier.classify(rel)
        except DocumentNotFoundError:
            return

        # 분류 도중 사용자가 파일을 수정한 경우 → 적용 안 함
        try:
            mtime_now = full.stat().st_mtime
        except FileNotFoundError:
            return
        if mtime_now != mtime_before:
            self._pending.append(
                {
                    "path": rel,
                    "reason": "file_changed_during_classify",
                    "recorded_at": _utc_now(),
                }
            )
            return

        if decision.confidence < self._opts.confidence_threshold:
            self._pending.append(
                {
                    "path": rel,
                    "reason": "low_confidence",
                    "decision": decision.to_dict(),
                    "recorded_at": _utc_now(),
                }
            )
            self._status.increment("pending_count", last_classified_at=_utc_now())
            return

        # confidence 충족 → 자동 적용
        try:
            record = self._writer.apply(rel, decision, move_into_category=self._opts.auto_move)
        except OSError as e:
            logger.error("frontmatter write failed for %s: %s", rel, e)
            self._pending.append(
                {
                    "path": rel,
                    "reason": "write_failed",
                    "message": str(e),
                    "decision": decision.to_dict(),
                    "recorded_at": _utc_now(),
                }
            )
            self._status.increment("error_count")
            return

        self._applied.append(record.to_dict())
        try:
            self._indexer.reindex(full=False)
            self._container.invalidate_all()
        except Exception:
            logger.exception("post-apply reindex failed (continuing)")
        self._status.increment("applied_count", last_classified_at=_utc_now())


__all__ = ["DaemonRunner"]
