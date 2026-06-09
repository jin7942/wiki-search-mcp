"""ClassificationService 구조 진단 테스트 (보고서 Gap #2/#6/#7).

- health_check: 평면 누적 폴더 + 빈 폴더 진단 (#2, #7)
- suggest_filename_normalization: 파일명 선두 날짜 표준화 제안 (#6)
모두 read-only: 반환만 검증, 디스크 수정 없음.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiki_search_mcp.core.exceptions import InvalidPathError
from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher
from wiki_search_mcp.services.classification_service import ClassificationService


@pytest.fixture
def wiki_path(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def matcher(wiki_path: Path) -> IgnoreMatcher:
    return IgnoreMatcher.from_wiki(wiki_path)


def _make_service(wiki_path: Path, matcher: IgnoreMatcher) -> ClassificationService:
    vector = MagicMock()
    vector.exists.return_value = False
    return ClassificationService(
        pages_path=wiki_path,
        vector_repository=vector,
        document_service=MagicMock(),
        category_service=MagicMock(),
        ignore_matcher=matcher,
    )


def _make_files(folder: Path, n: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (folder / f"doc{i}.md").write_text("x", encoding="utf-8")


# =============================================================================
# health_check (#2, #7)
# =============================================================================


class TestHealthCheck:
    def test_flags_flat_folder_over_threshold(
        self, wiki_path: Path, matcher: IgnoreMatcher
    ):
        """직계 파일 ≥ 임계 + 서브폴더 없음 → 계층화 권장."""
        _make_files(wiki_path / "projects" / "KT", 11)

        svc = _make_service(wiki_path, matcher)
        report = svc.health_check(threshold_flat=10)

        paths = [f.path for f in report.needs_hierarchization]
        assert "projects/KT" in paths
        kt = next(f for f in report.needs_hierarchization if f.path == "projects/KT")
        assert kt.file_count == 11
        assert kt.has_subfolders is False

    def test_below_threshold_not_flagged(
        self, wiki_path: Path, matcher: IgnoreMatcher
    ):
        """임계 미만이면 계층화 권장 안 함."""
        _make_files(wiki_path / "projects" / "Small", 4)

        svc = _make_service(wiki_path, matcher)
        report = svc.health_check(threshold_flat=10)

        assert all(
            f.path != "projects/Small" for f in report.needs_hierarchization
        )

    def test_folder_with_subfolders_not_flagged(
        self, wiki_path: Path, matcher: IgnoreMatcher
    ):
        """직계 파일이 많아도 이미 서브폴더가 있으면 권장 안 함."""
        parent = wiki_path / "projects" / "Hier"
        _make_files(parent, 11)
        (parent / "sub").mkdir()
        (parent / "sub" / "deep.md").write_text("x", encoding="utf-8")

        svc = _make_service(wiki_path, matcher)
        report = svc.health_check(threshold_flat=10)

        assert all(f.path != "projects/Hier" for f in report.needs_hierarchization)

    def test_detects_empty_folder(self, wiki_path: Path, matcher: IgnoreMatcher):
        """하위 어디에도 .md 가 없는 폴더는 empty_folders."""
        (wiki_path / "projects" / "Empty").mkdir(parents=True)
        _make_files(wiki_path / "projects" / "Active", 2)

        svc = _make_service(wiki_path, matcher)
        report = svc.health_check(threshold_flat=10)

        assert "projects/Empty" in report.empty_folders
        assert "projects/Active" not in report.empty_folders

    def test_folder_with_only_subfolder_md_not_empty(
        self, wiki_path: Path, matcher: IgnoreMatcher
    ):
        """직계엔 없어도 하위에 .md 가 있으면 빈 폴더 아님."""
        parent = wiki_path / "projects" / "P"
        (parent / "sub").mkdir(parents=True)
        (parent / "sub" / "a.md").write_text("x", encoding="utf-8")

        svc = _make_service(wiki_path, matcher)
        report = svc.health_check(threshold_flat=10)

        assert "projects/P" not in report.empty_folders

    def test_threshold_respected(self, wiki_path: Path, matcher: IgnoreMatcher):
        """threshold_flat 인자가 반영된다."""
        _make_files(wiki_path / "projects" / "Mid", 5)

        svc = _make_service(wiki_path, matcher)
        # 임계 3 → 잡힘
        assert any(
            f.path == "projects/Mid"
            for f in svc.health_check(threshold_flat=3).needs_hierarchization
        )
        # 임계 10 → 안 잡힘
        assert all(
            f.path != "projects/Mid"
            for f in svc.health_check(threshold_flat=10).needs_hierarchization
        )

    def test_missing_pages_path(self, tmp_path: Path):
        """pages 경로 없으면 빈 리포트."""
        missing = tmp_path / "nope"
        matcher = IgnoreMatcher.from_wiki(tmp_path)
        vector = MagicMock()
        vector.exists.return_value = False
        svc = ClassificationService(
            pages_path=missing,
            vector_repository=vector,
            document_service=MagicMock(),
            category_service=MagicMock(),
            ignore_matcher=matcher,
        )
        report = svc.health_check()
        assert report.needs_hierarchization == ()
        assert report.empty_folders == ()

    def test_to_dict(self, wiki_path: Path, matcher: IgnoreMatcher):
        _make_files(wiki_path / "projects" / "KT", 11)
        (wiki_path / "projects" / "Empty").mkdir(parents=True)

        svc = _make_service(wiki_path, matcher)
        d = svc.health_check(threshold_flat=10).to_dict()

        assert isinstance(d["needs_hierarchization"], list)
        assert d["needs_hierarchization"][0]["path"] == "projects/KT"
        assert "projects/Empty" in d["empty_folders"]
        assert "reasoning" in d


# =============================================================================
# suggest_filename_normalization (#6)
# =============================================================================


class TestFilenameNormalization:
    def test_normalizes_dot_date(self, wiki_path: Path, matcher: IgnoreMatcher):
        """YYYY.MM.DD → YYYY-MM-DD."""
        (wiki_path / "m").mkdir()
        (wiki_path / "m" / "2026.05.12 랙 회의.md").write_text("x", encoding="utf-8")

        svc = _make_service(wiki_path, matcher)
        result = svc.suggest_filename_normalization("m")

        assert len(result.candidates) == 1
        c = result.candidates[0]
        assert c.current == "m/2026.05.12 랙 회의.md"
        assert c.suggested == "m/2026-05-12 랙 회의.md"

    def test_normalizes_yy_date(self, wiki_path: Path, matcher: IgnoreMatcher):
        """YY.MM.DD → 20YY-MM-DD."""
        (wiki_path / "m").mkdir()
        (wiki_path / "m" / "26.05.11 PM 미팅.md").write_text("x", encoding="utf-8")

        svc = _make_service(wiki_path, matcher)
        result = svc.suggest_filename_normalization("m")

        assert result.candidates[0].suggested == "m/2026-05-11 PM 미팅.md"

    def test_normalizes_yymmdd(self, wiki_path: Path, matcher: IgnoreMatcher):
        """YYMMDD(구분자 없음) → 20YY-MM-DD."""
        (wiki_path / "m").mkdir()
        (wiki_path / "m" / "260513 한수원 회의.md").write_text("x", encoding="utf-8")

        svc = _make_service(wiki_path, matcher)
        result = svc.suggest_filename_normalization("m")

        assert result.candidates[0].suggested == "m/2026-05-13 한수원 회의.md"

    def test_already_standard_not_suggested(
        self, wiki_path: Path, matcher: IgnoreMatcher
    ):
        """이미 YYYY-MM-DD 표준이면 제안하지 않음."""
        (wiki_path / "m").mkdir()
        (wiki_path / "m" / "2026-05-19 KT 회의.md").write_text("x", encoding="utf-8")

        svc = _make_service(wiki_path, matcher)
        result = svc.suggest_filename_normalization("m")

        assert result.candidates == ()

    def test_no_date_not_suggested(self, wiki_path: Path, matcher: IgnoreMatcher):
        """날짜 없는 파일명은 대상 아님."""
        (wiki_path / "m").mkdir()
        (wiki_path / "m" / "일반 메모.md").write_text("x", encoding="utf-8")

        svc = _make_service(wiki_path, matcher)
        result = svc.suggest_filename_normalization("m")

        assert result.candidates == ()

    def test_invalid_month_not_treated_as_date(
        self, wiki_path: Path, matcher: IgnoreMatcher
    ):
        """월/일 범위를 벗어난 숫자는 날짜로 보지 않음(오탐 방지)."""
        (wiki_path / "m").mkdir()
        # 991399: 월 13, 일 99 → 날짜 아님
        (wiki_path / "m" / "991399 코드.md").write_text("x", encoding="utf-8")

        svc = _make_service(wiki_path, matcher)
        result = svc.suggest_filename_normalization("m")

        assert result.candidates == ()

    def test_whole_wiki_when_no_folder(
        self, wiki_path: Path, matcher: IgnoreMatcher
    ):
        """folder_path None 이면 pages 전체 스캔."""
        (wiki_path / "a").mkdir()
        (wiki_path / "a" / "2026.01.02 x.md").write_text("x", encoding="utf-8")
        (wiki_path / "b").mkdir()
        (wiki_path / "b" / "2026.03.04 y.md").write_text("x", encoding="utf-8")

        svc = _make_service(wiki_path, matcher)
        result = svc.suggest_filename_normalization(None)

        currents = {c.current for c in result.candidates}
        assert currents == {"a/2026.01.02 x.md", "b/2026.03.04 y.md"}

    def test_traversal_rejected(self, wiki_path: Path, matcher: IgnoreMatcher):
        svc = _make_service(wiki_path, matcher)
        with pytest.raises(InvalidPathError):
            svc.suggest_filename_normalization("../../etc")

    def test_to_dict(self, wiki_path: Path, matcher: IgnoreMatcher):
        (wiki_path / "m").mkdir()
        (wiki_path / "m" / "2026.05.12 x.md").write_text("x", encoding="utf-8")

        svc = _make_service(wiki_path, matcher)
        d = svc.suggest_filename_normalization("m").to_dict()

        assert isinstance(d["candidates"], list)
        assert d["candidates"][0]["current"] == "m/2026.05.12 x.md"
        assert "reason" in d["candidates"][0]
        assert "reasoning" in d
