from __future__ import annotations

"""Classification service.

미분류 파일 감지(``find_pending``)와 분류 추천(``suggest_classification``)을
담당합니다. MCP는 read-only 원칙을 유지하므로 이 서비스는 추천만 반환하고
실제 파일 수정은 Claude가 일반 도구로 수행합니다.

성능:
- ``find_pending``은 인덱스 기반 추출 우선 → 신규 파일은 set 차집합
- 60초 TTL 캐싱으로 디렉토리 재스캔 비용 최소화
- ``suggest_classification``은 기존 임베딩을 우선 활용 (재인코딩 회피)
"""

import logging
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from wiki_search_mcp.core.config import LISTING_TTL_SECONDS
from wiki_search_mcp.core.exceptions import DocumentNotFoundError
from wiki_search_mcp.core.models import ClassificationSuggestion, PendingItem
from wiki_search_mcp.core.path_validator import validate_path
from wiki_search_mcp.services.tagger_service import AutoTagger

if TYPE_CHECKING:
    from wiki_search_mcp.core.protocols import VectorRepository
    from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher
    from wiki_search_mcp.services.category_service import CategoryService
    from wiki_search_mcp.services.document_service import DocumentService

logger = logging.getLogger(__name__)


def _format_mtime(path: Path) -> str | None:
    """파일 mtime을 ISO 8601 문자열로 반환."""
    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, timezone.utc).isoformat()
    except OSError:
        return None


class ClassificationService:
    """미분류 파일 감지 + 분류 추천.

    Attributes:
        pages_path: 페이지 루트
        vector_repository: 인덱스 조회 (pending/추천 모두에서 사용)
        document_service: 유사 문서 조회
        category_service: 카테고리 후보 조회
        ignore_matcher: 무시 패턴 매처
    """

    def __init__(
        self,
        pages_path: Path,
        vector_repository: "VectorRepository",
        document_service: "DocumentService",
        category_service: "CategoryService",
        ignore_matcher: "IgnoreMatcher",
        clock: callable = time.monotonic,
    ):
        """ClassificationService 초기화.

        Args:
            pages_path: 페이지 루트 (rglob 기준)
            vector_repository: 벡터 저장소
            document_service: 문서 서비스
            category_service: 카테고리 서비스
            ignore_matcher: 무시 매처
            clock: 캐시 만료 판정용 시계
        """
        self._pages_path = pages_path
        self._vector = vector_repository
        self._document_service = document_service
        self._category_service = category_service
        self._ignore_matcher = ignore_matcher
        self._clock = clock
        self._cached_pending: list[PendingItem] | None = None
        self._cached_at: float = 0.0

    def find_pending(self, limit: int = 50) -> list[PendingItem]:
        """미분류 / 정리 대기 파일 목록 반환.

        다음 두 소스를 합쳐 결과를 만듭니다.
        1. 인덱스: ``category``가 비어있거나 ``uncategorized``인 문서
        2. 디스크: 인덱스에 없는 신규 .md 파일

        결과는 60초 TTL로 캐시됩니다.

        Args:
            limit: 반환할 최대 개수

        Returns:
            PendingItem 리스트
        """
        if self._is_cache_valid():
            return (self._cached_pending or [])[:limit]

        items: list[PendingItem] = []
        seen_paths: set[str] = set()

        # 1차: 인덱스 기반 추출
        if self._vector.exists():
            try:
                docs = self._vector.to_arrow_list()
            except Exception as e:
                logger.warning(f"Failed to read vector index: {e}")
                docs = []

            for doc in docs:
                path = (doc.get("path") or "").strip()
                if not path or path in seen_paths:
                    continue

                category = (doc.get("category") or "").strip()
                tags = doc.get("tags") or []

                reason = self._categorize_indexed_doc(category, tags)
                if reason is None:
                    continue

                full_path = self._pages_path / path
                items.append(
                    PendingItem.of(path=path, reason=reason, mtime=_format_mtime(full_path))
                )
                seen_paths.add(path)

        # 2차: 인덱스에 없는 신규 파일
        try:
            disk_files = self._scan_disk_files()
        except OSError as e:
            logger.warning(f"Failed to scan disk: {e}")
            disk_files = []

        # 인덱싱된 경로 집합
        indexed_paths: set[str] = set()
        if self._vector.exists():
            try:
                indexed_paths = {(d.get("path") or "").strip() for d in self._vector.to_arrow_list()}
            except Exception:
                indexed_paths = set()

        for rel_path in disk_files:
            if rel_path in seen_paths or rel_path in indexed_paths:
                continue
            full_path = self._pages_path / rel_path
            items.append(
                PendingItem.of(
                    path=rel_path, reason="not_indexed", mtime=_format_mtime(full_path)
                )
            )
            seen_paths.add(rel_path)

        # 정렬: not_indexed → no_frontmatter → no_category, 같은 reason은 path 사전순
        reason_order = {"not_indexed": 0, "no_frontmatter": 1, "no_category": 2}
        items.sort(key=lambda it: (reason_order.get(it.reason, 9), it.path))

        # 캐시 갱신
        self._cached_pending = items
        self._cached_at = self._clock()

        return items[:limit]

    def suggest_classification(self, path: str) -> ClassificationSuggestion:
        """단일 파일에 대한 카테고리/태그 추천.

        Args:
            path: 대상 파일 상대 경로

        Returns:
            ClassificationSuggestion (path가 존재하지 않으면 빈 제안)

        Raises:
            InvalidPathError: 경로 검증 실패
            DocumentNotFoundError: 파일이 디스크에도 인덱스에도 없음
        """
        normalized = validate_path(path, self._pages_path)

        full_path = self._pages_path / normalized
        if not full_path.exists():
            # 인덱스에는 있을 수 있음 (이동/삭제 직후)
            indexed = self._vector.find_by_path(normalized) if self._vector.exists() else None
            if not indexed:
                raise DocumentNotFoundError.of(normalized)
            content = ""
        else:
            try:
                content = full_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                logger.warning(f"Failed to read {full_path}: {e}")
                content = ""

        # 카테고리 후보: 1) 폴더 기반, 2) 유사 문서 투표
        category_candidates = self._compute_category_candidates(normalized)

        # 태그 후보: AutoTagger
        tagger = AutoTagger()
        tag_candidates = self._compute_tag_candidates(content, tagger)

        # 유사 문서 (참고용)
        similar_paths = self._compute_similar_paths(normalized)

        reasoning = self._build_reasoning(
            category_candidates, tag_candidates, similar_paths
        )

        return ClassificationSuggestion.of(
            path=normalized,
            category_candidates=category_candidates,
            tag_candidates=tag_candidates,
            similar_paths=similar_paths,
            reasoning=reasoning,
        )

    def invalidate(self) -> None:
        """캐시 무효화. ``wiki_reindex`` 후 호출."""
        self._cached_pending = None
        self._cached_at = 0.0

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _categorize_indexed_doc(
        self, category: str, tags: Any
    ) -> str | None:
        """인덱싱된 문서의 분류 부족 사유 반환. 분류 충분하면 None."""
        if not category or category == "uncategorized":
            # 카테고리 + 태그 둘 다 없으면 frontmatter 자체가 빈약
            if not tags:
                return "no_frontmatter"
            return "no_category"
        return None

    def _scan_disk_files(self) -> list[str]:
        """디스크에서 .md 파일 상대 경로 목록 (무시 패턴 적용)."""
        if not self._pages_path.exists():
            return []
        rel_paths: list[str] = []
        for md in self._pages_path.rglob("*.md"):
            if self._ignore_matcher.should_ignore(md):
                continue
            try:
                rel = md.relative_to(self._pages_path)
            except ValueError:
                continue
            rel_str = str(rel).replace("\\", "/")
            # frontmatter 누락 의심도 같이 잡힘 (인덱스에 없으므로 not_indexed)
            rel_paths.append(rel_str)
        return rel_paths

    def _compute_category_candidates(self, normalized_path: str) -> tuple[str, ...]:
        """카테고리 후보 계산.

        1) 폴더 기반: 경로 첫 컴포넌트가 카테고리면 1순위
        2) 유사 문서 투표: 이웃 문서들의 카테고리 빈도
        """
        candidates: list[str] = []

        listing = self._category_service.list_categories()
        active_cats = set(listing.categories)

        # 1) 경로 첫 컴포넌트
        first_component = normalized_path.split("/", 1)[0]
        if first_component and first_component != normalized_path:
            if first_component in active_cats:
                candidates.append(first_component)

        # 2) 유사 문서 투표
        try:
            similar_docs = self._document_service.get_similar(normalized_path, top_k=3)
        except Exception as e:
            logger.debug(f"get_similar failed: {e}")
            similar_docs = []

        votes: Counter[str] = Counter()
        for doc in similar_docs:
            cat = (getattr(doc, "category", "") or "").strip()
            if cat and cat != "uncategorized":
                votes[cat] += 1

        for name, _ in votes.most_common():
            if name not in candidates:
                candidates.append(name)

        # 3) 활성 카테고리 중 아직 후보에 없는 것을 보조로 제공 (최대 5개)
        for cat in listing.categories:
            if len(candidates) >= 5:
                break
            if cat not in candidates:
                candidates.append(cat)

        return tuple(candidates[:5])

    def _compute_tag_candidates(self, content: str, tagger: AutoTagger) -> tuple[str, ...]:
        """본문에서 태그 후보 추출 (기술 용어 우선)."""
        if not content:
            return ()

        technical = tagger.extract_technical_terms(content, top_n=5)
        general = tagger.extract_tags(content, top_n=5)

        merged: list[str] = []
        seen: set[str] = set()
        for term in [*technical, *general]:
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(term)
            if len(merged) >= 8:
                break
        return tuple(merged)

    def _compute_similar_paths(self, normalized_path: str) -> tuple[str, ...]:
        """유사 문서 경로 (참고용)."""
        try:
            similar = self._document_service.get_similar(normalized_path, top_k=5)
        except Exception:
            return ()
        return tuple(getattr(doc, "path", "") for doc in similar if getattr(doc, "path", ""))

    def _build_reasoning(
        self,
        category_candidates: tuple[str, ...],
        tag_candidates: tuple[str, ...],
        similar_paths: tuple[str, ...],
    ) -> str:
        """추천 근거 문자열 구성."""
        parts: list[str] = []
        if category_candidates:
            parts.append(f"카테고리 후보: {', '.join(category_candidates)}")
        if tag_candidates:
            parts.append(f"태그 후보: {', '.join(tag_candidates[:5])}")
        if similar_paths:
            parts.append(f"유사 문서 {len(similar_paths)}건 참조")
        if not parts:
            return "추천 근거 부족 (인덱스가 비어있거나 본문 없음)"
        return " | ".join(parts)

    def _is_cache_valid(self) -> bool:
        if self._cached_pending is None:
            return False
        return (self._clock() - self._cached_at) < LISTING_TTL_SECONDS
