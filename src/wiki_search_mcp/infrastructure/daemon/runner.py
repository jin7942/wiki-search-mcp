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
import time
from datetime import datetime, timezone
from pathlib import Path

from wiki_search_mcp.adapters.mcp.container import ServiceContainer
from wiki_search_mcp.core.exceptions import (
    ClassifierError,
    DocumentNotFoundError,
    RateLimitError,
)
from wiki_search_mcp.core.logging import setup_logging
from wiki_search_mcp.core.metrics import configure_metrics
from wiki_search_mcp.core.utils import resolve_pages_path
from wiki_search_mcp.infrastructure.daemon.options import DaemonOptions
from wiki_search_mcp.infrastructure.daemon.paths import (
    applied_jsonl,
    log_file,
    metrics_jsonl,
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
from wiki_search_mcp.services.classifier_service import (
    ClassifierService,
    ClassifierSkipped,
)
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
        # path → cooldown 만료 monotonic time. rate_limited / classifier_error 후
        # 같은 path가 재스캔 때마다 무한 재투입되어 pending.jsonl이 폭증하는 것을 방지.
        self._cooldown: dict[str, float] = {}
        self._cooldown_seconds: float = 600.0
        # LanceDB의 ``create_table(mode="overwrite")``는 atomic이지만, 같은 시점에
        # 두 worker가 동시에 호출하면 매니페스트 버전 경쟁으로 한쪽이 실패할 수 있다.
        # post-apply reindex만 직렬화해 worker 동시성은 유지하면서 인덱스 갱신만 순차.
        self._reindex_lock: asyncio.Lock | None = None

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
        self._writer = FrontmatterWriter(
            self._container.pages_path,
            rewrite_inbound_links=opts.rewrite_inbound_links,
        )

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
            min_body_chars=opts.min_body_chars,
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
            configure_metrics(metrics_jsonl(self._opts.wiki_path))
            logger.info("daemon starting: wiki=%s", self._opts.wiki_path)
            asyncio.run(self._main())

    # ------------------------------------------------------------------ main
    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        # asyncio.Lock은 running loop가 있어야 안전하게 만들 수 있어 여기서 늦게 생성.
        self._reindex_lock = asyncio.Lock()

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
                "reindex_error_count": 0,
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

        # 주기 self-rescan — 외부 FS 이벤트가 안 와도 cooldown 만료 항목이 다시
        # 큐잉되도록. ``rescan_interval_seconds <= 0`` 이면 비활성.
        periodic: asyncio.Task | None = None
        if self._opts.rescan_interval_seconds > 0:
            periodic = asyncio.create_task(self._periodic_rescan())

        try:
            await self._stop.wait()
        finally:
            logger.info("daemon stopping...")
            if periodic is not None:
                periodic.cancel()
            for w in workers:
                w.cancel()
            tasks = [*workers]
            if periodic is not None:
                tasks.append(periodic)
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # gather(return_exceptions=True) 는 예외를 반환값으로 돌리므로
            # 직접 검사하지 않으면 worker/periodic 의 비정상 종료가 silent 가 된다.
            # cancel() 로 인한 CancelledError 는 정상 종료 신호이므로 제외.
            for i, res in enumerate(results):
                if isinstance(res, BaseException) and not isinstance(
                    res, asyncio.CancelledError
                ):
                    logger.error("daemon task[%d] exited abnormally: %r", i, res)
            watcher.stop()
            self._status.update(state="stopped", stopped_at=_utc_now())
            logger.info("daemon stopped.")

    async def _periodic_rescan(self) -> None:
        """``rescan_interval_seconds`` 마다 ``_rescan()`` 호출.

        외부 FS 이벤트가 더 이상 안 들어와도 cooldown 만료 항목이 다시 큐에 들어가도록
        주기적으로 깨운다. ``_stop`` 신호가 오면 즉시 종료.
        """
        interval = self._opts.rescan_interval_seconds
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                pass
            try:
                await self._rescan()
            except Exception as e:
                # 침묵 금지: 로깅 + status 에 마지막 오류를 노출해 사용자가
                # `daemon status` 로 rescan 이 막혔음을 알 수 있게 한다.
                logger.exception("periodic rescan failed")
                self._status.update(
                    last_rescan_error=str(e),
                    last_rescan_error_at=_utc_now(),
                )

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
        except Exception as e:
            logger.exception("find_pending() failed")
            # silent failure 방지 — error_count + 마지막 오류 메시지를 status 에 노출.
            self._status.increment(
                "error_count",
                last_rescan_error=str(e),
                last_rescan_error_at=_utc_now(),
            )
            return
        now = time.monotonic()
        # 만료된 cooldown 정리
        expired = [p for p, t in self._cooldown.items() if t <= now]
        for p in expired:
            self._cooldown.pop(p, None)
        for item in items:
            rel = item.path
            if rel in self._inflight:
                continue
            if rel in self._cooldown:
                continue
            try:
                self._queue.put_nowait(rel)
            except asyncio.QueueFull:
                logger.warning("queue full; dropping enqueue for %s", rel)
                # 큐 적체로 path가 누락되는 것도 silent failure — 외부에 노출.
                self._status.increment("error_count")
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
                self._cooldown[rel] = time.monotonic() + self._cooldown_seconds
                self._status.increment("pending_count", last_classified_at=_utc_now())
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
                self._cooldown[rel] = time.monotonic() + self._cooldown_seconds
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

        # Quiescence guard — 사용자가 막 손댄 파일에 분류가 끼어드는 것을 차단.
        # ``now - mtime`` 이 임계 미만이면 짧은 cooldown 후 다음 rescan 에서 재시도.
        # 5분 정도로 cooldown 을 잡으면 quiescence 60s 환경에서도 자연스럽게 재시도된다.
        quiescence = self._opts.quiescence_seconds
        if quiescence > 0:
            age = time.time() - mtime_before
            if age < quiescence:
                self._cooldown[rel] = time.monotonic() + max(quiescence - age, 5.0)
                logger.debug(
                    "skip %s: age=%.1fs < quiescence=%.1fs", rel, age, quiescence
                )
                return

        try:
            decision = await self._classifier.classify(rel)
        except DocumentNotFoundError:
            return
        except ClassifierSkipped as e:
            # 분류 가드(본문 너무 짧음 / 사용자 잠금)에 걸린 경우.
            # 오류가 아니므로 error_count 는 그대로 두고, pending.jsonl 에 사유만 남긴다.
            self._pending.append(
                {
                    "path": rel,
                    "reason": e.reason,
                    "recorded_at": _utc_now(),
                }
            )
            # 같은 파일이 다음 rescan 마다 즉시 재진입하지 않도록 짧은 cooldown.
            self._cooldown[rel] = time.monotonic() + max(quiescence, 30.0)
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
            # 다중 worker 동시 reindex로 인한 LanceDB 매니페스트 race 방지.
            # 분류 INFO 적용 자체는 worker별로 병렬이지만, 인덱스 갱신은 순차.
            if self._reindex_lock is not None:
                async with self._reindex_lock:
                    await asyncio.to_thread(self._indexer.reindex, full=False)
            else:
                await asyncio.to_thread(self._indexer.reindex, full=False)
            self._container.invalidate_all()
        except Exception as e:
            logger.exception("post-apply reindex failed (continuing)")
            # 분류(frontmatter 적용)는 이미 성공했으므로 error_count 는 그대로 두되,
            # 운영자가 인덱스 갱신 누락을 감지할 수 있도록 별도 카운터 + 마지막
            # 오류 + pending.jsonl(reason=reindex_failed) 로 가시화한다. 인덱스에
            # 반영 안 된 파일은 다음 rescan 의 디스크 차집합 스캔에서 다시 잡힌다.
            self._status.increment(
                "reindex_error_count",
                last_reindex_error=str(e),
                last_reindex_error_at=_utc_now(),
            )
            self._pending.append(
                {
                    "path": record.path_after,
                    "reason": "reindex_failed",
                    "message": str(e),
                    "recorded_at": _utc_now(),
                }
            )
        self._status.increment("applied_count", last_classified_at=_utc_now())


__all__ = ["DaemonRunner"]
