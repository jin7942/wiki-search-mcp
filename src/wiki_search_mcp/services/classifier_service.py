"""ClassifierService — 휴리스틱 힌트 + LLM 호출 결합.

Daemon이 사용하는 분류 진입점. 휴리스틱(폴더/유사문서) 결과를 LLM에게 힌트로 전달하지만
**최종 결정은 LLM이 한다** (휴리스틱 단독 적용 안 함).

흐름:
1. ``ClassificationService.suggest_classification(path)`` 호출 → ``ClassificationSuggestion``
2. 본문 앞 N자 + 카테고리 목록 + suggestion을 prompt에 주입
3. ``LLMProvider.classify(req)`` → ``ClassificationDecision``
4. Daemon이 ``confidence_threshold`` 기준으로 적용/pending 분기
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from wiki_search_mcp.core.exceptions import (
    ClassifierError,
    DocumentNotFoundError,
)
from wiki_search_mcp.core.models import ClassificationDecision
from wiki_search_mcp.core.utils import parse_frontmatter
from wiki_search_mcp.services.llm.provider import (
    ClassificationRequest,
    LLMProvider,
)

if TYPE_CHECKING:
    from wiki_search_mcp.services.category_service import CategoryService
    from wiki_search_mcp.services.classification_service import ClassificationService

logger = logging.getLogger(__name__)


DEFAULT_BODY_PREVIEW_CHARS = 4000


class ClassifierService:
    """daemon이 사용하는 분류 진입점."""

    def __init__(
        self,
        *,
        classification_service: "ClassificationService",
        category_service: "CategoryService",
        provider: LLMProvider,
        pages_path: Path,
        body_preview_chars: int = DEFAULT_BODY_PREVIEW_CHARS,
    ):
        self._suggest = classification_service
        self._categories = category_service
        self._provider = provider
        self._pages = Path(pages_path)
        self._preview_chars = body_preview_chars

    async def classify(self, rel_path: str) -> ClassificationDecision:
        """단일 파일에 대해 LLM 분류 호출.

        Raises:
            DocumentNotFoundError: 파일이 디스크에 없을 때
            ClassifierError: LLM 호출/파싱 실패
        """
        full = self._pages / rel_path
        if not full.exists() or not full.is_file():
            raise DocumentNotFoundError.of(rel_path)

        try:
            content = full.read_text(encoding="utf-8")
        except OSError as e:
            raise ClassifierError.of(
                f"failed to read {rel_path}: {e}",
                code="SDK_ERROR",
                details={"path": rel_path},
            ) from e

        _, body = parse_frontmatter(content)
        body_preview = body[: self._preview_chars]

        suggestion = self._suggest.suggest_classification(rel_path)
        listing = self._categories.list_categories()
        active = tuple(listing.categories) if listing.categories else ()

        req = ClassificationRequest(
            path=rel_path,
            body_preview=body_preview,
            suggestion_hints=suggestion.to_dict(),
            active_categories=active,
        )
        decision = await self._provider.classify(req)
        logger.info(
            "classified %s -> category=%s confidence=%.2f tags=%s",
            rel_path,
            decision.category,
            decision.confidence,
            list(decision.tags),
        )
        return decision
