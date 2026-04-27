"""PathValidator 테스트.

Path Traversal 공격 방어 및 경로 정규화를 테스트합니다.
"""

import tempfile
from pathlib import Path

import pytest

from wiki_search_mcp.core.exceptions import InvalidPathError
from wiki_search_mcp.core.path_validator import (
    validate_path,
    validate_path_for_query,
)


class TestPathValidator:
    """경로 검증 테스트."""

    def test_valid_simple_path(self):
        """유효한 단순 경로."""
        result = validate_path("docs/readme.md")
        assert result == "docs/readme.md"

    def test_valid_path_without_extension(self):
        """확장자 없는 경로는 .md 추가."""
        result = validate_path("docs/readme")
        assert result == "docs/readme.md"

    def test_valid_korean_path(self):
        """한글 경로 허용."""
        result = validate_path("문서/가이드.md")
        assert result == "문서/가이드.md"

    def test_valid_mixed_language_path(self):
        """혼합 언어 경로 허용."""
        result = validate_path("docs/설정-guide.md")
        assert result == "docs/설정-guide.md"

    def test_invalid_empty_path(self):
        """빈 경로는 에러."""
        with pytest.raises(InvalidPathError):
            validate_path("")

    def test_invalid_whitespace_only_path(self):
        """공백만 있는 경로는 에러."""
        with pytest.raises(InvalidPathError):
            validate_path("   ")

    def test_invalid_absolute_path(self):
        """절대 경로는 에러."""
        with pytest.raises(InvalidPathError):
            validate_path("/etc/passwd")

    def test_invalid_path_traversal_double_dot(self):
        """.. 포함 경로는 에러."""
        with pytest.raises(InvalidPathError):
            validate_path("../etc/passwd")

        with pytest.raises(InvalidPathError):
            validate_path("docs/../../../etc/passwd")

    def test_invalid_special_characters(self):
        """특수문자 포함 경로는 에러."""
        with pytest.raises(InvalidPathError):
            validate_path("docs/file;rm -rf.md")

        with pytest.raises(InvalidPathError):
            validate_path("docs/file|cat /etc/passwd.md")


class TestPathValidatorWithBaseDir:
    """base_dir 포함 경로 검증 테스트."""

    def test_valid_path_within_base(self):
        """base_dir 내부 경로 허용."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "docs").mkdir()
            (base / "docs" / "readme.md").touch()

            result = validate_path("docs/readme.md", base)
            assert result == "docs/readme.md"

    def test_invalid_path_outside_base(self):
        """base_dir 외부 경로는 에러."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "wiki"
            base.mkdir()

            # 상위 디렉토리로 탈출 시도
            with pytest.raises(InvalidPathError):
                validate_path("../outside.md", base)


class TestPathValidatorForQuery:
    """쿼리용 경로 검증 테스트."""

    def test_valid_query_path(self):
        """유효한 쿼리 경로."""
        result = validate_path_for_query("docs/readme.md")
        assert result == "docs/readme.md"

    def test_query_path_no_extension_normalization(self):
        """쿼리 경로는 확장자 정규화 없음."""
        result = validate_path_for_query("docs/readme")
        assert result == "docs/readme"  # .md 추가 안 함

    def test_invalid_query_path_traversal(self):
        """쿼리 경로에서도 Path Traversal 방어."""
        with pytest.raises(InvalidPathError):
            validate_path_for_query("../etc/passwd")

    def test_invalid_query_path_absolute(self):
        """쿼리 경로에서도 절대 경로 거부."""
        with pytest.raises(InvalidPathError):
            validate_path_for_query("/etc/passwd")


class TestPathValidatorUnicode:
    """유니코드 경로 테스트."""

    def test_japanese_path(self):
        """일본어 경로 허용."""
        result = validate_path("ドキュメント/ガイド.md")
        assert result == "ドキュメント/ガイド.md"

    def test_chinese_path(self):
        """중국어 경로 허용."""
        result = validate_path("文档/指南.md")
        assert result == "文档/指南.md"

    def test_emoji_path_rejected(self):
        """이모지 경로는 거부."""
        with pytest.raises(InvalidPathError):
            validate_path("docs/📚readme.md")


class TestPathTraversalAttacks:
    """Path Traversal 공격 시나리오 테스트.

    다양한 우회 기법을 테스트하여 보안 취약점을 방지합니다.
    """

    def test_url_encoded_slash(self):
        """URL 인코딩된 슬래시(%2f) 거부.

        Note:
            현재 구현은 허용 문자 패턴에서 % 문자를 허용하지 않으므로
            자연스럽게 거부됩니다.
        """
        with pytest.raises(InvalidPathError):
            validate_path("docs%2f..%2f..%2fetc/passwd")

    def test_url_encoded_double_dot(self):
        """URL 인코딩된 .. (%2e%2e) 거부."""
        with pytest.raises(InvalidPathError):
            validate_path("docs/%2e%2e/etc/passwd")

    def test_null_byte_injection(self):
        """널 바이트(\x00) 주입 거부.

        Note:
            널 바이트는 C 언어 기반 시스템에서 문자열 종료로 해석되어
            경로 우회에 사용될 수 있습니다.
        """
        with pytest.raises(InvalidPathError):
            validate_path("docs/readme\x00.md")

    def test_null_byte_in_middle(self):
        """경로 중간의 널 바이트 거부."""
        with pytest.raises(InvalidPathError):
            validate_path("docs\x00/../etc/passwd")

    def test_backslash_path(self):
        """백슬래시(\\) 경로 거부.

        Note:
            Windows 스타일 경로 구분자는 Unix 시스템에서
            Path Traversal에 악용될 수 있습니다.
        """
        with pytest.raises(InvalidPathError):
            validate_path("docs\\..\\..\\etc\\passwd")

    def test_backslash_mixed_with_slash(self):
        """백슬래시와 슬래시 혼용 거부."""
        with pytest.raises(InvalidPathError):
            validate_path("docs\\readme/test.md")

    def test_unicode_fullwidth_dot(self):
        """유니코드 전각 마침표(U+FF0E) 거부.

        Note:
            U+FF0E (FULLWIDTH FULL STOP)는 일부 시스템에서
            일반 마침표로 정규화될 수 있어 .. 우회에 사용됩니다.
        """
        with pytest.raises(InvalidPathError):
            validate_path("docs/\uff0e\uff0e/etc/passwd")

    def test_unicode_fullwidth_slash(self):
        """유니코드 전각 슬래시(U+FF0F) 거부."""
        with pytest.raises(InvalidPathError):
            validate_path("docs\uff0f..\uff0fetc/passwd")

    def test_unicode_fraction_slash(self):
        """유니코드 분수 슬래시(U+2215) 거부."""
        with pytest.raises(InvalidPathError):
            validate_path("docs\u2215..\u2215etc/passwd")

    def test_double_url_encoding(self):
        """이중 URL 인코딩(%252f = %2f) 거부."""
        with pytest.raises(InvalidPathError):
            validate_path("docs%252f..%252fetc/passwd")

    def test_mixed_encoding_attack(self):
        """혼합 인코딩 공격 거부."""
        with pytest.raises(InvalidPathError):
            validate_path("docs/..%2f..%2fetc/passwd")

    def test_dot_dot_slash_variations(self):
        """다양한 .. 변형 거부."""
        attack_patterns = [
            "../",
            "..\\",
            ".../",
            "....//",
            "..;/",
            "..%00/",
            "..%0d/",
            "..%0a/",
        ]
        for pattern in attack_patterns:
            with pytest.raises(InvalidPathError):
                validate_path(f"docs/{pattern}etc/passwd")

    def test_control_characters(self):
        """제어 문자 거부."""
        control_chars = ["\r", "\n", "\t", "\v", "\f"]
        for char in control_chars:
            with pytest.raises(InvalidPathError):
                validate_path(f"docs/readme{char}.md")

    def test_semicolon_injection(self):
        """세미콜론 주입 거부.

        Note:
            일부 시스템에서 세미콜론은 명령어 구분자로 사용됩니다.
        """
        with pytest.raises(InvalidPathError):
            validate_path("docs/readme;rm -rf /.md")

    def test_pipe_injection(self):
        """파이프(|) 주입 거부."""
        with pytest.raises(InvalidPathError):
            validate_path("docs/readme|cat /etc/passwd.md")
