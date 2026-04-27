"""BM25 index store implementation.

core.protocols.KeywordRepository 인터페이스의 구현체입니다.
BM25 알고리즘을 사용하여 키워드 검색을 제공합니다.

사용 예:
    from wiki_search_mcp.infrastructure.storage import BM25IndexStore

    store = BM25IndexStore(Path("/wiki/.vectordb"))
    results = store.search("nginx 설정", limit=5)
"""

from __future__ import annotations

import json
from pathlib import Path

from rank_bm25 import BM25Okapi

from wiki_search_mcp.core.utils import tokenize


class BM25IndexStore:
    """BM25 인덱스 스토어 구현.

    KeywordRepository 프로토콜을 구현합니다.
    bm25_index.json 파일에서 인덱스를 로드합니다.

    Attributes:
        _bm25: BM25Okapi 인스턴스
        _paths: 문서 경로 리스트 (인덱스 순서)
    """

    def __init__(self, db_path: Path):
        """BM25IndexStore 초기화.

        Args:
            db_path: 인덱스 저장 경로 (.vectordb)
        """
        self._db_path = db_path
        self._bm25: BM25Okapi | None = None
        self._paths: list[str] = []
        self._load()

    def _load(self) -> None:
        """BM25 인덱스 로드."""
        bm25_path = self._db_path / "bm25_index.json"
        if bm25_path.exists():
            data = json.loads(bm25_path.read_text(encoding="utf-8"))
            tokens = data.get("tokens", [])
            self._paths = data.get("paths", [])
            if tokens:
                self._bm25 = BM25Okapi(tokens)

    def exists(self) -> bool:
        """인덱스 존재 여부.

        Returns:
            BM25 인덱스가 로드되었으면 True
        """
        return self._bm25 is not None

    def search(self, query: str, limit: int) -> list[tuple[str, float]]:
        """BM25 키워드 검색.

        Args:
            query: 검색 쿼리
            limit: 최대 결과 수

        Returns:
            (path, score) 튜플 리스트 (점수 내림차순)
        """
        if self._bm25 is None or not self._paths:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scores = self._bm25.get_scores(query_tokens)

        # 점수와 경로를 매핑하여 정렬
        scored_docs = [
            (self._paths[i], float(scores[i]))
            for i in range(len(scores))
            if scores[i] > 0
        ]
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        return scored_docs[:limit]

    def reload(self) -> None:
        """인덱스 리로드.

        인덱스 파일이 갱신된 후 호출합니다.
        """
        self._load()

    @property
    def document_count(self) -> int:
        """인덱싱된 문서 수.

        Returns:
            문서 수
        """
        return len(self._paths)
