"""LanceDB 버전 호환 헬퍼 회귀 테스트.

v0.2.7 이전 결함: ``"wiki" in db.list_tables()`` 가 lancedb 0.13+ 에서 항상
``False`` 를 반환했다. 신버전은 ``list_tables()`` 가 ``ListTablesResponse``
객체를 반환하는데, ``in`` 연산이 객체를 ``(field_name, value)`` 쌍으로 순회하기
때문이다. 그 결과 인덱싱된 wiki에서도 ``exists()`` 가 False → 검색/통계 전체 무력화.

이 테스트는 실물 lancedb(설치 시) + 신/구버전 반환 타입 모사로 헬퍼를 고정한다.
"""

from __future__ import annotations

import pytest

from wiki_search_mcp.infrastructure.storage.lancedb_compat import (
    has_table,
    list_table_names,
)


class _FakeListTablesResponse:
    """lancedb 0.13+ 의 ListTablesResponse 모사 (tables 속성 보유)."""

    def __init__(self, tables: list[str]) -> None:
        self.tables = tables
        self.page_token = None

    def __iter__(self):
        # 실제 객체처럼 (field_name, value) 쌍을 순회 → 'wiki' in 이 False 가 되는 함정
        yield ("tables", self.tables)
        yield ("page_token", self.page_token)


class _FakeNewDB:
    def __init__(self, tables: list[str]) -> None:
        self._tables = tables

    def list_tables(self) -> _FakeListTablesResponse:
        return _FakeListTablesResponse(self._tables)


class _FakeOldDB:
    """lancedb 0.12 이하: list_tables() 가 list[str] 직접 반환."""

    def __init__(self, tables: list[str]) -> None:
        self._tables = tables

    def list_tables(self) -> list[str]:
        return list(self._tables)


class TestListTableNamesNewVersion:
    """신버전(ListTablesResponse) 처리."""

    def test_returns_table_names(self) -> None:
        db = _FakeNewDB(["wiki", "other"])
        assert list_table_names(db) == ["wiki", "other"]

    def test_has_table_true(self) -> None:
        db = _FakeNewDB(["wiki"])
        assert has_table(db, "wiki") is True

    def test_has_table_false_for_missing(self) -> None:
        db = _FakeNewDB(["other"])
        assert has_table(db, "wiki") is False

    def test_naive_in_operator_would_fail(self) -> None:
        """회귀의 정체 고정: 객체에 ``in`` 직접 쓰면 False (버그 재현)."""
        resp = _FakeListTablesResponse(["wiki"])
        assert ("wiki" in resp) is False  # 함정 — 헬퍼가 이걸 회피해야 함
        assert "wiki" in resp.tables  # 실제 데이터는 여기 있음


class TestListTableNamesOldVersion:
    """구버전(list[str]) 처리."""

    def test_returns_table_names(self) -> None:
        db = _FakeOldDB(["wiki", "other"])
        assert list_table_names(db) == ["wiki", "other"]

    def test_has_table_true(self) -> None:
        db = _FakeOldDB(["wiki"])
        assert has_table(db, "wiki") is True


class TestEmpty:
    def test_new_version_empty(self) -> None:
        assert list_table_names(_FakeNewDB([])) == []
        assert has_table(_FakeNewDB([]), "wiki") is False

    def test_old_version_empty(self) -> None:
        assert list_table_names(_FakeOldDB([])) == []


class TestRealLanceDB:
    """실물 lancedb로 end-to-end 확인 (설치 시)."""

    def test_real_create_then_has_table(self, tmp_path) -> None:
        lancedb = pytest.importorskip("lancedb")
        db = lancedb.connect(str(tmp_path / ".vectordb"))
        db.create_table("wiki", [{"id": 1, "vector": [0.1, 0.2]}])
        # 회귀 핵심: 인덱싱 직후 has_table 이 True 여야 한다
        assert has_table(db, "wiki") is True
        assert "wiki" in list_table_names(db)
