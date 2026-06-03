"""WikiIndexer._create_or_replace_table 회귀 테스트 (v0.5.0).

운영 로그에서 ``create_table(mode="overwrite")`` 가 lancedb 일부 버전에서
``Table 'wiki' already exists`` 를 던져 reindex 가 수천 건 막혔다. 이때
명시적 drop+create 로 폴백해야 한다.

모델 로드(SentenceTransformer)를 피하기 위해 ``__new__`` 로 빈 인스턴스를
만들고 ``db`` 만 가짜로 주입한다 (메서드는 self.db 만 사용).
"""

from __future__ import annotations

from typing import Any

from wiki_search_mcp.infrastructure.indexing.indexer import WikiIndexer


class _FakeDB:
    """create_table / drop_table 호출을 기록하는 가짜 lancedb 연결.

    ``fail_overwrite`` 가 True 면 첫 overwrite 호출에서 already-exists 를 던진다.
    """

    def __init__(self, *, fail_overwrite: bool):
        self._fail_overwrite = fail_overwrite
        self.calls: list[str] = []

    def create_table(self, name: str, records: Any, mode: str | None = None) -> str:
        if mode == "overwrite":
            self.calls.append("create_overwrite")
            if self._fail_overwrite:
                raise RuntimeError("Table 'wiki' already exists")
            return "ok"
        self.calls.append("create_plain")
        return "ok"

    def drop_table(self, name: str) -> None:
        self.calls.append("drop")


def _make_indexer(db: _FakeDB) -> WikiIndexer:
    idx = WikiIndexer.__new__(WikiIndexer)  # __init__ 우회 (모델 로드 안 함)
    idx.db = db
    return idx


def test_overwrite_success_no_fallback() -> None:
    """overwrite 가 성공하면 drop 을 호출하지 않는다 (정상 경로)."""
    db = _FakeDB(fail_overwrite=False)
    idx = _make_indexer(db)

    idx._create_or_replace_table([{"path": "a.md"}])

    assert db.calls == ["create_overwrite"]


def test_already_exists_falls_back_to_drop_create() -> None:
    """overwrite 가 already-exists 로 실패하면 drop 후 재생성한다."""
    db = _FakeDB(fail_overwrite=True)
    idx = _make_indexer(db)

    idx._create_or_replace_table([{"path": "a.md"}])

    assert db.calls == ["create_overwrite", "drop", "create_plain"]


def test_non_already_exists_error_propagates() -> None:
    """already-exists 가 아닌 예외는 폴백 없이 그대로 전파한다."""
    class _BoomDB(_FakeDB):
        def create_table(self, name: str, records: Any, mode: str | None = None) -> str:
            self.calls.append("create")
            raise RuntimeError("disk full")

    db = _BoomDB(fail_overwrite=True)
    idx = _make_indexer(db)

    raised = False
    try:
        idx._create_or_replace_table([{"path": "a.md"}])
    except RuntimeError as e:
        raised = "disk full" in str(e)
    assert raised
    assert "drop" not in db.calls  # 폴백 안 함


def test_drop_failure_is_tolerated() -> None:
    """drop 이 '테이블 없음' 등으로 실패해도 create 로 진행한다."""
    class _DropFailDB(_FakeDB):
        def drop_table(self, name: str) -> None:
            self.calls.append("drop_fail")
            raise RuntimeError("Table 'wiki' was not found")

    db = _DropFailDB(fail_overwrite=True)
    idx = _make_indexer(db)

    idx._create_or_replace_table([{"path": "a.md"}])

    assert db.calls == ["create_overwrite", "drop_fail", "create_plain"]
