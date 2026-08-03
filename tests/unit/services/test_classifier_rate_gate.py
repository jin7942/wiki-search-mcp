"""ClassifierService rate-limit 게이트 위치 테스트 (0.7.0 P0).

요청서 참고사항: pending 1650건 전수 rate_limited + applied 0 의 원인 중 하나는
worker 가 dequeue 즉시 rate 슬롯을 소비해, 가드(too_short/user_locked)나
quiescence 로 스킵되는 파일까지 일일 LLM 예산을 전소시키던 것.

0.7.0: rate 슬롯은 실제 LLM 호출 직전에만 소비한다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiki_search_mcp.core.exceptions import RateLimitError
from wiki_search_mcp.core.models import ClassificationDecision
from wiki_search_mcp.services.classifier_service import (
    ClassifierService,
    ClassifierSkipped,
)


def _decision(path: str) -> ClassificationDecision:
    return ClassificationDecision(
        path=path,
        category="projects",
        tags=("t",),
        confidence=0.9,
        reasoning="r",
        provider="fake",
    )


class _FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def classify(self, req):
        self.calls.append(req.path)
        return _decision(req.path)


def _make_service(pages: Path, provider, rate_acquire) -> ClassifierService:
    suggest = MagicMock()
    suggest.suggest_classification.return_value = MagicMock(
        to_dict=lambda: {"category_candidates": [], "tag_candidates": []}
    )
    categories = MagicMock()
    categories.list_categories.return_value = MagicMock(categories=("projects",))
    categories.list_subfolders.return_value = {}
    return ClassifierService(
        classification_service=suggest,
        category_service=categories,
        provider=provider,
        pages_path=pages,
        min_body_chars=10,
        rate_acquire=rate_acquire,
    )


def _write(pages: Path, rel: str, text: str) -> None:
    p = pages / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_guard_skip_does_not_consume_rate_budget(tmp_path: Path) -> None:
    """too_short / user_locked 가드는 rate 슬롯을 소비하지 않는다."""
    acquired: list[int] = []

    async def rate_acquire() -> None:
        acquired.append(1)

    provider = _FakeProvider()
    svc = _make_service(tmp_path, provider, rate_acquire)

    _write(tmp_path, "inbox/short.md", "---\n---\n\n짧음")
    _write(
        tmp_path,
        "inbox/locked.md",
        "---\ndraft: true\n---\n\n" + "긴 본문 " * 50,
    )

    for rel in ("inbox/short.md", "inbox/locked.md"):
        with pytest.raises(ClassifierSkipped):
            asyncio.run(svc.classify(rel))

    assert acquired == []  # 예산 소비 없음
    assert provider.calls == []


def test_rate_acquired_before_llm_call(tmp_path: Path) -> None:
    """정상 분류는 LLM 호출 직전에 rate 슬롯을 정확히 1회 소비."""
    acquired: list[int] = []

    async def rate_acquire() -> None:
        acquired.append(1)

    provider = _FakeProvider()
    svc = _make_service(tmp_path, provider, rate_acquire)
    _write(tmp_path, "inbox/doc.md", "---\n---\n\n" + "충분히 긴 본문 " * 20)

    decision = asyncio.run(svc.classify("inbox/doc.md"))

    assert decision.category == "projects"
    assert acquired == [1]
    assert provider.calls == ["inbox/doc.md"]


def test_rate_limit_error_prevents_llm_call(tmp_path: Path) -> None:
    """rate 한도 초과면 LLM 호출 자체가 일어나지 않는다."""

    async def rate_acquire() -> None:
        raise RateLimitError.of(30000.0)

    provider = _FakeProvider()
    svc = _make_service(tmp_path, provider, rate_acquire)
    _write(tmp_path, "inbox/doc.md", "---\n---\n\n" + "충분히 긴 본문 " * 20)

    with pytest.raises(RateLimitError):
        asyncio.run(svc.classify("inbox/doc.md"))
    assert provider.calls == []
