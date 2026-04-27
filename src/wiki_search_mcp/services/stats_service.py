"""Stats service.

Wiki 통계 유스케이스를 담당합니다.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from wiki_search_mcp.core.models import WikiStats

if TYPE_CHECKING:
    from wiki_search_mcp.core.protocols import MetaRepository, VectorRepository


class StatsService:
    """Wiki 통계 유스케이스 담당."""

    def __init__(
        self,
        vector_repository: "VectorRepository",
        meta_repository: "MetaRepository",
    ):
        """StatsService 초기화.

        Args:
            vector_repository: 벡터 저장소
            meta_repository: 메타데이터 저장소
        """
        self._vector = vector_repository
        self._meta = meta_repository

    def get_stats(self) -> WikiStats:
        """Wiki 통계 조회.

        Returns:
            WikiStats 객체
        """
        if not self._vector.exists():
            return WikiStats.create(
                total_pages=0,
                by_category={},
                by_state={},
                by_confidence={},
                last_indexed=None,
            )

        all_docs = self._vector.to_arrow_list()

        # 카테고리별 집계
        by_category = dict(Counter(doc["category"] for doc in all_docs))

        # state별 집계
        by_state = dict(Counter(doc.get("state", "stable") for doc in all_docs))

        # confidence level별 집계
        by_confidence = dict(
            Counter(doc.get("confidence_level", "medium") for doc in all_docs)
        )

        return WikiStats.create(
            total_pages=len(all_docs),
            by_category=by_category,
            by_state=by_state,
            by_confidence=by_confidence,
            last_indexed=self._meta.get_last_indexed(),
        )
