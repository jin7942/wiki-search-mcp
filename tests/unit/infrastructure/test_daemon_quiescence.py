"""DaemonRunner quiescence/periodic-rescan v0.4.0 회귀 테스트.

장애 보고서 #1 의 핵심 가드:
- ``quiescence_seconds`` 미만으로 막 수정된 파일은 LLM 호출하지 않고 cooldown.
- ``rescan_interval_seconds`` > 0 이면 외부 FS 이벤트 없이도 주기 rescan 이 발동.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _xdg_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _build_runner(wiki: Path, *, quiescence_seconds: float, rescan_interval_seconds: float = 0.0):
    from wiki_search_mcp.infrastructure.daemon.options import DaemonOptions
    from wiki_search_mcp.infrastructure.daemon.runner import DaemonRunner

    fake_provider = MagicMock()
    opts = DaemonOptions(
        wiki_path=wiki,
        queue_max=100,
        provider_factory=lambda: fake_provider,
        quiescence_seconds=quiescence_seconds,
        rescan_interval_seconds=rescan_interval_seconds,
        min_body_chars=0,
    )
    with patch(
        "wiki_search_mcp.infrastructure.daemon.runner.WikiIndexer"
    ) as fake_idx_cls, patch(
        "wiki_search_mcp.infrastructure.daemon.runner.ServiceContainer"
    ) as fake_container_cls, patch(
        "wiki_search_mcp.infrastructure.daemon.runner.ClassifierService"
    ) as fake_classifier_cls:
        fake_container = MagicMock()
        fake_container.pages_path = wiki / "pages"
        fake_container_cls.return_value = fake_container
        fake_idx = MagicMock()
        fake_idx_cls.return_value = fake_idx
        fake_classifier = MagicMock()
        fake_classifier.classify = AsyncMock()
        fake_classifier_cls.return_value = fake_classifier
        runner = DaemonRunner(opts)
        runner._classifier = fake_classifier
        runner._indexer = fake_idx
        return runner, fake_classifier


@pytest.mark.asyncio
async def test_recently_modified_file_skipped_under_quiescence() -> None:
    """mtime 이 너무 최근이면 LLM 호출하지 않고 cooldown 에 등록."""
    with tempfile.TemporaryDirectory() as td:
        wiki = Path(td) / "wiki"
        (wiki / "pages" / "inbox").mkdir(parents=True)
        f = wiki / "pages" / "inbox" / "memo.md"
        f.write_text("# x", encoding="utf-8")
        # 매우 최근에 수정됨 (now). quiescence 가 충분히 길면 진입 차단되어야 함.

        runner, fake_classifier = _build_runner(wiki, quiescence_seconds=3600.0)
        runner._reindex_lock = asyncio.Lock()

        await runner._classify_and_apply("inbox/memo.md")

        fake_classifier.classify.assert_not_called()
        assert "inbox/memo.md" in runner._cooldown


@pytest.mark.asyncio
async def test_old_file_passes_quiescence() -> None:
    """mtime 이 quiescence 보다 오래 전이면 통과해 LLM 호출이 발생한다."""
    from wiki_search_mcp.core.models import ClassificationDecision

    with tempfile.TemporaryDirectory() as td:
        wiki = Path(td) / "wiki"
        (wiki / "pages" / "inbox").mkdir(parents=True)
        f = wiki / "pages" / "inbox" / "memo.md"
        f.write_text("---\n---\n# x", encoding="utf-8")
        # mtime 을 인위적으로 과거로 — quiescence 통과시킴
        past = time.time() - 7200
        os.utime(f, (past, past))

        runner, fake_classifier = _build_runner(wiki, quiescence_seconds=60.0)
        runner._reindex_lock = asyncio.Lock()
        fake_classifier.classify.return_value = ClassificationDecision(
            path="inbox/memo.md",
            category="infra",
            tags=(),
            confidence=0.2,  # threshold 미만 — pending 처리만 검증
            reasoning="r",
            provider="p",
            raw_response="",
        )

        await runner._classify_and_apply("inbox/memo.md")
        fake_classifier.classify.assert_called_once()


@pytest.mark.asyncio
async def test_periodic_rescan_fires_without_external_events() -> None:
    """``rescan_interval_seconds`` > 0 이면 외부 FS 이벤트 없이도 _rescan 이 깨어난다."""
    with tempfile.TemporaryDirectory() as td:
        wiki = Path(td) / "wiki"
        (wiki / "pages").mkdir(parents=True)
        runner, _ = _build_runner(
            wiki, quiescence_seconds=0.0, rescan_interval_seconds=0.1
        )
        runner._reindex_lock = asyncio.Lock()

        called: list[float] = []

        async def fake_rescan() -> None:
            called.append(time.monotonic())

        runner._rescan = fake_rescan  # type: ignore[assignment]

        task = asyncio.create_task(runner._periodic_rescan())
        try:
            await asyncio.sleep(0.35)
        finally:
            runner._stop.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # 0.1s 간격으로 0.35s 동안 — 최소 2번은 발화해야 한다.
        assert len(called) >= 2, f"periodic rescan 발화 부족: {len(called)}회"
