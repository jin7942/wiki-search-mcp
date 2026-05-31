"""DaemonRunner post-apply reindex 동시성/카운터 회귀 테스트.

장애 보고서 (v0.2.3 → v0.2.4):
- 두 worker가 동시에 ``reindex(full=False)``를 호출하면 LanceDB의
  ``drop_table`` → ``create_table`` 사이 race로 한쪽이
  ``ValueError: Table 'wiki' already exists``로 실패.
- 결과: 첫 부트스트랩 이후 인덱스가 영영 갱신되지 않음.

v0.2.4 패치:
- ``WikiIndexer.reindex``는 ``create_table(mode="overwrite")`` 단일 호출로 atomic.
- 그래도 lancedb 매니페스트 버전 경쟁이 있을 수 있으므로
  ``DaemonRunner._reindex_lock``으로 worker간 직렬화.
- 실패는 ``reindex_error_count`` 별도 카운터에 노출.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _xdg_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _build_runner(wiki: Path, decision_cls):
    from wiki_search_mcp.infrastructure.daemon.options import DaemonOptions
    from wiki_search_mcp.infrastructure.daemon.runner import DaemonRunner

    fake_provider = MagicMock()
    opts = DaemonOptions(
        wiki_path=wiki,
        queue_max=100,
        provider_factory=lambda: fake_provider,
        # 본 테스트는 reindex 동시성/카운터 회귀가 목적이므로
        # 신규 가드(quiescence)는 비활성화해 분류 진입을 막지 않도록 한다.
        quiescence_seconds=0.0,
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
        fake_classifier.classify = AsyncMock(
            return_value=decision_cls(
                path="inbox/memo.md",
                category="infra",
                tags=("vim",),
                confidence=0.95,
                reasoning="r",
                provider="claude-code:haiku",
                raw_response="{}",
            )
        )
        fake_classifier_cls.return_value = fake_classifier
        runner = DaemonRunner(opts)
        runner._classifier = fake_classifier
        runner._indexer = fake_idx
        return runner, fake_idx


@pytest.mark.asyncio
async def test_post_apply_reindex_is_serialized_across_workers() -> None:
    """두 worker가 동시에 _classify_and_apply를 호출해도 reindex는 절대 겹치지 않는다.

    v0.2.3 회귀: 두 worker가 동시에 drop_table → create_table 시도 → ValueError.
    v0.2.4: _reindex_lock으로 어느 시점에도 reindex 동시 실행이 1을 넘지 않아야 함.
    """
    from wiki_search_mcp.core.models import ClassificationDecision

    with tempfile.TemporaryDirectory() as td:
        wiki = Path(td) / "wiki"
        (wiki / "pages" / "inbox").mkdir(parents=True)

        runner, fake_idx = _build_runner(wiki, ClassificationDecision)
        runner._reindex_lock = asyncio.Lock()

        # 동시성 카운터 — reindex가 겹치면 1을 초과
        concurrent = 0
        peak = 0

        def slow_reindex(full: bool = False) -> None:
            nonlocal concurrent, peak
            concurrent += 1
            peak = max(peak, concurrent)
            # 짧은 sleep으로 다른 task가 끼어들 기회 부여
            import time
            time.sleep(0.05)
            concurrent -= 1

        fake_idx.reindex.side_effect = slow_reindex

        # 두 개 .md 파일 생성
        for i in range(2):
            p = wiki / "pages" / "inbox" / f"memo-{i}.md"
            p.write_text("---\n---\n# memo\n", encoding="utf-8")

        # 첫 번째 task와 두 번째 task의 path가 다르게 분류되도록 classifier 동적 변경
        async def _classify(rel: str) -> ClassificationDecision:
            return ClassificationDecision(
                path=rel,
                category="infra",
                tags=("t",),
                confidence=0.95,
                reasoning="r",
                provider="p",
                raw_response="{}",
            )

        runner._classifier.classify = _classify

        await asyncio.gather(
            runner._classify_and_apply("inbox/memo-0.md"),
            runner._classify_and_apply("inbox/memo-1.md"),
        )

        assert fake_idx.reindex.call_count == 2
        assert peak == 1, f"reindex 동시 실행됨 (peak={peak}) — lock 동작 안 함"


@pytest.mark.asyncio
async def test_reindex_failure_records_reindex_error_count() -> None:
    """reindex 실패는 ``reindex_error_count`` 카운터에 집계되고 ``error_count``는 건드리지 않는다.

    분류 자체는 성공이므로 error_count로 묶으면 운영자가 분류 실패와 혼동.
    """
    from wiki_search_mcp.core.models import ClassificationDecision

    with tempfile.TemporaryDirectory() as td:
        wiki = Path(td) / "wiki"
        (wiki / "pages" / "inbox").mkdir(parents=True)
        (wiki / "pages" / "inbox" / "memo.md").write_text(
            "---\n---\n# m\n", encoding="utf-8"
        )

        runner, fake_idx = _build_runner(wiki, ClassificationDecision)
        runner._reindex_lock = asyncio.Lock()
        fake_idx.reindex.side_effect = ValueError("Table 'wiki' already exists")
        fake_status = MagicMock()
        runner._status = fake_status

        await runner._classify_and_apply("inbox/memo.md")

        calls = [c.args[0] for c in fake_status.increment.call_args_list if c.args]
        assert "reindex_error_count" in calls, (
            f"reindex_error_count 카운터 증가 안 함: {calls}"
        )
        assert "applied_count" in calls, "applied_count는 그대로 증가해야 함 (분류 성공)"
        assert "error_count" not in calls, (
            f"분류는 성공이므로 error_count는 증가하면 안 됨: {calls}"
        )


def test_indexer_uses_mode_overwrite_to_avoid_race() -> None:
    """``reindex(full=True)``는 lancedb ``create_table(mode='overwrite')`` 단일 호출로
    수행되어야 한다. 별도 ``drop_table`` → ``create_table`` 분리는
    multi-worker daemon에서 race를 유발한다 (v0.2.3 장애 보고서).
    """
    src_path = Path(__file__).resolve().parents[3] / "src" / "wiki_search_mcp" / "infrastructure" / "indexing" / "indexer.py"
    source = src_path.read_text(encoding="utf-8")
    # drop_table 호출이 reindex 경로에서 제거됐는지 — open_table을 위한 list_tables는 허용
    # 새 가드: create_table 호출에 mode="overwrite" 명시
    assert 'create_table("wiki", records, mode="overwrite")' in source, (
        "indexer.reindex가 mode='overwrite'를 사용하지 않음 — race 회귀 가능"
    )
    # 명시적 drop_table 호출은 사라져야 함
    assert "drop_table(\"wiki\")" not in source, (
        "drop_table+create_table 분리는 두 worker 동시 실행 시 race 발생"
    )
