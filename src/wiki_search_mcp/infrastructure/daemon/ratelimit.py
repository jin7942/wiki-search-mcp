"""Sliding window rate limiter (분/시/일 동시 적용).

Claude Pro/Max 사용자의 인터랙티브 한도를 daemon이 과하게 갉아먹지 않도록 하는 안전장치.
분당 5회 / 시간당 100회 / 일일 500회 같은 보수적 기본값을 사용한다.

설계:
- 각 윈도우(60/3600/86400초)마다 ``deque[float]``로 호출 시점을 기록.
- ``acquire()`` 호출 시 가장 보수적인 윈도우 기준 다음 호출 가능까지 대기 시간 계산.
- 대기 시간이 ``max_wait_s`` 이내면 ``asyncio.sleep``으로 대기, 초과면 ``RateLimitError``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable

from wiki_search_mcp.core.exceptions import RateLimitError

logger = logging.getLogger(__name__)


class _Window:
    """단일 sliding window."""

    __slots__ = ("limit", "span", "_ticks")

    def __init__(self, limit: int, span_seconds: float):
        self.limit = limit
        self.span = span_seconds
        self._ticks: deque[float] = deque()

    def _purge(self, now: float) -> None:
        cutoff = now - self.span
        while self._ticks and self._ticks[0] <= cutoff:
            self._ticks.popleft()

    def next_available_in(self, now: float) -> float:
        """0이면 즉시 가능, 양수면 그만큼 대기 필요."""
        self._purge(now)
        if len(self._ticks) < self.limit:
            return 0.0
        oldest = self._ticks[0]
        return max(0.0, (oldest + self.span) - now)

    def record(self, now: float) -> None:
        self._ticks.append(now)


class SlidingWindowRateLimit:
    """분/시/일 윈도우 동시 적용.

    Args:
        per_minute: 분당 한도 (>0)
        per_hour: 시간당 한도 (>0이면 활성)
        per_day: 일일 한도 (>0이면 활성)
        max_wait_s: 대기 허용 최대 시간. 초과면 ``RateLimitError`` 발생
        clock: 단조 시계 함수 (테스트용 fake clock 주입)
    """

    def __init__(
        self,
        per_minute: int,
        per_hour: int | None = None,
        per_day: int | None = None,
        *,
        max_wait_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if per_minute <= 0:
            raise ValueError("per_minute must be > 0")
        self._windows: list[_Window] = [_Window(per_minute, 60.0)]
        if per_hour and per_hour > 0:
            self._windows.append(_Window(per_hour, 3600.0))
        if per_day and per_day > 0:
            self._windows.append(_Window(per_day, 86400.0))
        self._max_wait_s = max_wait_s
        self._clock = clock
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """다음 호출 슬롯을 점유. 대기 시간이 ``max_wait_s`` 초과 시 ``RateLimitError``."""
        async with self._lock:
            now = self._clock()
            wait = max((w.next_available_in(now) for w in self._windows), default=0.0)
            if wait > self._max_wait_s:
                raise RateLimitError.of(wait)
            if wait > 0:
                logger.debug("rate-limit sleep: %.2fs", wait)
                await asyncio.sleep(wait)
                now = self._clock()
            for w in self._windows:
                w.record(now)

    def snapshot(self) -> dict[str, dict[str, int]]:
        """현재 윈도우 사용량 (디버그/MCP 노출용)."""
        now = self._clock()
        out: dict[str, dict[str, int]] = {}
        labels = {60.0: "per_minute", 3600.0: "per_hour", 86400.0: "per_day"}
        for w in self._windows:
            w._purge(now)
            out[labels[w.span]] = {"limit": w.limit, "used": len(w._ticks)}
        return out
