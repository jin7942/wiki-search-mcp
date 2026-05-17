"""DaemonRunner silent error_count 누락 회귀 테스트.

v0.2.6 이전 결함: ``find_pending() failed`` 와 ``queue full; dropping enqueue``
경로가 logger만 호출하고 ``error_count`` 카운터를 증가시키지 않아 운영자가
daemon status로 silent failure를 감지하지 못했다. v0.2.6은 두 경로 모두에서
``error_count`` 를 증가시킨다.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _xdg_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _build_runner(wiki: Path, *, queue_max: int = 100):
    from wiki_search_mcp.infrastructure.daemon.options import DaemonOptions
    from wiki_search_mcp.infrastructure.daemon.runner import DaemonRunner

    fake_provider = MagicMock()
    opts = DaemonOptions(
        wiki_path=wiki,
        queue_max=queue_max,
        provider_factory=lambda: fake_provider,
    )
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
        return runner, fake_container


@pytest.mark.asyncio
async def test_find_pending_failure_increments_error_count() -> None:
    """``find_pending`` 예외 시 ``error_count`` 카운터가 1 증가해야 한다."""
    with tempfile.TemporaryDirectory() as td:
        wiki = Path(td) / "wiki"
        (wiki / "pages").mkdir(parents=True)
        runner, fake_container = _build_runner(wiki)
        # status 호출 검증을 위해 mock 교체
        runner._status = MagicMock()
        fake_container.classification_service.find_pending.side_effect = RuntimeError("disk error")

        await runner._rescan()

        increments = [c.args[0] for c in runner._status.increment.call_args_list if c.args]
        assert "error_count" in increments, (
            f"find_pending 예외 시 error_count 증가 안 됨: {increments}"
        )


@pytest.mark.asyncio
async def test_queue_full_increments_error_count() -> None:
    """큐가 가득찬 상태에서 put_nowait 실패 시 ``error_count`` 카운터가 증가해야 한다."""
    from wiki_search_mcp.core.models import PendingItem

    with tempfile.TemporaryDirectory() as td:
        wiki = Path(td) / "wiki"
        (wiki / "pages").mkdir(parents=True)
        # queue_max=1로 만들고 미리 채워서 다음 put_nowait가 무조건 QueueFull
        runner, fake_container = _build_runner(wiki, queue_max=1)
        runner._status = MagicMock()
        # 큐 미리 채움
        runner._queue.put_nowait("already_there.md")
        # find_pending이 신규 path 반환 → put_nowait가 QueueFull
        fake_container.classification_service.find_pending.return_value = [
            PendingItem.of(path="new1.md", reason="not_indexed"),
            PendingItem.of(path="new2.md", reason="not_indexed"),
        ]

        await runner._rescan()

        increments = [c.args[0] for c in runner._status.increment.call_args_list if c.args]
        assert "error_count" in increments, (
            f"queue full 시 error_count 증가 안 됨: {increments}"
        )
