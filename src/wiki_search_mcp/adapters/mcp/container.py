"""Service container for dependency injection.

서비스 의존성을 관리하는 DI 컨테이너입니다.
Lazy Loading으로 필요할 때만 인스턴스를 생성합니다.

사용 예:
    from wiki_search_mcp.adapters.mcp import ServiceContainer

    container = ServiceContainer("/wiki")
    results = container.search_service.search("query")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from wiki_search_mcp.core.config import WikiConfig
from wiki_search_mcp.core.protocols import (
    EmbeddingProvider,
    GraphRepository,
    KeywordRepository,
    MetaRepository,
    QueryCache,
    VectorRepository,
)
from wiki_search_mcp.core.utils import resolve_pages_path

logger = logging.getLogger(__name__)


class ServiceContainer:
    """서비스 의존성 관리 (DI Container).

    Lazy Loading으로 필요할 때만 인스턴스 생성.
    싱글톤 패턴으로 동일 서비스 재사용.

    Attributes:
        _wiki_path: wiki 루트 경로
        _model_name: 임베딩 모델 이름
        _cache: 인스턴스 캐시
    """

    def __init__(
        self,
        wiki_path: str,
        model_name: str | None = None,
        ignore_patterns: tuple[str, ...] = (),
    ):
        """ServiceContainer 초기화.

        Args:
            wiki_path: wiki 루트 경로
            model_name: 임베딩 모델 이름 (선택적)
            ignore_patterns: CLI ``--ignore``로 전달된 추가 무시 패턴
        """
        self._wiki_path = Path(wiki_path)
        self._wiki_config = WikiConfig.load(self._wiki_path)
        # 모델 이름: 인자 > 기본값
        self._model_name = model_name or self._wiki_config.embedding_model
        self._ignore_patterns = tuple(ignore_patterns)
        self._cache: dict[str, Any] = {}

    # ==========================================================================
    # Infrastructure (Lazy Singleton)
    # ==========================================================================

    @property
    def embedder(self) -> EmbeddingProvider:
        """임베딩 제공자."""
        if "embedder" not in self._cache:
            from wiki_search_mcp.infrastructure.embedding import Embedder

            instance = Embedder(self._model_name)
            self._verify_protocol(instance, EmbeddingProvider, "embedder")
            self._cache["embedder"] = instance
        return self._cache["embedder"]

    @property
    def vector_repository(self) -> VectorRepository:
        """벡터 저장소."""
        if "vector_repo" not in self._cache:
            from wiki_search_mcp.infrastructure.storage import LanceVectorStore

            instance = LanceVectorStore(self._wiki_path / ".vectordb")
            self._verify_protocol(instance, VectorRepository, "vector_repository")
            self._cache["vector_repo"] = instance
        return self._cache["vector_repo"]

    @property
    def keyword_repository(self) -> KeywordRepository:
        """키워드 검색 저장소."""
        if "keyword_repo" not in self._cache:
            from wiki_search_mcp.infrastructure.storage import BM25IndexStore

            instance = BM25IndexStore(self._wiki_path / ".vectordb")
            self._verify_protocol(instance, KeywordRepository, "keyword_repository")
            self._cache["keyword_repo"] = instance
        return self._cache["keyword_repo"]

    @property
    def graph_repository(self) -> GraphRepository:
        """그래프 저장소."""
        if "graph_repo" not in self._cache:
            from wiki_search_mcp.infrastructure.storage import JsonGraphStore

            instance = JsonGraphStore(self._wiki_path / ".vectordb")
            self._verify_protocol(instance, GraphRepository, "graph_repository")
            self._cache["graph_repo"] = instance
        return self._cache["graph_repo"]

    @property
    def meta_repository(self) -> MetaRepository:
        """메타데이터 저장소."""
        if "meta_repo" not in self._cache:
            from wiki_search_mcp.infrastructure.storage import JsonMetaStore

            instance = JsonMetaStore(self._wiki_path / ".vectordb")
            self._verify_protocol(instance, MetaRepository, "meta_repository")
            self._cache["meta_repo"] = instance
        return self._cache["meta_repo"]

    @property
    def query_cache(self) -> QueryCache:
        """쿼리 캐시."""
        if "query_cache" not in self._cache:
            from wiki_search_mcp.infrastructure.cache import LRUQueryCache

            instance = LRUQueryCache()
            self._verify_protocol(instance, QueryCache, "query_cache")
            self._cache["query_cache"] = instance
        return self._cache["query_cache"]

    @property
    def ignore_matcher(self):
        """무시 패턴 매처 (dot-prefix + .gitignore + CLI ``--ignore``)."""
        if "ignore_matcher" not in self._cache:
            from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher

            self._cache["ignore_matcher"] = IgnoreMatcher.from_wiki(
                self._wiki_path,
                extra_patterns=self._ignore_patterns,
            )
        return self._cache["ignore_matcher"]

    def _verify_protocol(self, instance: Any, protocol: type, name: str) -> None:
        """Protocol 구현 검증.

        @runtime_checkable Protocol을 사용하여 구현체 검증.
        검증 실패 시 TypeError 발생.

        Args:
            instance: 검증할 인스턴스
            protocol: 검증할 Protocol 타입
            name: 로깅용 이름

        Raises:
            TypeError: Protocol 미구현 시
        """
        if not isinstance(instance, protocol):
            error_msg = f"{name} must implement {protocol.__name__}"
            logger.error(error_msg)
            raise TypeError(error_msg)

    # ==========================================================================
    # Services (Lazy Singleton)
    # ==========================================================================

    @property
    def search_service(self):
        """검색 서비스."""
        if "search_svc" not in self._cache:
            from wiki_search_mcp.services import SearchService

            self._cache["search_svc"] = SearchService(
                vector_repository=self.vector_repository,
                keyword_repository=self.keyword_repository,
                graph_repository=self.graph_repository,
                embedder=self.embedder,
                query_cache=self.query_cache,
            )
        return self._cache["search_svc"]

    @property
    def document_service(self):
        """문서 서비스."""
        if "document_svc" not in self._cache:
            from wiki_search_mcp.services import DocumentService

            self._cache["document_svc"] = DocumentService(
                vector_repository=self.vector_repository,
                pages_path=resolve_pages_path(self._wiki_path),
                embedder=self.embedder,
            )
        return self._cache["document_svc"]

    @property
    def graph_service(self):
        """그래프 서비스."""
        if "graph_svc" not in self._cache:
            from wiki_search_mcp.services import GraphService

            self._cache["graph_svc"] = GraphService(
                graph_repository=self.graph_repository,
                vector_repository=self.vector_repository,
            )
        return self._cache["graph_svc"]

    @property
    def validation_service(self):
        """검증 서비스."""
        if "validation_svc" not in self._cache:
            from wiki_search_mcp.services import ValidationService

            self._cache["validation_svc"] = ValidationService(
                vector_repository=self.vector_repository,
                graph_repository=self.graph_repository,
            )
        return self._cache["validation_svc"]

    @property
    def stats_service(self):
        """통계 서비스."""
        if "stats_svc" not in self._cache:
            from wiki_search_mcp.services import StatsService

            self._cache["stats_svc"] = StatsService(
                vector_repository=self.vector_repository,
                meta_repository=self.meta_repository,
            )
        return self._cache["stats_svc"]

    @property
    def category_service(self):
        """카테고리 서비스 (폴더 자동 감지)."""
        if "category_svc" not in self._cache:
            from wiki_search_mcp.services import CategoryService

            self._cache["category_svc"] = CategoryService(
                pages_path=self.pages_path,
                ignore_matcher=self.ignore_matcher,
                vector_repository=self.vector_repository,
            )
        return self._cache["category_svc"]

    @property
    def classification_service(self):
        """분류 추천 서비스 (pending 감지 + 카테고리/태그 추천)."""
        if "classification_svc" not in self._cache:
            from wiki_search_mcp.services import ClassificationService

            self._cache["classification_svc"] = ClassificationService(
                pages_path=self.pages_path,
                vector_repository=self.vector_repository,
                document_service=self.document_service,
                category_service=self.category_service,
                ignore_matcher=self.ignore_matcher,
            )
        return self._cache["classification_svc"]

    # ==========================================================================
    # Cache Management
    # ==========================================================================

    def invalidate_all(self) -> None:
        """모든 캐시 무효화.

        인덱스 갱신 후 호출하여 모든 캐시를 갱신합니다.
        """
        if "vector_repo" in self._cache:
            self._cache["vector_repo"].invalidate_cache()
        if "keyword_repo" in self._cache:
            self._cache["keyword_repo"].reload()
        if "graph_repo" in self._cache:
            self._cache["graph_repo"].reload()
        if "query_cache" in self._cache:
            self._cache["query_cache"].clear()
        if "category_svc" in self._cache:
            self._cache["category_svc"].invalidate()
        if "classification_svc" in self._cache:
            self._cache["classification_svc"].invalidate()

    @property
    def pages_path(self) -> Path:
        """pages 디렉토리 경로."""
        return resolve_pages_path(self._wiki_path)

    @property
    def db_path(self) -> Path:
        """vectordb 경로."""
        return self._wiki_path / ".vectordb"
