"""WikiIndexer 변경 감지(mtime + 내용 해시) 테스트.

mtime 단독 감지의 한계(touch/checkout 로 mtime 만 바뀌면 불필요 재임베딩)를
내용 해시 병행으로 막는지 검증한다.
"""

import os

from wiki_search_mcp.infrastructure.indexing import WikiIndexer


def _make_indexer(tmp_path):
    wiki_path = tmp_path / "wiki"
    (wiki_path / "pages").mkdir(parents=True)
    (wiki_path / "pages" / "seed.md").write_text("seed", encoding="utf-8")
    return WikiIndexer(str(wiki_path)), wiki_path


class TestIsUnchanged:
    """_is_unchanged 순수 로직 검증 (모델 인코딩 불필요)."""

    def test_new_file_is_changed(self, tmp_path):
        indexer, wiki = _make_indexer(tmp_path)
        page = wiki / "pages" / "seed.md"
        unchanged, h = indexer._is_unchanged(None, page, 123.0)
        assert unchanged is False
        assert h is None  # 신규 파일은 해시 계산 안 함

    def test_legacy_float_matching_mtime(self, tmp_path):
        """구버전 포맷(float): mtime 일치하면 미변경, 해시 미계산."""
        indexer, wiki = _make_indexer(tmp_path)
        page = wiki / "pages" / "seed.md"
        mtime = indexer._get_file_mtime(page)
        unchanged, h = indexer._is_unchanged(mtime, page, mtime)
        assert unchanged is True
        assert h is None

    def test_legacy_float_differing_mtime(self, tmp_path):
        """구버전 포맷(float): mtime 다르면 변경으로 판정(해시 정보 없음)."""
        indexer, wiki = _make_indexer(tmp_path)
        page = wiki / "pages" / "seed.md"
        mtime = indexer._get_file_mtime(page)
        unchanged, h = indexer._is_unchanged(mtime - 100, page, mtime)
        assert unchanged is False
        assert h is None  # 구포맷은 해시 비교 불가 → 그냥 변경 처리

    def test_new_format_fast_path(self, tmp_path):
        """신규 포맷: mtime 일치 → 읽기 없이 미변경."""
        indexer, wiki = _make_indexer(tmp_path)
        page = wiki / "pages" / "seed.md"
        mtime = indexer._get_file_mtime(page)
        stored = {"mtime": mtime, "hash": "irrelevant"}
        unchanged, h = indexer._is_unchanged(stored, page, mtime)
        assert unchanged is True
        assert h is None  # 빠른 경로는 해시 계산 안 함

    def test_new_format_mtime_changed_content_same(self, tmp_path):
        """신규 포맷: mtime 다르지만 내용 동일 → 미변경 + 현재 해시 반환."""
        indexer, wiki = _make_indexer(tmp_path)
        page = wiki / "pages" / "seed.md"
        real_hash = indexer._get_file_hash(page)
        mtime = indexer._get_file_mtime(page)
        stored = {"mtime": mtime - 100, "hash": real_hash}
        unchanged, h = indexer._is_unchanged(stored, page, mtime)
        assert unchanged is True
        assert h == real_hash  # mtime 갱신용 해시 반환

    def test_new_format_content_changed(self, tmp_path):
        """신규 포맷: mtime 다르고 내용도 다르면 변경."""
        indexer, wiki = _make_indexer(tmp_path)
        page = wiki / "pages" / "seed.md"
        mtime = indexer._get_file_mtime(page)
        stored = {"mtime": mtime - 100, "hash": "deadbeef"}
        unchanged, h = indexer._is_unchanged(stored, page, mtime)
        assert unchanged is False
        assert h == indexer._get_file_hash(page)


class TestIncrementalReindexHash:
    """실제 reindex 통합: mtime churn 시 재임베딩 회피."""

    def test_touch_does_not_reembed(self, tmp_path):
        """내용 그대로 mtime 만 바꾸면(=touch) updated=0 이어야 한다."""
        indexer, wiki = _make_indexer(tmp_path)
        (wiki / "pages" / "doc.md").write_text(
            "---\ntitle: Doc\n---\n\nbody", encoding="utf-8"
        )

        first = indexer.reindex(full=False)
        assert first["updated"] >= 1  # 신규 인덱싱

        # mtime 만 미래로 변경 (내용 동일)
        page = wiki / "pages" / "doc.md"
        future = indexer._get_file_mtime(page) + 1000
        os.utime(page, (future, future))

        second = indexer.reindex(full=False)
        # 내용 해시 동일 → 재임베딩 없음
        assert second["updated"] == 0

    def test_content_change_reembeds(self, tmp_path):
        """내용이 바뀌면 재임베딩(updated>=1)."""
        indexer, wiki = _make_indexer(tmp_path)
        page = wiki / "pages" / "doc.md"
        page.write_text("---\ntitle: Doc\n---\n\nbody", encoding="utf-8")

        indexer.reindex(full=False)

        page.write_text("---\ntitle: Doc\n---\n\nCHANGED body", encoding="utf-8")
        result = indexer.reindex(full=False)
        assert result["updated"] >= 1

    def test_meta_stores_new_format(self, tmp_path):
        """reindex 후 meta['files'] 항목이 신규 포맷(dict)으로 저장된다."""
        indexer, wiki = _make_indexer(tmp_path)
        (wiki / "pages" / "doc.md").write_text("body", encoding="utf-8")
        indexer.reindex(full=False)

        meta = indexer._load_meta()
        entry = meta["files"]["doc.md"]
        assert isinstance(entry, dict)
        assert "mtime" in entry
        assert "hash" in entry
        assert len(entry["hash"]) == 64  # sha256 hex


class TestReindexLockTimeout:
    """락 timeout 시 쓰기 skip (무보호 쓰기로 인한 손상 방지)."""

    def test_lock_timeout_skips_writes(self, tmp_path, monkeypatch):
        """cross_process_lock 이 실패(False)하면 쓰기를 건너뛰고 skipped 반환.

        과거에는 경고 후 강행해 LanceDB/JSON 무보호 쓰기 → 손상 위험.
        이제는 쓰기를 전혀 수행하지 않고 조기 반환해야 한다.
        """
        from contextlib import contextmanager

        indexer, wiki = _make_indexer(tmp_path)
        (wiki / "pages" / "doc.md").write_text(
            "---\ntitle: D\n---\nbody", encoding="utf-8"
        )

        # 락을 항상 실패(False)로 만든다.
        @contextmanager
        def fake_lock(*args, **kwargs):
            yield False

        monkeypatch.setattr(
            "wiki_search_mcp.infrastructure.indexing.indexer.cross_process_lock",
            fake_lock,
        )

        result = indexer.reindex(full=False)

        assert result.get("skipped") == "lock_timeout"
        assert result["indexed"] == 0
        assert result["updated"] == 0
        # 쓰기를 건너뛰었으므로 인덱스 산출물이 생성되지 않아야 한다.
        assert not (indexer.db_path / "graph.json").exists()
        assert not (indexer.db_path / "bm25_index.json").exists()
