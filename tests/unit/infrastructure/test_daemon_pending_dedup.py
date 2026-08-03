"""DaemonRunner pending 중복 기록 방지 + rate_limited cooldown 테스트 (0.7.0 P0).

요청서 참고사항 재현: rate_limited 항목이 600초 cooldown 마다 재시도되며
pending.jsonl 에 1650건 중복 누적되던 병리.

- ``_record_pending``: 같은 path+reason 연속 기록은 1회만.
- worker 의 RateLimitError 처리: cooldown 이 ``wait_seconds`` 이상으로 잡혀
  한도 회복 전 헛 재시도가 없다.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki_search_mcp.core.exceptions import RateLimitError


@pytest.fixture(autouse=True)
def _xdg_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _build_runner(wiki: Path):
    from wiki_search_mcp.infrastructure.daemon.options import DaemonOptions
    from wiki_search_mcp.infrastructure.daemon.runner import DaemonRunner

    opts = DaemonOptions(wiki_path=wiki, provider_factory=lambda: MagicMock())
    with patch(
        "wiki_search_mcp.infrastructure.daemon.runner.WikiIndexer"
    ), patch(
        "wiki_search_mcp.infrastructure.daemon.runner.ServiceContainer"
    ) as fake_container_cls, patch(
        "wiki_search_mcp.infrastructure.daemon.runner.ClassifierService"
    ):
        fake_container = MagicMock()
        fake_container.pages_path = wiki / "pages"
        fake_container_cls.return_value = fake_container
        runner = DaemonRunner(opts)
    runner._pending = MagicMock()
    runner._status = MagicMock()
    return runner


def test_record_pending_dedups_same_reason(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    (wiki / "pages").mkdir(parents=True)
    runner = _build_runner(wiki)

    assert runner._record_pending("a.md", "rate_limited", wait_seconds=100) is True
    assert runner._record_pending("a.md", "rate_limited", wait_seconds=200) is False
    assert runner._pending.append.call_count == 1

    # reason 이 바뀌면 다시 기록
    assert runner._record_pending("a.md", "low_confidence") is True
    assert runner._pending.append.call_count == 2


async def _drain_one_worker(runner, rel: str) -> None:
    """worker 를 짧게 돌려 큐 항목 1개를 처리시키고 종료."""
    runner._queue.put_nowait(rel)
    task = asyncio.create_task(runner._worker(0))
    await runner._queue.join()
    runner._stop.set()
    await asyncio.wait_for(task, timeout=5.0)


def test_rate_limited_cooldown_uses_wait_seconds(tmp_path: Path) -> None:
    """일일 한도 소진(wait 3만초)이면 cooldown 도 그만큼 길어야 한다."""
    wiki = tmp_path / "wiki"
    (wiki / "pages").mkdir(parents=True)
    runner = _build_runner(wiki)
    runner._classify_and_apply = AsyncMock(side_effect=RateLimitError.of(30000.0))

    asyncio.run(_drain_one_worker(runner, "inbox/a.md"))

    expiry = runner._cooldown["inbox/a.md"]
    remaining = expiry - time.monotonic()
    assert remaining > 29000  # wait_seconds 기반 (기본 600초 아님)
    runner._pending.append.assert_called_once()


def test_rate_limited_short_wait_keeps_default_cooldown(tmp_path: Path) -> None:
    """짧은 wait 면 기본 cooldown(600초)이 하한."""
    wiki = tmp_path / "wiki"
    (wiki / "pages").mkdir(parents=True)
    runner = _build_runner(wiki)
    runner._classify_and_apply = AsyncMock(side_effect=RateLimitError.of(45.0))

    asyncio.run(_drain_one_worker(runner, "inbox/b.md"))

    remaining = runner._cooldown["inbox/b.md"] - time.monotonic()
    assert 500 < remaining <= 600
