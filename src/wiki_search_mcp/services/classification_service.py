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

from wiki_search_mcp.core.config import LISTING_TTL_SECONDS, is_staging_folder
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

        # 인덱스를 한 번만 읽어 1차/2차에서 공유(과거엔 to_arrow_list 2회 호출).
        indexed_docs = self._read_indexed_docs()
        indexed_paths = {(d.get("path") or "").strip() for d in indexed_docs}

        seen_paths: set[str] = set()
        items: list[PendingItem] = []
        items.extend(self._pending_from_index(indexed_docs, seen_paths))
        items.extend(self._pending_from_disk(indexed_paths, seen_paths))

        self._sort_pending(items)

        # 캐시 갱신
        self._cached_pending = items
        self._cached_at = self._clock()

        return items[:limit]

    def _read_indexed_docs(self) -> list[dict]:
        """인덱스 문서 목록(실패/미존재 시 빈 리스트)."""
        if not self._vector.exists():
            return []
        try:
            return self._vector.to_arrow_list()
        except Exception as e:
            logger.warning(f"Failed to read vector index: {e}")
            return []

    def _pending_from_index(
        self, indexed_docs: list[dict], seen_paths: set[str]
    ) -> list[PendingItem]:
        """1차: 인덱스에서 분류 부족 문서 추출.

        staging 폴더 파일은 frontmatter 상태와 무관하게 항상 pending(daemon 이
        카테고리 폴더로 다시 이동시켜야 함). 그 외엔 category/tags 부족만.
        ``seen_paths`` 에 처리한 경로를 누적해 2차와 중복을 막는다.
        """
        items: list[PendingItem] = []
        for doc in indexed_docs:
            path = (doc.get("path") or "").strip()
            if not path or path in seen_paths:
                continue

            first = path.split("/", 1)[0] if "/" in path else ""
            if first and is_staging_folder(first):
                reason: str | None = "in_staging"
            else:
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
        return items

    def _pending_from_disk(
        self, indexed_paths: set[str], seen_paths: set[str]
    ) -> list[PendingItem]:
        """2차: 인덱스에 없는 신규 디스크 파일(+ staging 은 항상 포함)."""
        try:
            disk_files = self._scan_disk_files()
        except OSError as e:
            logger.warning(f"Failed to scan disk: {e}")
            return []

        items: list[PendingItem] = []
        for rel_path in disk_files:
            if rel_path in seen_paths:
                continue
            first = rel_path.split("/", 1)[0] if "/" in rel_path else ""
            is_staging = bool(first) and is_staging_folder(first)
            # staging 파일은 인덱스 유무와 무관하게 항상 노출.
            if not is_staging and rel_path in indexed_paths:
                continue
            full_path = self._pages_path / rel_path
            reason = "in_staging" if is_staging else "not_indexed"
            items.append(
                PendingItem.of(path=rel_path, reason=reason, mtime=_format_mtime(full_path))
            )
            seen_paths.add(rel_path)
        return items

    @staticmethod
    def _sort_pending(items: list[PendingItem]) -> None:
        """in_staging → not_indexed → no_frontmatter → no_category, 동일 reason 은 path 순."""
        reason_order = {
            "in_staging": 0,
            "not_indexed": 1,
            "no_frontmatter": 2,
            "no_category": 3,
        }
        items.sort(key=lambda it: (reason_order.get(it.reason, 9), it.path))

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
        content = self._load_content(normalized)

        # 유사 문서를 한 번만 조회해 카테고리 투표와 유사경로 표시에 공유한다.
        # (과거엔 _compute_category_candidates 와 _compute_similar_paths 가
        # 각각 get_similar 를 호출해 동일 검색을 2번 수행했다.)
        similar_docs = self._get_similar_docs(normalized, top_k=5)

        category_candidates = self._compute_category_candidates(
            normalized, similar_docs
        )
        tag_candidates = self._compute_tag_candidates(content, AutoTagger())
        similar_paths = tuple(
            getattr(doc, "path", "") for doc in similar_docs if getattr(doc, "path", "")
        )

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

    def _load_content(self, normalized_path: str) -> str:
        """분류용 본문 로드.

        파일이 디스크에 있으면 읽고, 없으면 인덱스 존재 여부만 확인한다
        (이동/삭제 직후 인덱스에만 남은 경우 허용). 둘 다 없으면 예외.

        Raises:
            DocumentNotFoundError: 디스크에도 인덱스에도 없음.
        """
        full_path = self._pages_path / normalized_path
        if not full_path.exists():
            indexed = (
                self._vector.find_by_path(normalized_path)
                if self._vector.exists()
                else None
            )
            if not indexed:
                raise DocumentNotFoundError.of(normalized_path)
            return ""
        try:
            return full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"Failed to read {full_path}: {e}")
            return ""

    def _get_similar_docs(self, normalized_path: str, top_k: int) -> list:
        """유사 문서 조회(실패 시 빈 리스트). 카테고리 투표/유사경로에 공유."""
        try:
            return self._document_service.get_similar(normalized_path, top_k=top_k)
        except Exception as e:
            logger.debug(f"get_similar failed: {e}")
            return []

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

    def _compute_category_candidates(
        self, normalized_path: str, similar_docs: list
    ) -> tuple[str, ...]:
        """카테고리 후보 계산.

        1) 폴더 기반: 경로 첫 컴포넌트가 카테고리면 1순위
        2) 유사 문서 투표: 이웃 문서들의 카테고리 빈도 (상위 3개만)
        3) 활성 카테고리 보조 채움

        Args:
            normalized_path: 정규화된 대상 경로.
            similar_docs: 호출자가 한 번 조회해 공유하는 유사 문서 리스트.
                투표에는 상위 3개만 사용한다(과거 top_k=3 동작 보존).
        """
        candidates: list[str] = []

        listing = self._category_service.list_categories()
        active_cats = set(listing.categories)

        # 1) 경로 첫 컴포넌트
        first_component = normalized_path.split("/", 1)[0]
        if first_component and first_component != normalized_path:
            if first_component in active_cats:
                candidates.append(first_component)

        # 2) 유사 문서 투표 (상위 3개)
        votes: Counter[str] = Counter()
        for doc in similar_docs[:3]:
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
