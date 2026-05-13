"""ClassifierService 단위 테스트 (provider/suggestion mock)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiki_search_mcp.core.exceptions import DocumentNotFoundError
from wiki_search_mcp.core.models import (
    CategoryListing,
    ClassificationDecision,
    ClassificationSuggestion,
)
from wiki_search_mcp.services.classifier_service import ClassifierService
from wiki_search_mcp.services.llm.provider import ClassificationRequest


class _FakeProvider:
    name = "fake"

    def __init__(self, decision: ClassificationDecision):
        self._decision = decision
        self.captured: ClassificationRequest | None = None

    async def classify(self, req: ClassificationRequest) -> ClassificationDecision:
        self.captured = req
        return self._decision

    async def healthcheck(self) -> None:
        return


@pytest.mark.asyncio
async def test_classify_uses_suggestion_and_categories(tmp_path: Path) -> None:
    pages = tmp_path
    (pages / "inbox").mkdir()
    (pages / "inbox" / "x.md").write_text(
        "---\ntitle: x\n---\n\nhello body 한글", encoding="utf-8"
    )

    decision = ClassificationDecision(
        path="inbox/x.md",
        category="infra",
        tags=("nginx",),
        confidence=0.85,
        reasoning="r",
        provider="fake",
        raw_response="",
    )
    provider = _FakeProvider(decision)

    suggest = MagicMock()
    suggest.suggest_classification.return_value = ClassificationSuggestion.of(
        path="inbox/x.md",
        category_candidates=["infra", "notes"],
        tag_candidates=["nginx"],
        similar_paths=["infra/y.md"],
        reasoning="hint",
    )
    cats = MagicMock()
    cats.list_categories.return_value = CategoryListing.of(
        mode="folder", categories=["infra", "notes"], detected_at="now"
    )

    svc = ClassifierService(
        classification_service=suggest,
        category_service=cats,
        provider=provider,
        pages_path=pages,
    )
    out = await svc.classify("inbox/x.md")
    assert out.category == "infra"
    assert provider.captured is not None
    assert provider.captured.active_categories == ("infra", "notes")
    assert provider.captured.suggestion_hints["category_candidates"] == ["infra", "notes"]
    assert "hello body 한글" in provider.captured.body_preview


@pytest.mark.asyncio
async def test_classify_raises_when_missing(tmp_path: Path) -> None:
    provider = _FakeProvider(MagicMock())
    suggest = MagicMock()
    cats = MagicMock()
    svc = ClassifierService(
        classification_service=suggest,
        category_service=cats,
        provider=provider,
        pages_path=tmp_path,
    )
    with pytest.raises(DocumentNotFoundError):
        await svc.classify("does-not-exist.md")
