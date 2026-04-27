"""Search service.

검색 유스케이스를 담당합니다.
벡터, 키워드, 하이브리드 검색을 지원합니다.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from wiki_search_mcp.core.config import MAX_RELATED_DOCS, RRF_K, SEARCH_MULTIPLIER
from wiki_search_mcp.core.logging import get_logger
from wiki_search_mcp.core.models import (
    Document,
    SearchFilters,
    SearchResponse,
    SearchResult,
)
from wiki_search_mcp.services.filters import passes_filters

if TYPE_CHECKING:
    from wiki_search_mcp.core.protocols import (
        EmbeddingProvider,
        GraphRepository,
        KeywordRepository,
        QueryCache,
        QueryExpanderProtocol,
        VectorRepository,
    )


logger = get_logger("search_service")


class SearchService:
    """검색 유스케이스 담당.

    벡터, 키워드, 하이브리드 검색을 지원합니다.
    Protocol 기반 DI로 Repository를 주입받습니다.
    """

    def __init__(
        self,
        vector_repository: "VectorRepository",
        keyword_repository: "KeywordRepository",
        graph_repository: "GraphRepository",
        embedder: "EmbeddingProvider",
        query_cache: "QueryCache",
        expander: "QueryExpanderProtocol | None" = None,
    ):
        """SearchService 초기화.

        Args:
            vector_repository: 벡터 저장소
            keyword_repository: 키워드 검색 저장소
            graph_repository: 그래프 저장소
            embedder: 임베딩 제공자
            query_cache: 쿼리 캐시
            expander: 쿼리 확장기 (선택적)
        """
        self._vector = vector_repository
        self._keyword = keyword_repository
        self._graph = graph_repository
        self._embedder = embedder
        self._cache = query_cache
        self._expander = expander

    def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "hybrid",
        vector_weight: float = 0.7,
        filters: SearchFilters | None = None,
        expand_graph: bool = True,
        expand_query: bool = False,
        sort_by: str = "similarity",
        sort_order: str = "desc",
    ) -> SearchResponse:
        """검색 실행.

        Args:
            query: 검색 질의
            top_k: 반환할 결과 수
            mode: 검색 모드 ("hybrid", "vector", "keyword")
            vector_weight: 하이브리드 검색 시 벡터 가중치
            filters: 검색 필터
            expand_graph: 그래프 확장 여부
            expand_query: 쿼리 확장 여부
            sort_by: 정렬 기준
            sort_order: 정렬 순서

        Returns:
            SearchResponse 객체
        """
        start_time = time.perf_counter()
        logger.debug(f"Search request: query={query!r}, mode={mode}, top_k={top_k}")

        # 인덱스 존재 확인
        if not self._vector.exists():
            return SearchResponse.of(
                results=[],
                total_pages=0,
                query=query,
                mode=mode,
                error="Index not found. Run wiki_reindex() first.",
            )

        # 기본 필터
        if filters is None:
            filters = SearchFilters.of()

        # 쿼리 확장
        queries_to_search = [query]
        if expand_query and self._expander is not None:
            queries_to_search = self._expander.expand(query)

        # 검색 실행
        raw_results = self._execute_search(queries_to_search, top_k, mode, vector_weight)

        # 결과 포맷팅 및 필터링
        formatted = self._format_and_filter(raw_results, filters, expand_graph)

        # 정렬
        formatted = self._apply_sort(formatted, sort_by, sort_order)

        # top_k 제한
        formatted = formatted[:top_k]

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"Search completed: query={query!r}, results={len(formatted)}, "
            f"mode={mode}, duration={duration_ms:.1f}ms"
        )

        return SearchResponse.of(
            results=formatted,
            total_pages=self._graph.node_count,
            query=query,
            mode=mode,
        )

    def _execute_search(
        self,
        queries: list[str],
        top_k: int,
        mode: str,
        vector_weight: float,
    ) -> list[dict[str, Any]]:
        """검색 모드별 실행.

        검색 모드(vector, keyword, hybrid)에 따라 적절한 검색 메서드를 호출합니다.
        SEARCH_MULTIPLIER를 적용하여 필터링 전 충분한 후보를 확보합니다.

        Args:
            queries: 검색 쿼리 리스트 (쿼리 확장 시 여러 개)
            top_k: 최종 반환할 결과 수
            mode: 검색 모드 ("vector", "keyword", "hybrid")
            vector_weight: 하이브리드 검색 시 벡터 가중치 (0.0-1.0)

        Returns:
            검색 결과 raw dict 리스트 (포맷팅 전)
        """
        limit = top_k * SEARCH_MULTIPLIER

        if mode == "keyword":
            return self._search_keyword(queries, limit)
        elif mode == "hybrid" and self._keyword.exists():
            return self._search_hybrid(queries, limit, vector_weight)
        else:
            return self._search_vector(queries, limit)

    def _search_vector(
        self, queries: list[str], limit: int
    ) -> list[dict[str, Any]]:
        """벡터 유사도 검색 수행.

        쿼리를 임베딩 벡터로 변환한 후 벡터 저장소에서 유사도 검색을 수행합니다.
        여러 쿼리(확장된 경우)의 결과를 중복 제거하여 병합합니다.

        Args:
            queries: 검색 쿼리 리스트
            limit: 최대 결과 수

        Returns:
            벡터 검색 결과 리스트 (path, vector, _distance 등 포함)
        """
        all_results = []
        seen = set()

        for q in queries:
            # 캐시된 임베딩 사용
            query_vec = list(self._cache.get_or_compute(q, self._embedder.encode_as_tuple))
            results = self._vector.search(query_vec, limit)

            for r in results:
                if r["path"] not in seen:
                    seen.add(r["path"])
                    all_results.append(r)

        return all_results[:limit]

    def _search_keyword(
        self, queries: list[str], limit: int
    ) -> list[dict[str, Any]]:
        """BM25 키워드 검색 수행.

        키워드 저장소(BM25 인덱스)에서 텍스트 매칭 검색을 수행합니다.
        검색된 경로로 벡터 저장소에서 전체 문서 정보를 조회합니다.

        Args:
            queries: 검색 쿼리 리스트
            limit: 최대 결과 수

        Returns:
            키워드 검색 결과 리스트 (벡터 저장소의 문서 정보)

        Note:
            키워드 검색 결과에는 _distance가 없으므로 유사도 점수가 0으로 처리됩니다.
        """
        all_paths = []
        seen = set()

        for q in queries:
            results = self._keyword.search(q, limit)
            for path, _ in results:
                if path not in seen:
                    seen.add(path)
                    all_paths.append(path)

        # 경로로 문서 조회
        raw_results = []
        for path in all_paths[:limit]:
            doc = self._vector.find_by_path(path)
            if doc:
                raw_results.append(doc)

        return raw_results

    def _search_hybrid(
        self, queries: list[str], limit: int, vector_weight: float
    ) -> list[dict[str, Any]]:
        """Reciprocal Rank Fusion (RRF) 알고리즘으로 하이브리드 검색 수행.

        벡터 검색과 키워드(BM25) 검색 결과를 RRF 알고리즘으로 통합합니다.
        의미적 유사성과 키워드 매칭을 모두 고려한 결과를 반환합니다.

        RRF 점수 계산:
            RRF_score = Σ weight / (k + rank_i)

        여기서:
            - k = 60 (표준 RRF 상수, config.RRF_K)
            - rank_i = 각 검색 방식에서의 순위 (0-indexed)
            - weight = 각 검색 방식의 가중치
                - 벡터: vector_weight (기본 0.7)
                - 키워드: 1 - vector_weight (기본 0.3)

        RRF의 장점:
            - 정규화 불필요: 순위 기반이므로 점수 스케일 차이 무관
            - 이상치 강건성: 극단적인 점수에 영향받지 않음
            - 하이퍼파라미터 단순: k=60이 대부분의 경우에 적합

        Args:
            queries: 검색 쿼리 리스트 (쿼리 확장 시 여러 개)
            limit: 반환할 결과 수
            vector_weight: 벡터 검색 가중치 (0.0-1.0, 기본 0.7)

        Returns:
            RRF 점수로 정렬된 검색 결과 리스트

        Reference:
            Cormack, G. V., Clarke, C. L., & Buettcher, S. (2009).
            "Reciprocal rank fusion outperforms condorcet and individual
            rank learning methods." SIGIR '09.
        """
        # 벡터 검색 결과
        vector_results = []
        for q in queries:
            query_vec = list(self._cache.get_or_compute(q, self._embedder.encode_as_tuple))
            vector_results.extend(self._vector.search(query_vec, limit))

        # 키워드 검색 결과
        keyword_results = []
        for q in queries:
            keyword_results.extend(self._keyword.search(q, limit))

        # RRF 점수 계산
        scores: dict[str, float] = {}

        for rank, r in enumerate(vector_results):
            path = r["path"]
            scores[path] = scores.get(path, 0) + vector_weight / (rank + RRF_K)

        for rank, (path, _) in enumerate(keyword_results):
            scores[path] = scores.get(path, 0) + (1 - vector_weight) / (rank + RRF_K)

        # 점수순 정렬
        sorted_paths = sorted(scores.keys(), key=lambda p: scores[p], reverse=True)

        # 경로로 문서 조회
        raw_results = []
        for path in sorted_paths[:limit]:
            doc = self._vector.find_by_path(path)
            if doc:
                raw_results.append(doc)

        return raw_results

    def _format_and_filter(
        self,
        raw_results: list[dict[str, Any]],
        filters: SearchFilters,
        expand_graph: bool,
    ) -> list[SearchResult]:
        """검색 결과 포맷팅 및 필터링.

        raw dict 형태의 검색 결과를 SearchResult 모델로 변환합니다.
        필터 조건에 맞지 않는 결과는 제외하고, 중복을 제거합니다.
        그래프 확장이 활성화되면 관련 문서도 함께 조회합니다.

        Args:
            raw_results: 검색 결과 raw dict 리스트
            filters: 검색 필터 (category, tags, states, confidence_min 등)
            expand_graph: True면 wikilink 기반 관련 문서 포함

        Returns:
            SearchResult 객체 리스트 (document, similarity, related, warning 포함)

        Note:
            - L2 거리는 similarity = max(0, 1 - distance/2)로 변환됩니다.
            - deprecated 상태 문서에는 경고 메시지가 추가됩니다.
        """
        formatted = []
        seen_ids: set[str] = set()

        for r in raw_results:
            # 필터 적용 (filters.py 사용)
            if not passes_filters(r, filters):
                continue

            # 중복 방지
            if r["path"] in seen_ids:
                continue

            # Document 생성
            doc = Document.from_dict(r)

            # 유사도 계산 (L2 거리 → 유사도)
            distance = r.get("_distance", 0)
            similarity = max(0, round(1 - distance / 2, 3))

            # 그래프 확장
            related: list[str] = []
            if expand_graph:
                related = self._graph.get_neighbors(r["path"], max_depth=2)[:MAX_RELATED_DOCS]

            # 경고 추가
            warning = None
            if doc.state == "deprecated":
                warning = "This document is deprecated and may be outdated."

            result = SearchResult.of(
                document=doc,
                similarity=similarity,
                related=related,
                warning=warning,
            )
            formatted.append(result)
            seen_ids.add(r["path"])

        return formatted

    def _apply_sort(
        self,
        results: list[SearchResult],
        sort_by: str,
        sort_order: str,
    ) -> list[SearchResult]:
        """결과 정렬 적용.

        Args:
            results: 정렬할 검색 결과 리스트
            sort_by: 정렬 기준 ("similarity", "confidence", "updated", "title")
            sort_order: 정렬 순서 ("asc", "desc")

        Returns:
            정렬된 결과 리스트

        Note:
            - similarity: 벡터 유사도 (기본값, 이미 정렬되어 있음)
            - confidence: 문서 신뢰도 점수
            - updated: 최근 수정일
            - title: 제목 알파벳순
        """
        reverse = sort_order == "desc"

        if sort_by == "confidence":
            return sorted(
                results,
                key=lambda x: x.document.confidence.score,
                reverse=reverse,
            )
        elif sort_by == "updated":
            return sorted(
                results,
                key=lambda x: x.document.updated or "",
                reverse=reverse,
            )
        elif sort_by == "title":
            return sorted(
                results,
                key=lambda x: x.document.title,
                reverse=reverse,
            )
        # similarity는 이미 정렬되어 있음
        elif sort_by == "similarity" and not reverse:
            return list(reversed(results))

        return results
