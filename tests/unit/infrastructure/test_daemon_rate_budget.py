"""DaemonRunner LLM 호출 예산 회귀 테스트 (0.7.1).

장애 보고서(2026-11-13, 0.6.1 운영): 본문 200자 미만 inbox 파일 5개가 가드에
걸려 LLM 을 부르지 않으면서도 rate 슬롯을 먼저 차감해 일일 한도 500회를
독점했고, 분류 가능한 파일은 최장 28일간 한 번도 분류되지 못했다.

기존 테스트는 ``ClassifierService`` 를 mock 으로 바꿔 끼워 runner 단위에서
rate 게이트를 검증하지 못했다. 여기서는 실제 ``ClassifierService`` + 실제
``SlidingWindowRateLimit`` 을 쓰고 provider 만 가짜로 둔다.

- 가드/quiescence/파일 없음 경로는 rate 슬롯을 쓰지 않는다 (0.7.0 수정의 회귀 고정).
- 가드 skip / low_confidence 는 내용(mtime)이 바뀌기 전엔 재투입하지 않는다.
- status 의 pending_count 는 현재 대기 path 수, rate 는 한도 사용량.
- pending.jsonl 은 상한 초과 시 path 별 최신 1건으로 압축된다.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wiki_search_mcp.core.models import (
    CategoryListing,
    ClassificationDecision,
    ClassificationSuggestion,
    PendingItem,
)
from wiki_search_mcp.infrastructure.daemon.options import DaemonOptions
from wiki_search_mcp.infrastructure.daemon.runner import DaemonRunner
from wiki_search_mcp.infrastructure.daemon.status_reader import read_daemon_pending

SHORT = "짧은 메모\n"
LONG = "가" * 400


@pytest.fixture(autouse=True)
def _xdg_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


@pytest.fixture
def wiki(tmp_path: Path) -> Path:
    w = tmp_path / "wiki"
    (w / "inbox").mkdir(parents=True)
    return w


class _FakeProvider:
    """호출 경로를 기록하고 고정 confidence 로 응답하는 provider."""

    name = "fake"

    def __init__(self, confidence: float = 0.9) -> None:
        self.confidence = confidence
        self.calls: list[str] = []

    async def healthcheck(self) -> None:
        return None

    async def classify(self, req):  # type: ignore[no-untyped-def]
        self.calls.append(req.path)
        return ClassificationDecision(
            path=req.path,
            category="notes",
            tags=("x",),
            confidence=self.confidence,
            reasoning="fake",
            provider="fake",
        )


def _write(wiki: Path, name: str, body: str) -> Path:
    """inbox 파일 작성. mtime 을 1시간 전으로 둬 quiescence 영향을 없앤다."""
    p = wiki / "inbox" / name
    p.write_text(body, encoding="utf-8")
    old = time.time() - 3600
    os.utime(p, (old, old))
    return p


def _build(wiki: Path, provider: _FakeProvider, **overrides: object) -> DaemonRunner:
    """실제 ClassifierService/rate limiter/status/pending 로그를 쓰는 runner."""
    opts = DaemonOptions(
        **{
            "wiki_path": wiki,
            "provider_factory": lambda: provider,
            "quiescence_seconds": 0.0,
            "rescan_interval_seconds": 0.0,
            **overrides,
        }
    )
    with patch("wiki_search_mcp.infrastructure.daemon.runner.WikiIndexer"), patch(
        "wiki_search_mcp.infrastructure.daemon.runner.ServiceContainer"
    ) as container_cls:
        container = MagicMock()
        container.pages_path = wiki
        container_cls.return_value = container
        runner = DaemonRunner(opts)

    svc = container.classification_service
    svc.find_pending.side_effect = lambda limit=200: [
        PendingItem(path=f"inbox/{p.name}", reason="in_staging", mtime=None)
        for p in sorted((wiki / "inbox").glob("*.md"))
    ][:limit]
    svc.suggest_classification.return_value = ClassificationSuggestion.of(
        path="x", category_candidates=["notes"], tag_candidates=[]
    )
    container.category_service.list_categories.return_value = CategoryListing.of(
        mode="folder", categories=["notes"], detected_at="now"
    )
    container.category_service.list_subfolders.return_value = {}
    return runner


async def _cycle(runner: DaemonRunner) -> None:
    """rescan 1회 후 큐가 빌 때까지 worker 2개로 처리."""
    runner._loop = asyncio.get_running_loop()
    if runner._reindex_lock is None:
        runner._reindex_lock = asyncio.Lock()
    await runner._rescan()
    workers = [asyncio.create_task(runner._worker(i)) for i in range(2)]
    await runner._queue.join()
    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)


async def _cycles(runner: DaemonRunner, n: int) -> None:
    """rescan 을 n회 반복. 사이마다 시간 cooldown 을 만료시켜 '충분히 시간이 흐른' 상태를 만든다."""
    for _ in range(n):
        await _cycle(runner)
        runner._cooldown.clear()


def _used(runner: DaemonRunner) -> dict[str, int]:
    return {k: v["used"] for k, v in runner._rate.snapshot().items()}


# ---------------------------------------------------------------- rate 예산


async def test_short_files_do_not_starve_classifiable_file(wiki: Path) -> None:
    """보고서 재현: 짧은 파일 5개가 앞에 있어도 긴 파일이 첫 rescan 에 분류된다.

    0.6.1 에서는 짧은 파일 5개가 분당 슬롯 5개를 모두 쓰고 긴 파일은
    RateLimitError 로 밀려 LLM 호출이 0회였다.
    """
    for i in range(5):
        _write(wiki, f"a{i}.md", SHORT)
    _write(wiki, "z-long.md", LONG)
    provider = _FakeProvider(confidence=0.3)
    runner = _build(wiki, provider, rate_per_minute=5, min_body_chars=200)

    await _cycle(runner)

    assert provider.calls == ["inbox/z-long.md"]
    assert _used(runner)["per_minute"] == 1


async def test_guard_and_missing_paths_do_not_consume_rate(wiki: Path) -> None:
    """too_short / user_locked / 파일 없음 경로는 몇 번을 돌아도 슬롯 0."""
    _write(wiki, "short.md", SHORT)
    _write(wiki, "locked.md", "---\ndraft: true\n---\n\n" + LONG)
    provider = _FakeProvider()
    runner = _build(wiki, provider, min_body_chars=200)
    svc = runner._container.classification_service
    base = svc.find_pending.side_effect
    svc.find_pending.side_effect = lambda limit=200: base(limit) + [
        PendingItem(path="inbox/gone.md", reason="in_staging", mtime=None)
    ]

    await _cycles(runner, 3)

    assert provider.calls == []
    assert set(_used(runner).values()) == {0}


async def test_quiescence_skip_does_not_consume_rate(wiki: Path) -> None:
    (wiki / "inbox" / "fresh.md").write_text(LONG, encoding="utf-8")  # mtime = 지금
    provider = _FakeProvider()
    runner = _build(wiki, provider, quiescence_seconds=3600.0)

    await _cycle(runner)

    assert provider.calls == []
    assert set(_used(runner).values()) == {0}


# ------------------------------------------------- 내용 불변이면 재투입 금지


async def test_skipped_file_not_requeued_until_content_changes(wiki: Path) -> None:
    p = _write(wiki, "short.md", SHORT)
    runner = _build(wiki, _FakeProvider(), min_body_chars=200)
    seen: list[str] = []
    original = runner._classifier.classify

    async def counting(rel: str):  # type: ignore[no-untyped-def]
        seen.append(rel)
        return await original(rel)

    runner._classifier.classify = counting  # type: ignore[method-assign]

    await _cycles(runner, 3)
    assert seen == ["inbox/short.md"]  # 같은 내용 → 다시 읽지 않음

    p.write_text(SHORT + "덧붙임\n", encoding="utf-8")  # mtime 갱신
    await _cycle(runner)
    assert seen == ["inbox/short.md", "inbox/short.md"]


async def test_low_confidence_not_reclassified_until_content_changes(wiki: Path) -> None:
    """low_confidence 는 같은 본문으로 LLM 을 rescan 마다 다시 부르지 않는다.

    0.7.0 에서는 cooldown 없이 rescan(기본 300초)마다 재호출해 파일당 하루
    288회를 썼다. 2개면 일일 한도 500을 넘는다.
    """
    p = _write(wiki, "doc.md", LONG)
    provider = _FakeProvider(confidence=0.3)
    runner = _build(wiki, provider)

    await _cycles(runner, 3)
    assert provider.calls == ["inbox/doc.md"]

    p.write_text(LONG + "수정\n", encoding="utf-8")
    await _cycle(runner)
    assert provider.calls == ["inbox/doc.md", "inbox/doc.md"]


async def test_low_confidence_retried_after_ttl(wiki: Path) -> None:
    """내용이 같아도 TTL 이 지나면 한 번 더 시도한다 (카테고리 목록 변화 등 반영)."""
    _write(wiki, "doc.md", LONG)
    provider = _FakeProvider(confidence=0.3)
    runner = _build(wiki, provider)
    runner._low_confidence_retry_seconds = 0.0

    await _cycles(runner, 2)

    assert provider.calls == ["inbox/doc.md", "inbox/doc.md"]


# ------------------------------------------------------------------ status


async def test_status_reports_current_pending_paths_and_rate(wiki: Path) -> None:
    _write(wiki, "a-short.md", SHORT)
    b = _write(wiki, "b-doc.md", LONG)
    provider = _FakeProvider(confidence=0.3)
    runner = _build(wiki, provider, min_body_chars=200)
    runner._status.write({"state": "running", "pending_count": 0})

    await _cycles(runner, 3)
    st = runner._status.read()
    assert st["pending_count"] == 2
    assert st["pending_by_reason"] == {"too_short": 1, "low_confidence": 1}
    assert st["rate"]["per_day"] == {"limit": 500, "used": 1}

    # b 가 수정돼 확신 있게 분류·적용되면 대기에서 빠진다.
    provider.confidence = 0.9
    b.write_text(LONG + "수정\n", encoding="utf-8")
    os.utime(b, (time.time() - 1800,) * 2)
    await _cycle(runner)
    st = runner._status.read()
    assert st["applied_count"] == 1
    assert st["pending_count"] == 1
    assert st["pending_by_reason"] == {"too_short": 1}


# ------------------------------------------------------------- pending 압축


async def test_pending_log_compacted_when_over_limit(wiki: Path) -> None:
    runner = _build(wiki, _FakeProvider())
    log = runner._pending
    for i in range(50):
        log.append(
            {"path": "inbox/a.md", "reason": "rate_limited", "recorded_at": f"2026-11-12T00:00:{i:02d}Z"}
        )
    log.append({"path": "inbox/b.md", "reason": "low_confidence", "recorded_at": "2026-11-12T01:00:00Z"})
    view_before = read_daemon_pending(wiki, limit=100)
    runner._pending_compact_bytes = 1024

    await _cycle(runner)  # inbox 가 비어 있어 분류는 없음

    assert [(e["path"], e["recorded_at"]) for e in log.scan()] == [
        ("inbox/a.md", "2026-11-12T00:00:49Z"),
        ("inbox/b.md", "2026-11-12T01:00:00Z"),
    ]
    assert read_daemon_pending(wiki, limit=100) == view_before
    backup = log.path.with_name(log.path.name + ".prev")
    assert sum(1 for _ in backup.open(encoding="utf-8")) == 51
