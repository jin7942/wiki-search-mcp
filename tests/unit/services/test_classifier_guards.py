"""ClassifierService 진입 가드 (v0.4.0) 회귀 테스트.

장애 보고서 #1: inbox 작성 중 분류기가 미완성 본문을 LLM 에 보내 카테고리를
결정해 버리던 문제. 두 가지 가드로 차단:

- 본문이 너무 짧음 → ``ClassifierSkipped("too_short")``
- frontmatter ``draft:true`` / ``locked:true`` → ``ClassifierSkipped("user_locked")``

가드는 LLM 호출 *전에* 발동해야 하며, provider 는 호출되면 안 된다.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiki_search_mcp.core.models import (
    CategoryListing,
    ClassificationDecision,
    ClassificationSuggestion,
)
from wiki_search_mcp.services.classifier_service import (
    ClassifierService,
    ClassifierSkipped,
)
from wiki_search_mcp.services.llm.provider import ClassificationRequest


class _CountingProvider:
    """LLM 이 호출됐는지 추적하는 가짜 provider."""

    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    async def classify(self, req: ClassificationRequest) -> ClassificationDecision:
        self.calls += 1
        return ClassificationDecision(
            path=req.path,
            category="infra",
            tags=(),
            confidence=0.9,
            reasoning="r",
            provider="fake",
            raw_response="",
        )

    async def healthcheck(self) -> None:
        return


def _make_service(pages: Path, *, min_body_chars: int) -> tuple[ClassifierService, _CountingProvider]:
    provider = _CountingProvider()
    suggest = MagicMock()
    suggest.suggest_classification.return_value = ClassificationSuggestion.of(
        path="inbox/x.md",
        category_candidates=["infra"],
        tag_candidates=(),
        similar_paths=(),
        reasoning="",
    )
    cats = MagicMock()
    cats.list_categories.return_value = CategoryListing.of(
        mode="folder", categories=["infra"], detected_at="now"
    )
    cats.list_subfolders.return_value = {}
    svc = ClassifierService(
        classification_service=suggest,
        category_service=cats,
        provider=provider,
        pages_path=pages,
        min_body_chars=min_body_chars,
    )
    return svc, provider


@pytest.mark.asyncio
async def test_short_body_raises_skipped_too_short(tmp_path: Path) -> None:
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "x.md").write_text(
        "---\ntitle: x\n---\n# 새 회의", encoding="utf-8"
    )
    svc, provider = _make_service(tmp_path, min_body_chars=200)

    with pytest.raises(ClassifierSkipped) as ei:
        await svc.classify("inbox/x.md")
    assert ei.value.reason == "too_short"
    assert provider.calls == 0, "본문이 짧으면 LLM 을 호출하지 않아야 한다"


@pytest.mark.asyncio
async def test_min_body_chars_zero_disables_guard(tmp_path: Path) -> None:
    """``min_body_chars=0`` 이면 가드 비활성 — 기존 동작 회귀 방지."""
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "x.md").write_text("# 짧음", encoding="utf-8")
    svc, provider = _make_service(tmp_path, min_body_chars=0)

    decision = await svc.classify("inbox/x.md")
    assert decision.category == "infra"
    assert provider.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("draft_value", [True, "true", "yes"])
async def test_draft_frontmatter_locks_classification(
    tmp_path: Path, draft_value: object
) -> None:
    (tmp_path / "inbox").mkdir()
    body = "본문 " * 200  # min_body_chars 통과 길이
    (tmp_path / "inbox" / "x.md").write_text(
        f"---\ntitle: x\ndraft: {draft_value}\n---\n{body}", encoding="utf-8"
    )
    svc, provider = _make_service(tmp_path, min_body_chars=0)

    with pytest.raises(ClassifierSkipped) as ei:
        await svc.classify("inbox/x.md")
    assert ei.value.reason == "user_locked"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_locked_frontmatter_locks_classification(tmp_path: Path) -> None:
    (tmp_path / "inbox").mkdir()
    body = "본문 " * 200
    (tmp_path / "inbox" / "x.md").write_text(
        f"---\ntitle: x\nlocked: true\n---\n{body}", encoding="utf-8"
    )
    svc, provider = _make_service(tmp_path, min_body_chars=0)

    with pytest.raises(ClassifierSkipped) as ei:
        await svc.classify("inbox/x.md")
    assert ei.value.reason == "user_locked"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_draft_false_does_not_block(tmp_path: Path) -> None:
    """``draft: false`` 는 가드를 트리거하지 않는다 (값 분기 확인)."""
    (tmp_path / "inbox").mkdir()
    body = "본문 " * 200
    (tmp_path / "inbox" / "x.md").write_text(
        f"---\ntitle: x\ndraft: false\n---\n{body}", encoding="utf-8"
    )
    svc, provider = _make_service(tmp_path, min_body_chars=0)

    decision = await svc.classify("inbox/x.md")
    assert decision.category == "infra"
    assert provider.calls == 1
