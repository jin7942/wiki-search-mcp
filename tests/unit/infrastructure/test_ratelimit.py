"""SlidingWindowRateLimit 단위 테스트 (fake clock)."""

from __future__ import annotations

import asyncio

import pytest

from wiki_search_mcp.core.exceptions import RateLimitError
from wiki_search_mcp.infrastructure.daemon.ratelimit import SlidingWindowRateLimit


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.asyncio
async def test_minute_window_blocks_then_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeClock()

    async def no_sleep(seconds: float) -> None:
        clock.advance(seconds)

    monkeypatch.setattr("wiki_search_mcp.infrastructure.daemon.ratelimit.asyncio.sleep", no_sleep)

    limit = SlidingWindowRateLimit(per_minute=2, max_wait_s=120.0, clock=clock)
    await limit.acquire()
    await limit.acquire()
    # 다음 호출은 한도 차서 대기 필요
    await limit.acquire()  # fake sleep으로 즉시 진행
    # 첫 호출이 60초 후 만료되었어야 함
    assert clock.now >= 60.0


@pytest.mark.asyncio
async def test_per_day_overflow_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeClock()

    async def no_sleep(seconds: float) -> None:
        clock.advance(seconds)

    monkeypatch.setattr("wiki_search_mcp.infrastructure.daemon.ratelimit.asyncio.sleep", no_sleep)

    # per_minute=100, per_day=2 → 3번째 호출은 day window 한도 초과 + 대기 시간(>max_wait_s) → RateLimitError
    limit = SlidingWindowRateLimit(per_minute=100, per_day=2, max_wait_s=5.0, clock=clock)
    await limit.acquire()
    await limit.acquire()
    with pytest.raises(RateLimitError):
        await limit.acquire()


def test_snapshot_reports_usage() -> None:
    clock = _FakeClock()
    limit = SlidingWindowRateLimit(per_minute=5, per_hour=10, clock=clock)
    # 직접 record 트리거 (snapshot은 동기)
    for w in limit._windows:
        w.record(clock.now)
    snap = limit.snapshot()
    assert snap["per_minute"]["limit"] == 5
    assert snap["per_minute"]["used"] == 1
    assert snap["per_hour"]["used"] == 1
