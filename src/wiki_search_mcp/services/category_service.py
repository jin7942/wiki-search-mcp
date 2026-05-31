from __future__ import annotations

"""Category service.

폴더 구조 자동 감지를 통해 카테고리 목록을 제공합니다.
사용자가 미리 만들어 둔 디렉토리들이 곧 카테고리입니다.

폴백: 디렉토리가 1개 이하면 ``mode="empty"``로 응답하여
Claude에게 AI 기반 제안을 트리거하라고 알립니다.
"""

import logging
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from wiki_search_mcp.core.config import (
    CATEGORY_FOLDER_THRESHOLD,
    LISTING_TTL_SECONDS,
    is_staging_folder,
)
from wiki_search_mcp.core.models import CategoryListing
from wiki_search_mcp.services.tagger_service import AutoTagger

if TYPE_CHECKING:
    from wiki_search_mcp.core.protocols import VectorRepository
    from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher

logger = logging.getLogger(__name__)


class CategoryService:
    """폴더 자동 감지 기반 카테고리 제공자.

    캐싱 정책:
    - 60초 TTL (``LISTING_TTL_SECONDS``)로 ``detect_from_folders`` 결과 보관
    - ``invalidate()`` 호출 또는 reindex 시 무효화

    Attributes:
        pages_path: 카테고리 후보를 탐색할 페이지 루트
        ignore_matcher: 디렉토리 필터링용 매처
        vector_repository: 인덱스 기반 후보 추출용 (선택)
    """

    def __init__(
        self,
        pages_path: Path,
        ignore_matcher: "IgnoreMatcher",
        vector_repository: "VectorRepository | None" = None,
        clock: callable = time.monotonic,
    ):
        """CategoryService 초기화.

        Args:
            pages_path: 카테고리 후보를 탐색할 디렉토리 루트
            ignore_matcher: 무시 패턴 매처
            vector_repository: 인덱스 기반 카테고리 빈도 분석용 (옵션)
            clock: 캐시 만료 판정용 시계 (테스트 주입 가능)
        """
        self._pages_path = pages_path
        self._ignore_matcher = ignore_matcher
        self._vector = vector_repository
        self._clock = clock
        self._cached_listing: CategoryListing | None = None
        self._cached_at: float = 0.0

    def list_categories(self, force_refresh: bool = False) -> CategoryListing:
        """현재 활성 카테고리 목록 반환.

        TTL 캐시 우선, 만료 시 재감지.

        Args:
            force_refresh: True면 캐시 무시

        Returns:
            CategoryListing 객체
        """
        if not force_refresh and self._is_cache_valid():
            return self._cached_listing  # type: ignore[return-value]

        listing = self.detect_from_folders()
        self._cached_listing = listing
        self._cached_at = self._clock()
        return listing

    def detect_from_folders(self) -> CategoryListing:
        """pages_path 1depth 디렉토리에서 카테고리 추출.

        - 디렉토리 ≥ ``CATEGORY_FOLDER_THRESHOLD`` → ``mode="folder"``
        - 그 외 → ``mode="empty"``

        Returns:
            CategoryListing 객체
        """
        detected_at = datetime.now(timezone.utc).isoformat()

        if not self._pages_path.exists() or not self._pages_path.is_dir():
            return CategoryListing.of(mode="empty", categories=[], detected_at=detected_at)

        try:
            entries = list(self._pages_path.iterdir())
        except OSError as e:
            logger.warning(f"Failed to list pages_path {self._pages_path}: {e}")
            return CategoryListing.of(mode="empty", categories=[], detected_at=detected_at)

        directories: list[str] = []
        staging: list[str] = []
        for entry in entries:
            if not entry.is_dir():
                continue
            if self._ignore_matcher.should_ignore(entry):
                continue
            if is_staging_folder(entry.name):
                staging.append(entry.name)
                continue
            directories.append(entry.name)

        directories.sort()
        staging.sort()

        # mode는 staging을 제외한 일반 카테고리 수만으로 판정.
        # staging만 있는 경우는 "사용 가능한 카테고리 없음" 으로 본다.
        if len(directories) >= CATEGORY_FOLDER_THRESHOLD:
            return CategoryListing.of(
                mode="folder",
                categories=directories,
                detected_at=detected_at,
                staging_folders=staging,
            )
        return CategoryListing.of(
            mode="empty",
            categories=[],
            detected_at=detected_at,
            staging_folders=staging,
        )

    def suggest_categories(self, top_k: int = 10) -> list[dict]:
        """기존 인덱스를 분석하여 카테고리 후보 제시.

        ``mode="empty"``인 사용자에게 카테고리를 제안하기 위해 사용합니다.

        - 인덱스에 있는 모든 문서의 ``category`` 필드 빈도 집계
        - 본문에서 ``AutoTagger``로 추출한 키워드 빈도 집계
        - 두 결과를 합산하여 후보 반환

        Args:
            top_k: 반환할 후보 수

        Returns:
            [{"name": str, "doc_count": int, "keywords": list[str]}, ...]
        """
        if self._vector is None or not self._vector.exists():
            return []

        docs = self._vector.to_arrow_list()
        if not docs:
            return []

        # 카테고리 빈도 (이미 분류된 항목)
        cat_counter: Counter[str] = Counter()
        for doc in docs:
            cat = (doc.get("category") or "").strip()
            if cat and cat != "uncategorized":
                cat_counter[cat] += 1

        # 본문 키워드 (전체 합쳐서 분석)
        tagger = AutoTagger()
        combined_text = " ".join(
            (doc.get("summary") or "") + " " + (doc.get("title") or "")
            for doc in docs
        )
        keywords = tagger.extract_tags(combined_text, top_n=top_k * 3)

        suggestions: list[dict] = []

        # 1순위: 기존 카테고리 빈도
        for name, count in cat_counter.most_common(top_k):
            related = [k for k in keywords if k.lower() != name.lower()][:5]
            suggestions.append({"name": name, "doc_count": count, "keywords": related})

        # 2순위: 카테고리가 부족하면 키워드를 후보로
        remaining = top_k - len(suggestions)
        if remaining > 0:
            seen = {s["name"].lower() for s in suggestions}
            for kw in keywords:
                if len(suggestions) >= top_k:
                    break
                if kw.lower() in seen:
                    continue
                suggestions.append({"name": kw, "doc_count": 0, "keywords": []})
                seen.add(kw.lower())

        return suggestions

    def list_subfolders(self) -> dict[str, tuple[str, ...]]:
        """각 활성 카테고리 1-depth 서브폴더 이름 목록.

        분류기가 평탄(``<category>/<basename>``) 배치 대신 적절한 프로젝트 폴더로
        라우팅할 수 있도록 LLM 프롬프트의 힌트로 사용한다. staging/ignore 폴더는 제외.

        Returns:
            ``{category: (sub1, sub2, ...)}`` — 카테고리에 서브폴더가 없으면 키 자체가
            없을 수 있다. 정렬은 카테고리 사전순, 서브폴더 사전순.
        """
        result: dict[str, tuple[str, ...]] = {}
        listing = self.list_categories()
        for cat in listing.categories:
            cat_dir = self._pages_path / cat
            if not cat_dir.is_dir():
                continue
            subs: list[str] = []
            try:
                for entry in cat_dir.iterdir():
                    if not entry.is_dir():
                        continue
                    if self._ignore_matcher.should_ignore(entry):
                        continue
                    if is_staging_folder(entry.name):
                        continue
                    subs.append(entry.name)
            except OSError as e:
                logger.debug("list_subfolders(%s) failed: %s", cat, e)
                continue
            if subs:
                subs.sort()
                result[cat] = tuple(subs)
        return result

    def invalidate(self) -> None:
        """캐시 무효화. ``wiki_reindex`` 후 호출."""
        self._cached_listing = None
        self._cached_at = 0.0

    def _is_cache_valid(self) -> bool:
        """캐시 유효성 판정 (TTL)."""
        if self._cached_listing is None:
            return False
        return (self._clock() - self._cached_at) < LISTING_TTL_SECONDS
