"""Tests for infrastructure/storage/vector_store.py.

LanceDB 벡터 스토어의 기능을 테스트합니다.
lancedb가 설치되어 있지 않으면 테스트를 건너뜁니다.
"""

import pytest

# lancedb가 없으면 테스트 건너뛰기
lancedb = pytest.importorskip("lancedb")

from wiki_search_mcp.infrastructure.storage.vector_store import LanceVectorStore


@pytest.fixture
def temp_db(tmp_path):
    """임시 LanceDB 생성."""
    db_path = tmp_path / ".vectordb"
    db_path.mkdir()
    db = lancedb.connect(str(db_path))

    # 테스트용 wiki 테이블 생성
    test_data = [
        {
            "path": "infra/nginx.md",
            "title": "Nginx 설정",
            "category": "infra",
            "tags": ["nginx", "web"],
            "summary": "Nginx 설정 방법",
            "state": "stable",
            "confidence_level": "high",
            "confidence_score": 90,
            "vector": [0.1] * 768,
        },
        {
            "path": "dev/python.md",
            "title": "Python 가이드",
            "category": "dev",
            "tags": ["python"],
            "summary": "Python 개발 가이드",
            "state": "draft",
            "confidence_level": "medium",
            "confidence_score": 60,
            "vector": [0.2] * 768,
        },
    ]
    db.create_table("wiki", test_data)

    return db_path


class TestLanceVectorStore:
    """LanceVectorStore 테스트."""

    def test_exists_returns_true_when_table_exists(self, temp_db):
        """테이블이 있으면 exists() True."""
        store = LanceVectorStore(temp_db)

        assert store.exists() is True

    def test_exists_returns_false_when_no_table(self, tmp_path):
        """테이블이 없으면 exists() False."""
        db_path = tmp_path / ".vectordb"
        db_path.mkdir()

        store = LanceVectorStore(db_path)

        assert store.exists() is False

    def test_find_by_path_returns_document(self, temp_db):
        """find_by_path()로 문서 조회."""
        store = LanceVectorStore(temp_db)
        doc = store.find_by_path("infra/nginx.md")

        assert doc is not None
        assert doc["title"] == "Nginx 설정"
        assert doc["category"] == "infra"

    def test_find_by_path_returns_none_for_missing(self, temp_db):
        """없는 문서는 None 반환."""
        store = LanceVectorStore(temp_db)
        doc = store.find_by_path("nonexistent.md")

        assert doc is None

    def test_find_by_path_escapes_quotes(self, temp_db):
        """경로에 싱글 쿼트가 있어도 SQL injection 방지."""
        store = LanceVectorStore(temp_db)
        # 에러 없이 실행되어야 함
        doc = store.find_by_path("path'with'quotes.md")

        assert doc is None

    def test_search_returns_results(self, temp_db):
        """search()로 벡터 유사도 검색."""
        store = LanceVectorStore(temp_db)
        results = store.search([0.1] * 768, limit=5)

        assert len(results) >= 1
        # 가장 유사한 결과가 첫 번째
        assert results[0]["path"] == "infra/nginx.md"

    def test_invalidate_cache_refreshes_table(self, temp_db):
        """invalidate_cache() 후 테이블 캐시 초기화."""
        store = LanceVectorStore(temp_db)
        _ = store.table  # 캐시 생성

        store.invalidate_cache()

        assert store._table_cache is None

    def test_to_arrow_list_returns_all_docs(self, temp_db):
        """to_arrow_list()로 전체 문서 조회."""
        store = LanceVectorStore(temp_db)
        docs = store.to_arrow_list()

        assert len(docs) == 2


class TestLanceVectorStoreEmpty:
    """빈 스토어 테스트."""

    def test_search_on_empty_returns_empty(self, tmp_path):
        """빈 스토어에서 검색하면 빈 리스트."""
        db_path = tmp_path / ".vectordb"
        db_path.mkdir()

        store = LanceVectorStore(db_path)
        results = store.search([0.1] * 768, limit=5)

        assert results == []
