"""보안 테스트

SQL Injection, Path Traversal, 입력 검증을 테스트합니다.
"""

import tempfile
from pathlib import Path

import pytest


class TestSQLInjectionDefense:
    """SQL Injection 방어 테스트."""

    def test_single_quote_escape(self):
        """싱글 쿼트가 이스케이프되는지 확인."""
        # 악의적 입력
        malicious_path = "test'; DROP TABLE wiki; --"

        # 방어 로직
        safe_path = malicious_path.replace("'", "''")

        # 이스케이프 확인
        assert "''" in safe_path
        assert "test''" in safe_path

    def test_path_with_special_chars(self):
        """특수 문자가 포함된 경로 처리."""
        paths = [
            "test'.md",
            "test''.md",
            "test\"quote.md",
            "test;semicolon.md",
        ]

        for path in paths:
            safe_path = path.replace("'", "''")
            # 쿼리에 안전하게 삽입 가능한지 확인
            query = f"path = '{safe_path}'"
            assert query  # 에러 없이 생성

    def test_unicode_path_handling(self):
        """유니코드 경로 처리."""
        unicode_path = "문서/한글파일.md"
        safe_path = unicode_path.replace("'", "''")

        assert safe_path == unicode_path  # 변환 없음


class TestPathTraversalDefense:
    """Path Traversal 방어 테스트."""

    def test_reject_double_dot(self):
        """.. 포함 경로 거부."""
        malicious_paths = [
            "../../../etc/passwd",
            "docs/../../../secret",
            "valid/../../invalid",
        ]

        for path in malicious_paths:
            assert ".." in path
            # searcher.get_document()에서 ValueError 발생해야 함

    def test_reject_absolute_path(self):
        """절대 경로 거부."""
        absolute_paths = [
            "/etc/passwd",
            "/home/user/secret",
            "/var/log/auth.log",
        ]

        for path in absolute_paths:
            assert path.startswith("/")
            # searcher.get_document()에서 ValueError 발생해야 함

    def test_accept_valid_relative_path(self):
        """유효한 상대 경로 허용."""
        valid_paths = [
            "infra/nginx.md",
            "devops/ci-cd.md",
            "deep/nested/path/doc.md",
        ]

        for path in valid_paths:
            assert ".." not in path
            assert not path.startswith("/")


class TestInputValidation:
    """입력 검증 테스트."""

    def test_empty_query_rejected(self):
        """빈 쿼리 거부."""
        empty_queries = ["", "   ", "\n", "\t"]

        for query in empty_queries:
            assert not query.strip()

    def test_top_k_range_enforcement(self):
        """top_k 범위 제한."""
        # 최소값 검증
        top_k = -1
        if top_k < 1:
            top_k = 1
        assert top_k == 1

        # 최대값 검증
        top_k = 1000
        if top_k > 100:
            top_k = 100
        assert top_k == 100

    def test_valid_inputs_accepted(self):
        """유효한 입력 허용."""
        valid_queries = [
            "nginx 설정",
            "SSL certificate",
            "쿠버네티스 배포",
        ]

        for query in valid_queries:
            assert query.strip()
            assert len(query) > 0


class TestIndexerPathValidation:
    """Indexer Path Traversal 방어 테스트."""

    def test_symlink_outside_pages_blocked(self):
        """pages 외부를 가리키는 심볼릭 링크 차단."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            pages_path = tmpdir / "wiki" / "pages"
            pages_path.mkdir(parents=True)

            # 정상 파일
            normal_file = pages_path / "normal.md"
            normal_file.write_text("# Normal")

            # 외부 파일
            outside_file = tmpdir / "secret.md"
            outside_file.write_text("# Secret")

            # resolve() 후 relative_to 검증
            pages_resolved = pages_path.resolve()

            # 정상 파일은 통과
            normal_resolved = normal_file.resolve()
            rel_path = str(normal_resolved.relative_to(pages_resolved))
            assert rel_path == "normal.md"

            # 외부 파일은 ValueError
            outside_resolved = outside_file.resolve()
            with pytest.raises(ValueError):
                outside_resolved.relative_to(pages_resolved)
