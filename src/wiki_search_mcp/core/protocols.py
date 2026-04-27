"""Repository and service protocols.

Protocol 기반 인터페이스 정의입니다.
구현체가 아닌 인터페이스에 의존하여 DIP(의존성 역전 원칙)를 적용합니다.

패턴 적용:
- Repository 패턴: 데이터 접근 추상화
- ISP (인터페이스 분리 원칙): 작은 단위로 인터페이스 분리

사용 예:
    def search(self, vector_repo: VectorRepository) -> list[dict]:
        # vector_repo는 LanceVectorStore 또는 MockVectorStore 가능
        return vector_repo.search(vector, limit=5)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .models import Document


# =============================================================================
# Embedding Protocols
# =============================================================================


@runtime_checkable
class EmbeddingProvider(Protocol):
    """임베딩 제공자 인터페이스.

    텍스트를 벡터로 변환하는 기능을 제공합니다.
    sentence-transformers 또는 다른 임베딩 모델로 구현 가능합니다.
    """

    def encode(self, text: str) -> list[float]:
        """단일 텍스트 임베딩.

        Args:
            text: 임베딩할 텍스트

        Returns:
            임베딩 벡터 (float 리스트)
        """
        ...

    def encode_batch(
        self, texts: list[str], show_progress: bool = False
    ) -> list[list[float]]:
        """배치 임베딩.

        Args:
            texts: 임베딩할 텍스트 리스트
            show_progress: 진행률 표시 여부

        Returns:
            임베딩 벡터 리스트
        """
        ...


# =============================================================================
# Repository Protocols (ISP: 인터페이스 분리)
# =============================================================================


@runtime_checkable
class VectorRepository(Protocol):
    """벡터 저장소 인터페이스 (Repository 패턴).

    LanceDB 또는 다른 벡터 DB로 구현 가능합니다.
    """

    def search(
        self, vector: list[float], limit: int, where: str | None = None
    ) -> list[dict[str, Any]]:
        """벡터 유사도 검색.

        Args:
            vector: 검색 벡터
            limit: 최대 결과 수
            where: 필터 조건 (SQL-like)

        Returns:
            검색 결과 리스트 (각 결과는 dict)
        """
        ...

    def find_by_path(self, path: str) -> dict[str, Any] | None:
        """경로로 문서 조회.

        Args:
            path: 문서 경로

        Returns:
            문서 정보 또는 None
        """
        ...

    def find_all(self, limit: int = 50) -> list[dict[str, Any]]:
        """전체 문서 조회.

        Args:
            limit: 최대 결과 수

        Returns:
            문서 리스트
        """
        ...

    def exists(self) -> bool:
        """인덱스 존재 여부.

        Returns:
            인덱스가 존재하면 True
        """
        ...

    def invalidate_cache(self) -> None:
        """캐시 무효화.

        reindex 후 호출하여 캐시를 갱신합니다.
        """
        ...

    def to_arrow_list(self) -> list[dict[str, Any]]:
        """전체 문서를 리스트로 반환.

        PyArrow를 사용하여 전체 문서를 조회합니다.
        pandas 의존성 없이 효율적으로 데이터를 가져옵니다.

        Returns:
            전체 문서 리스트
        """
        ...


@runtime_checkable
class KeywordRepository(Protocol):
    """키워드 검색 저장소 인터페이스.

    BM25 또는 다른 키워드 검색 엔진으로 구현 가능합니다.
    """

    def search(self, query: str, limit: int) -> list[tuple[str, float]]:
        """BM25 키워드 검색.

        Args:
            query: 검색 쿼리
            limit: 최대 결과 수

        Returns:
            (path, score) 튜플 리스트
        """
        ...

    def exists(self) -> bool:
        """인덱스 존재 여부.

        Returns:
            인덱스가 존재하면 True
        """
        ...

    def reload(self) -> None:
        """인덱스 리로드.

        인덱스 파일이 갱신된 후 호출합니다.
        """
        ...


@runtime_checkable
class GraphRepository(Protocol):
    """그래프 저장소 인터페이스.

    wikilink 그래프를 관리합니다.
    """

    def get_neighbors(self, path: str, max_depth: int = 2) -> list[str]:
        """이웃 노드 탐색 (BFS).

        Args:
            path: 출발 노드 경로
            max_depth: 최대 탐색 깊이

        Returns:
            이웃 노드 경로 리스트 (거리순)
        """
        ...

    def get_backlinks(self, path: str) -> list[str]:
        """역방향 링크 조회.

        Args:
            path: 대상 문서 경로

        Returns:
            이 문서를 참조하는 문서 경로 리스트
        """
        ...

    def get_all_paths(self) -> set[str]:
        """모든 노드 경로.

        Returns:
            모든 문서 경로 집합
        """
        ...

    def get_edges(self) -> list[dict[str, str]]:
        """모든 엣지.

        Returns:
            {"source": str, "target": str} 형태의 엣지 리스트
        """
        ...

    def reload(self) -> None:
        """그래프 리로드.

        graph.json이 갱신된 후 호출합니다.
        """
        ...

    @property
    def node_count(self) -> int:
        """그래프 노드 수.

        Returns:
            노드 수
        """
        ...


@runtime_checkable
class MetaRepository(Protocol):
    """메타데이터 저장소 인터페이스.

    인덱스 메타데이터를 관리합니다.
    """

    def get_last_indexed(self) -> str | None:
        """마지막 인덱싱 시간.

        Returns:
            ISO 형식 시간 문자열 또는 None
        """
        ...


# =============================================================================
# Cache Protocol
# =============================================================================


@runtime_checkable
class QueryCache(Protocol):
    """쿼리 캐시 인터페이스.

    쿼리 임베딩 결과를 캐싱합니다.
    """

    def get_or_compute(
        self, key: str, compute_fn: Callable[[str], tuple[float, ...]]
    ) -> tuple[float, ...]:
        """캐시 조회 또는 계산.

        Args:
            key: 캐시 키 (쿼리 문자열)
            compute_fn: 캐시 미스 시 호출할 함수

        Returns:
            임베딩 벡터 (tuple)
        """
        ...

    def clear(self) -> None:
        """캐시 초기화."""
        ...


# =============================================================================
# Query Expander Protocol
# =============================================================================


@runtime_checkable
class QueryExpanderProtocol(Protocol):
    """쿼리 확장기 인터페이스.

    동의어 기반으로 검색 쿼리를 확장합니다.
    """

    def expand(self, query: str) -> list[str]:
        """쿼리를 동의어로 확장.

        Args:
            query: 원본 검색 쿼리

        Returns:
            확장된 쿼리 리스트 (원본 포함)
        """
        ...

    def get_synonyms(self, word: str) -> list[str]:
        """특정 단어의 동의어 목록 반환.

        Args:
            word: 조회할 단어

        Returns:
            동의어 리스트 (없으면 빈 리스트)
        """
        ...


# =============================================================================
# Category Provider Protocol
# =============================================================================


if TYPE_CHECKING:
    from .models import CategoryListing


@runtime_checkable
class CategoryProvider(Protocol):
    """카테고리 제공자 인터페이스.

    사용자 폴더 구조 또는 인덱스 분석을 통해 카테고리 목록을 제공합니다.
    """

    def list_categories(self, force_refresh: bool = False) -> "CategoryListing":
        """현재 활성 카테고리 목록 반환.

        Args:
            force_refresh: True면 캐시 무시하고 재감지

        Returns:
            CategoryListing 객체
        """
        ...

    def invalidate(self) -> None:
        """카테고리 캐시 무효화."""
        ...
