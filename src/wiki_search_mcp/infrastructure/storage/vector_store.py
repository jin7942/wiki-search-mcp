"""LanceDB vector store implementation.

core.protocols.VectorRepository 인터페이스의 구현체입니다.
LanceDB를 사용하여 벡터 유사도 검색을 제공합니다.

사용 예:
    from wiki_search_mcp.infrastructure.storage import LanceVectorStore

    store = LanceVectorStore(Path("/wiki/.vectordb"))
    results = store.search(vector, limit=5)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import lancedb

from wiki_search_mcp.core.exceptions import IndexNotFoundError, InvalidPathError
from wiki_search_mcp.core.path_validator import validate_path_for_query
from wiki_search_mcp.infrastructure.storage.lancedb_compat import has_table


class LanceVectorStore:
    """LanceDB 벡터 스토어 구현.

    VectorRepository 프로토콜을 구현합니다.
    테이블 캐싱으로 성능을 최적화합니다.

    Attributes:
        _db: LanceDB 연결 객체
        _table_cache: wiki 테이블 캐시
    """

    def __init__(self, db_path: Path):
        """LanceVectorStore 초기화.

        Args:
            db_path: LanceDB 저장 경로 (.vectordb)

        Raises:
            IndexNotFoundError: LanceDB 연결 실패 시
        """
        self._db_path = db_path
        try:
            self._db = lancedb.connect(str(db_path))
        except Exception as e:
            raise IndexNotFoundError.of(str(db_path)) from e
        self._table_cache = None

    @property
    def table(self):
        """wiki 테이블 참조 (캐싱).

        매 검색마다 open_table()을 호출하는 대신 캐시된 참조를 사용합니다.
        """
        if self._table_cache is None:
            if has_table(self._db, "wiki"):
                self._table_cache = self._db.open_table("wiki")
        return self._table_cache

    def exists(self) -> bool:
        """인덱스 존재 여부.

        Returns:
            wiki 테이블이 존재하면 True
        """
        return self.table is not None

    def search(
        self, vector: list[float], limit: int, where: str | None = None
    ) -> list[dict[str, Any]]:
        """벡터 유사도 검색.

        Args:
            vector: 검색 벡터
            limit: 최대 결과 수
            where: 필터 조건 (SQL-like, 예: "category = 'infra'")

        Returns:
            검색 결과 리스트
        """
        if self.table is None:
            return []

        query = self.table.search(vector).limit(limit)
        if where:
            query = query.where(where)

        return query.to_list()

    def find_by_path(self, path: str) -> dict[str, Any] | None:
        """경로로 문서 조회.

        Args:
            path: 문서 경로

        Returns:
            문서 정보 또는 None

        Note:
            경로 검증은 PathValidator를 사용합니다.
            검증 실패 시 None을 반환합니다.
        """
        if self.table is None:
            return None

        # 경로 형식 검증 (PathValidator 사용)
        try:
            validated_path = validate_path_for_query(path)
        except InvalidPathError:
            return None

        # SQL Injection 방어: 싱글 쿼트 이스케이프
        safe_path = validated_path.replace("'", "''")
        results = self.table.search().where(f"path = '{safe_path}'").limit(1).to_list()

        return results[0] if results else None

    def find_all(self, limit: int = 50) -> list[dict[str, Any]]:
        """전체 문서 조회.

        Args:
            limit: 최대 결과 수

        Returns:
            문서 리스트
        """
        if self.table is None:
            return []

        return self.table.search().limit(limit).to_list()

    def to_arrow_list(self) -> list[dict[str, Any]]:
        """PyArrow로 전체 문서 조회 (pandas 불필요).

        Returns:
            전체 문서 리스트
        """
        if self.table is None:
            return []

        return self.table.to_arrow().to_pylist()

    def invalidate_cache(self) -> None:
        """캐시 무효화.

        reindex 후 호출하여 테이블 캐시를 갱신합니다.
        """
        self._table_cache = None

    def get_vector_by_path(self, path: str) -> list[float] | None:
        """경로로 벡터 조회.

        Args:
            path: 문서 경로

        Returns:
            임베딩 벡터 또는 None
        """
        doc = self.find_by_path(path)
        return doc["vector"] if doc else None
