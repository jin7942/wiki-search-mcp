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
import time
from pathlib import Path
from typing import TYPE_CHECKING

from wiki_search_mcp.core.exceptions import (
    ClassifierError,
    DocumentNotFoundError,
)
from wiki_search_mcp.core.metrics import record
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
DEFAULT_MIN_BODY_CHARS = 200


class ClassifierSkipped(Exception):
    """LLM 호출 전 가드에 의해 분류가 건너뛰어졌음을 의미한다.

    ``reason`` 은 daemon 측 pending.jsonl 의 reason 필드로 그대로 기록되도록
    안정된 short token 으로 유지한다 (``too_short`` / ``user_locked``).
    """

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


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
        min_body_chars: int = DEFAULT_MIN_BODY_CHARS,
    ):
        self._suggest = classification_service
        self._categories = category_service
        self._provider = provider
        self._pages = Path(pages_path)
        self._preview_chars = body_preview_chars
        self._min_body_chars = min_body_chars

    async def classify(self, rel_path: str) -> ClassificationDecision:
        """단일 파일에 대해 LLM 분류 호출.

        진입 가드(LLM 호출 전):
        - 본문(frontmatter 제외)의 ``strip()`` 길이가 ``min_body_chars`` 미만이면
          ``ClassifierSkipped("too_short")``.
        - frontmatter 에 ``draft: true`` 또는 ``locked: true`` 가 있으면
          ``ClassifierSkipped("user_locked")``. 사용자가 작성 중임을 명시한 신호.

        Raises:
            DocumentNotFoundError: 파일이 디스크에 없을 때
            ClassifierSkipped: 가드에 걸려 분류를 건너뜀 (daemon 이 pending 으로 처리)
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

        meta, body = parse_frontmatter(content)

        # 사용자 명시 보호 — draft/locked 가 truthy 면 분류 안 함.
        # "true" 문자열도 허용(에디터마다 YAML 직렬화가 다름).
        if _is_truthy(meta.get("draft")) or _is_truthy(meta.get("locked")):
            raise ClassifierSkipped("user_locked")

        if len(body.strip()) < self._min_body_chars:
            raise ClassifierSkipped("too_short")

        body_preview = body[: self._preview_chars]

        suggestion = self._suggest.suggest_classification(rel_path)
        listing = self._categories.list_categories()
        active = tuple(listing.categories) if listing.categories else ()

        # 카테고리별 서브폴더(2-depth) 목록 — LLM 이 평탄 배치 대신 적절한
        # 프로젝트 서브폴더로 라우팅할 수 있도록 힌트로 전달.
        try:
            subfolders = self._categories.list_subfolders()
        except Exception:
            logger.debug("list_subfolders() failed", exc_info=True)
            subfolders = {}

        req = ClassificationRequest(
            path=rel_path,
            body_preview=body_preview,
            suggestion_hints=suggestion.to_dict(),
            active_categories=active,
            subfolders_by_category=subfolders,
        )
        _llm_start = time.perf_counter()
        decision = await self._provider.classify(req)
        llm_ms = round((time.perf_counter() - _llm_start) * 1000, 1)
        logger.info(
            "classified %s -> category=%s subcategory=%s confidence=%.2f tags=%s",
            rel_path,
            decision.category,
            decision.subcategory or "-",
            decision.confidence,
            list(decision.tags),
        )
        # 구조화 메트릭: LLM 분류 호출 시간/결과. 분류 지연 원인 추적의 핵심 지표.
        # (재시도는 provider 내부에서 처리되며 transient 실패는 logger.warning 으로 남음.)
        record(
            "llm_classify",
            duration_ms=llm_ms,
            path=rel_path,
            category=decision.category,
            confidence=round(decision.confidence, 2),
        )
        return decision


def _is_truthy(value: object) -> bool:
    """frontmatter 의 draft/locked 값을 관대하게 boolean 으로 해석.

    YAML 라이브러리/에디터마다 ``True``/``"true"``/``"yes"`` 등 표현이 갈리므로
    흔한 truthy 표현을 폭넓게 인정. ``None``/``False``/빈 문자열은 모두 False.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "on"}
    return False
