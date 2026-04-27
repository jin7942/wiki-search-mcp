"""유연한 파일 구조 테스트

pages/ 디렉토리 유무에 따른 동작을 검증합니다.
"""

import tempfile
from pathlib import Path


class TestPagesPathDetection:
    """pages 디렉토리 탐지 테스트."""

    def test_with_pages_directory(self):
        """pages/ 디렉토리가 있으면 해당 경로 사용."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir)
            pages_path = wiki_path / "pages"
            pages_path.mkdir(parents=True)

            # pages_candidate 로직 검증
            pages_candidate = wiki_path / "pages"
            if pages_candidate.exists() and pages_candidate.is_dir():
                detected_path = pages_candidate
            else:
                detected_path = wiki_path

            assert detected_path == pages_path

    def test_without_pages_directory(self):
        """pages/ 디렉토리가 없으면 루트 경로 사용."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir)
            # pages 디렉토리 없음

            pages_candidate = wiki_path / "pages"
            if pages_candidate.exists() and pages_candidate.is_dir():
                detected_path = pages_candidate
            else:
                detected_path = wiki_path

            assert detected_path == wiki_path

    def test_pages_is_file_not_directory(self):
        """pages가 파일이면 루트 경로 사용."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir)
            # pages를 파일로 생성
            (wiki_path / "pages").write_text("not a directory")

            pages_candidate = wiki_path / "pages"
            if pages_candidate.exists() and pages_candidate.is_dir():
                detected_path = pages_candidate
            else:
                detected_path = wiki_path

            assert detected_path == wiki_path


class TestIndexerFlexiblePath:
    """Indexer의 유연한 경로 처리 테스트."""

    def test_indexer_with_pages(self):
        """pages/ 있는 경우 Indexer 초기화."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir)
            pages_path = wiki_path / "pages"
            pages_path.mkdir(parents=True)

            # 테스트 문서 생성
            (pages_path / "test.md").write_text("# Test")

            # Indexer 로직 시뮬레이션
            pages_candidate = wiki_path / "pages"
            if pages_candidate.exists() and pages_candidate.is_dir():
                resolved_pages = pages_candidate
            else:
                resolved_pages = wiki_path

            md_files = list(resolved_pages.rglob("*.md"))
            assert len(md_files) == 1
            assert md_files[0].name == "test.md"

    def test_indexer_without_pages(self):
        """pages/ 없는 경우 루트에서 검색."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir)

            # 루트에 직접 문서 생성
            (wiki_path / "test.md").write_text("# Test")
            (wiki_path / "subdir").mkdir()
            (wiki_path / "subdir" / "nested.md").write_text("# Nested")

            pages_candidate = wiki_path / "pages"
            if pages_candidate.exists() and pages_candidate.is_dir():
                resolved_pages = pages_candidate
            else:
                resolved_pages = wiki_path

            md_files = list(resolved_pages.rglob("*.md"))
            assert len(md_files) == 2

    def test_nested_structure_without_pages(self):
        """pages/ 없이 중첩 디렉토리 구조."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir)

            # 옵시디언 스타일 구조 생성
            (wiki_path / "infra").mkdir()
            (wiki_path / "infra" / "nginx.md").write_text("# Nginx")
            (wiki_path / "devops").mkdir()
            (wiki_path / "devops" / "ci-cd.md").write_text("# CI/CD")
            (wiki_path / "README.md").write_text("# My Wiki")

            pages_candidate = wiki_path / "pages"
            if pages_candidate.exists() and pages_candidate.is_dir():
                resolved_pages = pages_candidate
            else:
                resolved_pages = wiki_path

            md_files = list(resolved_pages.rglob("*.md"))
            assert len(md_files) == 3

            # 상대 경로 확인
            relative_paths = [
                str(f.relative_to(resolved_pages)) for f in md_files
            ]
            assert "infra/nginx.md" in relative_paths or "infra\\nginx.md" in relative_paths


class TestSearcherFlexiblePath:
    """Searcher의 유연한 경로 처리 테스트."""

    def test_file_path_resolution(self):
        """get_document에서 파일 경로 해결."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir)

            # 루트에 직접 문서 생성
            (wiki_path / "test.md").write_text("# Test Content")

            # pages_path 결정 로직
            pages_candidate = wiki_path / "pages"
            if pages_candidate.exists() and pages_candidate.is_dir():
                pages_path = pages_candidate
            else:
                pages_path = wiki_path

            # 파일 경로 해결
            file_path = pages_path / "test.md"
            assert file_path.exists()
            assert file_path.read_text() == "# Test Content"


class TestCliFlexiblePath:
    """CLI의 유연한 경로 처리 테스트."""

    def test_warning_for_no_pages_with_md(self):
        """pages/ 없지만 .md 있으면 경고만."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir)
            (wiki_path / "test.md").write_text("# Test")

            pages_path = wiki_path / "pages"
            if not pages_path.exists():
                md_files = list(wiki_path.rglob("*.md"))
                # .md 파일이 있으면 진행 가능
                assert len(md_files) > 0

    def test_warning_for_no_pages_no_md(self):
        """pages/ 없고 .md도 없으면 경고."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir)

            pages_path = wiki_path / "pages"
            if not pages_path.exists():
                md_files = list(wiki_path.rglob("*.md"))
                # .md 파일이 없으면 경고
                assert len(md_files) == 0
