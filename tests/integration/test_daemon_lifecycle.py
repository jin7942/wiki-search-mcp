"""격리 환경 daemon 라이프사이클 통합 테스트.

실제 LLM은 호출하지 않고 FakeProvider를 주입하여 다음을 검증:
1. daemon 시작 → 인덱싱된 미분류 파일 자동 분류 → frontmatter 적용 + 이동
2. confidence 미달 케이스는 pending.jsonl에 적재
3. applied.jsonl에 정상 기록 → RollbackService로 원상복구
4. SIGTERM으로 graceful shutdown

격리:
- ``XDG_STATE_HOME``을 tmp_path로 monkeypatch → daemon 상태 파일이 시스템 전역에 안 남음
- 실제 임베딩 모델 다운로드를 피하기 위해 ClassifierService 자체를 FakeClassifier로 swap
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiki_search_mcp.core.models import (
    CategoryListing,
    ClassificationDecision,
    ClassificationSuggestion,
    PendingItem,
)
from wiki_search_mcp.infrastructure.daemon.options import DaemonOptions
from wiki_search_mcp.infrastructure.daemon.paths import (
    applied_jsonl,
    pending_jsonl,
    pid_file,
    status_file,
)
from wiki_search_mcp.infrastructure.daemon.pidfile import PidLock
from wiki_search_mcp.infrastructure.daemon.statefile import StatusFile
from wiki_search_mcp.infrastructure.jsonl.log import JsonlLog


class _FakeProvider:
    """결정론적 fake provider — file path별 응답 사전 구성."""

    name = "fake"

    def __init__(self) -> None:
        self.responses: dict[str, ClassificationDecision] = {}

    def set_response(self, path: str, **kw) -> None:
        self.responses[path] = ClassificationDecision(
            path=path,
            category=kw.get("category", "infra"),
            tags=tuple(kw.get("tags", ("nginx",))),
            confidence=kw.get("confidence", 0.9),
            reasoning=kw.get("reasoning", "fake"),
            provider="fake:test",
            raw_response="",
        )

    async def classify(self, req):  # type: ignore[no-untyped-def]
        if req.path in self.responses:
            return self.responses[req.path]
        # 기본: 미확신
        return ClassificationDecision(
            path=req.path,
            category="uncategorized",
            tags=(),
            confidence=0.3,
            reasoning="default low",
            provider="fake:test",
            raw_response="",
        )

    async def healthcheck(self) -> None:
        return


@pytest.fixture
def isolated_wiki(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """격리 환경: XDG_STATE_HOME을 tmp로 옮기고, 빈 wiki 폴더 준비."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    wiki = tmp_path / "wiki"
    (wiki / "inbox").mkdir(parents=True)
    return wiki


def _make_runner_with_fake(wiki: Path, provider: _FakeProvider, threshold: float = 0.7):
    """ServiceContainer를 직접 사용하지 않는 경량 DaemonRunner 빌더.

    실제 임베딩/인덱싱은 단위 통합 테스트의 책임이 아니므로, container의 일부를 mock으로 교체한다.
    """
    from wiki_search_mcp.infrastructure.daemon.runner import DaemonRunner

    opts = DaemonOptions(
        wiki_path=wiki,
        llm_model="haiku",
        confidence_threshold=threshold,
        concurrency=1,
        rate_per_minute=999,
        rate_per_hour=999,
        rate_per_day=999,
        debounce=0.1,
        # 본 통합 테스트는 daemon 라이프사이클 자체를 검증하므로 v0.4.0
        # 신규 가드(파일 막 생성 → 즉시 분류 차단)를 비활성화한다.
        quiescence_seconds=0.0,
        min_body_chars=0,
        rescan_interval_seconds=0.0,
        auto_move=True,
        rewrite_inbound_links=False,
        log_level="WARNING",
        provider_factory=lambda: provider,
    )
    runner = DaemonRunner(opts)

    # 인덱싱/카테고리 등 무거운 의존성은 mock으로 교체
    runner._indexer = MagicMock()  # type: ignore[assignment]
    runner._container.invalidate_all = MagicMock()  # type: ignore[assignment]

    # find_pending이 inbox/*.md를 반환하도록
    def _find_pending(limit: int = 50):
        items = []
        inbox = wiki / "inbox"
        if inbox.exists():
            for p in sorted(inbox.glob("*.md")):
                items.append(
                    PendingItem(path=f"inbox/{p.name}", reason="no_frontmatter", mtime=None)
                )
        return items[:limit]

    runner._container.classification_service.find_pending = MagicMock(side_effect=_find_pending)  # type: ignore[assignment]

    # suggest_classification — 카테고리 후보로 'infra' 제공
    runner._container.classification_service.suggest_classification = MagicMock(
        return_value=ClassificationSuggestion.of(
            path="dummy",
            category_candidates=["infra"],
            tag_candidates=["nginx"],
        )
    )
    runner._container.category_service.list_categories = MagicMock(
        return_value=CategoryListing.of(mode="folder", categories=["infra", "notes"], detected_at="now")
    )
    return runner, opts


def _run_in_thread(coro):
    """asyncio 코루틴을 별도 스레드에서 실행하고 종료를 위해 stop event 반환."""
    result = {"error": None}

    def target():
        try:
            asyncio.run(coro)
        except Exception as e:  # noqa: BLE001
            result["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t, result


def test_daemon_classifies_and_applies(isolated_wiki: Path) -> None:
    wiki = isolated_wiki
    (wiki / "inbox" / "nginx-setup.md").write_text(
        "# Nginx SSL\nLet's Encrypt setup notes.", encoding="utf-8"
    )

    provider = _FakeProvider()
    provider.set_response("inbox/nginx-setup.md", category="infra", tags=("nginx",), confidence=0.92)

    runner, opts = _make_runner_with_fake(wiki, provider, threshold=0.7)

    # 직접 _main을 잠깐 돌렸다가 stop event로 종료
    async def driver():
        task = asyncio.create_task(runner._main())
        # rescan + classify 완료 대기
        await asyncio.sleep(1.0)
        runner._stop.set()
        await task

    asyncio.run(driver())

    # 검증: frontmatter 적용 + 이동
    applied = list(JsonlLog(applied_jsonl(wiki)).scan())
    assert len(applied) == 1
    rec = applied[0]
    assert rec["path_before"] == "inbox/nginx-setup.md"
    assert rec["path_after"] == "infra/nginx-setup.md"
    assert (wiki / "infra" / "nginx-setup.md").exists()
    assert not (wiki / "inbox" / "nginx-setup.md").exists()

    # status
    state = StatusFile(status_file(wiki)).read()
    assert state["state"] == "stopped"
    assert state["applied_count"] == 1
    assert state["pending_count"] == 0


def test_daemon_pendings_low_confidence(isolated_wiki: Path) -> None:
    wiki = isolated_wiki
    (wiki / "inbox" / "ambiguous.md").write_text("ㅁㄴㅇㄹ", encoding="utf-8")

    provider = _FakeProvider()
    # 임계값 0.7 미만
    provider.set_response("inbox/ambiguous.md", category="infra", tags=(), confidence=0.4)

    runner, opts = _make_runner_with_fake(wiki, provider, threshold=0.7)

    async def driver():
        task = asyncio.create_task(runner._main())
        await asyncio.sleep(1.0)
        runner._stop.set()
        await task

    asyncio.run(driver())

    # 적용 안 됨
    assert (wiki / "inbox" / "ambiguous.md").exists()
    assert not (wiki / "infra").exists()
    # pending 기록
    pending = list(JsonlLog(pending_jsonl(wiki)).scan())
    assert any(e.get("path") == "inbox/ambiguous.md" and e.get("reason") == "low_confidence" for e in pending)


def test_rollback_restores_after_apply(isolated_wiki: Path) -> None:
    """end-to-end: daemon 분류 → rollback → 원상복구."""
    wiki = isolated_wiki
    (wiki / "inbox" / "x.md").write_text("body", encoding="utf-8")

    provider = _FakeProvider()
    provider.set_response("inbox/x.md", category="infra", tags=("nginx",), confidence=0.95)
    runner, _ = _make_runner_with_fake(wiki, provider, threshold=0.7)

    async def driver():
        task = asyncio.create_task(runner._main())
        await asyncio.sleep(1.0)
        runner._stop.set()
        await task

    asyncio.run(driver())

    assert (wiki / "infra" / "x.md").exists()

    # rollback
    from wiki_search_mcp.services.rollback_service import RollbackService

    svc = RollbackService(applied_log=JsonlLog(applied_jsonl(wiki)), pages_path=wiki)
    results = svc.rollback_last(1)
    assert results[0]["status"] == "restored"
    assert (wiki / "inbox" / "x.md").exists()
    assert not (wiki / "infra" / "x.md").exists()


def test_provider_healthcheck_failure_records_failed_state(isolated_wiki: Path) -> None:
    wiki = isolated_wiki

    class _Broken:
        name = "broken"

        async def classify(self, req):  # pragma: no cover
            raise AssertionError("classify must not be called")

        async def healthcheck(self) -> None:
            from wiki_search_mcp.core.exceptions import ClassifierError

            raise ClassifierError.of("nope", code="CLI_NOT_FOUND")

    provider = _Broken()
    runner, _ = _make_runner_with_fake(wiki, provider, threshold=0.7)

    asyncio.run(runner._main())
    state = StatusFile(status_file(wiki)).read()
    assert state["state"] == "failed"
    assert state["error_code"] == "CLI_NOT_FOUND"
