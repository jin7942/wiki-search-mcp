"""Tests for infrastructure/storage/bm25_store.py.

BM25 인덱스 스토어의 기능을 테스트합니다.
rank_bm25가 설치되어 있지 않으면 테스트를 건너뜁니다.
"""

import json

import pytest

# rank_bm25가 없으면 테스트 건너뛰기
pytest.importorskip("rank_bm25")

from wiki_search_mcp.infrastructure.storage.bm25_store import BM25IndexStore


@pytest.fixture
def temp_bm25_index(tmp_path):
    """임시 BM25 인덱스 생성."""
    db_path = tmp_path / ".vectordb"
    db_path.mkdir()

    # BM25 인덱스 생성
    bm25_data = {
        "paths": ["infra/nginx.md", "infra/ssl.md", "dev/python.md"],
        "tokens": [
            ["nginx", "설정", "방법"],
            ["ssl", "인증서", "nginx"],
            ["python", "개발", "가이드"],
        ],
    }
    (db_path / "bm25_index.json").write_text(json.dumps(bm25_data), encoding="utf-8")

    return db_path


class TestBM25IndexStore:
    """BM25IndexStore 테스트."""

    def test_exists_returns_true_when_index_exists(self, temp_bm25_index):
        """인덱스가 있으면 exists() True."""
        store = BM25IndexStore(temp_bm25_index)

        assert store.exists() is True

    def test_exists_returns_false_when_no_index(self, tmp_path):
        """인덱스가 없으면 exists() False."""
        db_path = tmp_path / ".vectordb"
        db_path.mkdir()

        store = BM25IndexStore(db_path)

        assert store.exists() is False

    def test_search_returns_matching_docs(self, temp_bm25_index):
        """search()로 키워드 검색."""
        store = BM25IndexStore(temp_bm25_index)
        results = store.search("nginx 설정", limit=5)

        assert len(results) >= 1
        # (path, score) 튜플
        paths = [r[0] for r in results]
        assert "infra/nginx.md" in paths

    def test_search_returns_empty_for_no_match(self, temp_bm25_index):
        """매칭되는 문서가 없으면 빈 리스트."""
        store = BM25IndexStore(temp_bm25_index)
        results = store.search("nonexistent keyword", limit=5)

        assert results == []

    def test_search_ignores_short_tokens(self, temp_bm25_index):
        """1글자 토큰은 무시."""
        store = BM25IndexStore(temp_bm25_index)
        # "a"는 무시되고, 유효한 토큰이 없으면 빈 결과
        results = store.search("a", limit=5)

        assert results == []

    def test_document_count(self, temp_bm25_index):
        """document_count 속성."""
        store = BM25IndexStore(temp_bm25_index)

        assert store.document_count == 3

    def test_reload_refreshes_index(self, temp_bm25_index):
        """reload() 후 인덱스 갱신."""
        store = BM25IndexStore(temp_bm25_index)

        # 인덱스 파일 수정
        new_data = {
            "paths": ["new/doc.md"],
            "tokens": [["new", "document"]],
        }
        (temp_bm25_index / "bm25_index.json").write_text(
            json.dumps(new_data), encoding="utf-8"
        )

        store.reload()

        assert store.document_count == 1


class TestBM25IndexStoreEmpty:
    """빈 스토어 테스트."""

    def test_search_on_empty_returns_empty(self, tmp_path):
        """빈 스토어에서 검색하면 빈 리스트."""
        db_path = tmp_path / ".vectordb"
        db_path.mkdir()

        store = BM25IndexStore(db_path)
        results = store.search("nginx", limit=5)

        assert results == []
