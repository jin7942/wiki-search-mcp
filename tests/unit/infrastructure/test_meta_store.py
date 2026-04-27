"""Tests for infrastructure/storage/meta_store.py.

메타데이터 스토어의 기능을 테스트합니다.
"""

import json

import pytest

from wiki_search_mcp.infrastructure.storage.meta_store import JsonMetaStore


@pytest.fixture
def temp_meta(tmp_path):
    """임시 메타데이터 생성."""
    db_path = tmp_path / ".vectordb"
    db_path.mkdir()

    meta_data = {
        "files": {
            "infra/nginx.md": {"hash": "abc123", "indexed_at": "2024-01-01"},
            "dev/python.md": {"hash": "def456", "indexed_at": "2024-01-02"},
        },
        "last_indexed": "2024-12-01T10:00:00",
    }
    (db_path / "meta.json").write_text(json.dumps(meta_data), encoding="utf-8")

    return db_path


class TestJsonMetaStore:
    """JsonMetaStore 테스트."""

    def test_get_last_indexed_returns_timestamp(self, temp_meta):
        """get_last_indexed()로 마지막 인덱싱 시간 조회."""
        store = JsonMetaStore(temp_meta)

        assert store.get_last_indexed() == "2024-12-01T10:00:00"

    def test_get_last_indexed_returns_none_when_not_set(self, tmp_path):
        """last_indexed가 없으면 None 반환."""
        db_path = tmp_path / ".vectordb"
        db_path.mkdir()

        store = JsonMetaStore(db_path)

        assert store.get_last_indexed() is None

    def test_get_file_info_returns_metadata(self, temp_meta):
        """get_file_info()로 파일 메타데이터 조회."""
        store = JsonMetaStore(temp_meta)
        info = store.get_file_info("infra/nginx.md")

        assert info is not None
        assert info["hash"] == "abc123"

    def test_get_file_info_returns_none_for_missing(self, temp_meta):
        """없는 파일은 None 반환."""
        store = JsonMetaStore(temp_meta)
        info = store.get_file_info("nonexistent.md")

        assert info is None

    def test_file_count(self, temp_meta):
        """file_count 속성."""
        store = JsonMetaStore(temp_meta)

        assert store.file_count == 2

    def test_reload_refreshes_meta(self, temp_meta):
        """reload() 후 메타데이터 갱신."""
        store = JsonMetaStore(temp_meta)

        # 메타 파일 수정
        new_meta = {"files": {}, "last_indexed": "2025-01-01T00:00:00"}
        (temp_meta / "meta.json").write_text(json.dumps(new_meta), encoding="utf-8")

        store.reload()

        assert store.get_last_indexed() == "2025-01-01T00:00:00"
        assert store.file_count == 0


class TestJsonMetaStoreEmpty:
    """빈 스토어 테스트."""

    def test_default_values_on_missing_file(self, tmp_path):
        """파일 없으면 기본값."""
        db_path = tmp_path / ".vectordb"
        db_path.mkdir()

        store = JsonMetaStore(db_path)

        assert store.get_last_indexed() is None
        assert store.file_count == 0
