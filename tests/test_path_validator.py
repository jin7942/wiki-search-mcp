"""PathValidator 테스트.

v0.2.6: 정규식 화이트리스트 제거. Path Traversal 방어는 명시적 블랙리스트
(``..``, ``/시작``, ``\\x00``, ``\\``, ``%``)와 ``_validate_within_base``의
resolve+is_relative_to 검증이 담당.
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
    """경로 검증 — 기본 화이트리스트."""

    def test_valid_simple_path(self):
        assert validate_path("docs/readme.md") == "docs/readme.md"

    def test_valid_path_without_extension(self):
        """확장자 없는 경로는 .md 추가."""
        assert validate_path("docs/readme") == "docs/readme.md"

    def test_valid_korean_path(self):
        assert validate_path("문서/가이드.md") == "문서/가이드.md"

    def test_valid_mixed_language_path(self):
        assert validate_path("docs/설정-guide.md") == "docs/설정-guide.md"

    def test_invalid_empty_path(self):
        with pytest.raises(InvalidPathError) as exc:
            validate_path("")
        assert exc.value.context.details["reason"] == "empty"

    def test_invalid_whitespace_only_path(self):
        with pytest.raises(InvalidPathError) as exc:
            validate_path("   ")
        assert exc.value.context.details["reason"] == "empty"

    def test_invalid_absolute_path(self):
        with pytest.raises(InvalidPathError) as exc:
            validate_path("/etc/passwd")
        assert exc.value.context.details["reason"] == "absolute"

    def test_invalid_path_traversal_double_dot(self):
        with pytest.raises(InvalidPathError) as exc:
            validate_path("../etc/passwd")
        assert exc.value.context.details["reason"] == "parent_traversal"

        with pytest.raises(InvalidPathError) as exc:
            validate_path("docs/../../../etc/passwd")
        assert exc.value.context.details["reason"] == "parent_traversal"


class TestPathValidatorWithBaseDir:
    """base_dir 포함 경로 검증 — resolve 기반 traversal 방어."""

    def test_valid_path_within_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "docs").mkdir()
            (base / "docs" / "readme.md").touch()
            result = validate_path("docs/readme.md", base)
            assert result == "docs/readme.md"

    def test_invalid_path_outside_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "wiki"
            base.mkdir()
            # raw로 ..가 안 들어가지만 symlink/cross-mount 등에서 resolve가
            # base 밖으로 빠질 수 있는 시나리오를 시뮬레이션하기 위해
            # symlink로 외부를 가리키게 한다.
            outside = Path(tmpdir) / "outside"
            outside.mkdir()
            (base / "escape").symlink_to(outside)
            with pytest.raises(InvalidPathError) as exc:
                validate_path("escape/secret.md", base)
            assert exc.value.context.details["reason"] == "outside_base"


class TestUnicodePathSupport:
    """v0.2.6: OS상 정상인 유니코드 파일명은 모두 허용."""

    def test_japanese_path(self):
        assert validate_path("ドキュメント/ガイド.md") == "ドキュメント/ガイド.md"

    def test_chinese_path(self):
        assert validate_path("文档/指南.md") == "文档/指南.md"

    def test_emoji_path_now_allowed(self):
        """v0.2.5까지는 거부했지만 OS가 받아주는 정상 파일명이므로 허용."""
        assert validate_path("docs/📚readme.md") == "docs/📚readme.md"

    def test_space_in_filename_allowed(self):
        """v0.2.6 회귀 핵심: 한국어 공백 포함 파일명이 traversal로 오인되지 않아야 함.

        장애 보고서의 실제 케이스: ``inbox/한수원 안전관리 SER 제안서.md``.
        """
        assert (
            validate_path("inbox/한수원 안전관리 SER 제안서.md")
            == "inbox/한수원 안전관리 SER 제안서.md"
        )

    def test_parentheses_brackets_allowed(self):
        assert validate_path("notes/(draft) memo.md") == "notes/(draft) memo.md"
        assert validate_path("notes/[v1] note.md") == "notes/[v1] note.md"

    def test_apostrophe_allowed(self):
        assert validate_path("notes/user's note.md") == "notes/user's note.md"

    def test_semicolon_now_allowed(self):
        """세미콜론은 OS상 정상 파일명. 명령어 인젝션 방어는 shell 호출 시점의 책임."""
        assert validate_path("docs/file;backup.md") == "docs/file;backup.md"

    def test_pipe_now_allowed(self):
        assert validate_path("docs/a|b.md") == "docs/a|b.md"

    def test_fullwidth_chars_pass_through(self):
        """전각 마침표/슬래시는 OS상 별개 코드포인트로 처리되어 traversal 위험 없음.

        ``..`` raw 매치는 이들에 매칭되지 않고 (``\\uff0e\\uff0e`` != ``..``),
        ``_validate_within_base``의 resolve도 이를 디렉토리 이름으로 취급한다.
        """
        # 전각 문자 포함은 통과 (base_dir 없을 때)
        assert validate_path("docs/．．/etc.md") == "docs/．．/etc.md"


class TestPathTraversalAttacks:
    """명시 블랙리스트로 거부되는 traversal 시퀀스."""

    def test_url_encoded_slash_rejected(self):
        with pytest.raises(InvalidPathError) as exc:
            validate_path("docs%2f..%2f..%2fetc/passwd")
        # raw .. 와 % 가 모두 있으므로 검사 순서상 둘 중 하나로 잡힘
        assert exc.value.context.details["reason"] in {"percent_encoded", "parent_traversal"}

    def test_url_encoded_double_dot_rejected(self):
        with pytest.raises(InvalidPathError) as exc:
            validate_path("docs/%2e%2e/etc/passwd")
        # %2e%2e는 .. 매치보다 % 매치가 먼저 잡힘 (검사 순서)
        # 단 docs/.. 부분의 raw `..`가 먼저 잡힐 수도 있어 둘 중 하나면 OK.
        assert exc.value.context.details["reason"] in {"percent_encoded", "parent_traversal"}

    def test_percent_in_normal_filename_rejected(self):
        """v0.2.6: % 자체가 거부 대상. ``사용률 95%.md`` 같은 정상 사용 파일도 거부.

        보수적 안전 선택. 사용자가 % 쓰는 경우 percent 또는 다른 표기로 대체 권장.
        """
        with pytest.raises(InvalidPathError) as exc:
            validate_path("docs/사용률 95%.md")
        assert exc.value.context.details["reason"] == "percent_encoded"

    def test_null_byte_injection(self):
        with pytest.raises(InvalidPathError) as exc:
            validate_path("docs/readme\x00.md")
        assert exc.value.context.details["reason"] == "null_byte"

    def test_null_byte_in_middle(self):
        """``\\x00`` 검사가 raw ``..`` 검사보다 뒤에 있으므로 ``..``가 함께 있으면
        parent_traversal로 먼저 잡힌다. 둘 중 하나로 거부되면 OK."""
        with pytest.raises(InvalidPathError) as exc:
            validate_path("docs\x00/../etc/passwd")
        assert exc.value.context.details["reason"] in {"null_byte", "parent_traversal"}

    def test_backslash_path_rejected(self):
        with pytest.raises(InvalidPathError) as exc:
            validate_path("docs\\..\\..\\etc\\passwd")
        # 검사 순서상 `..`이 먼저 매치되거나 `\\`이 매치됨
        assert exc.value.context.details["reason"] in {"parent_traversal", "backslash"}

    def test_backslash_mixed_with_slash_rejected(self):
        with pytest.raises(InvalidPathError) as exc:
            validate_path("docs\\readme/test.md")
        assert exc.value.context.details["reason"] == "backslash"

    def test_double_url_encoding_rejected(self):
        with pytest.raises(InvalidPathError) as exc:
            validate_path("docs%252f..%252fetc/passwd")
        assert exc.value.context.details["reason"] in {"percent_encoded", "parent_traversal"}

    def test_mixed_encoding_attack_rejected(self):
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

    def test_control_characters_pass_or_blocked(self):
        """v0.2.6: 제어 문자는 OS 정상 코드포인트이므로 명시 블랙리스트에 없음.

        단 ``\\r\\n``과 같이 사용 시 화면 표시가 깨질 수 있다는 우려는 별개 이슈.
        path validator 책임 아님 — base_dir이 주어지면 resolve 단계에서 차단되거나
        통과한다. 본 테스트는 명시적으로 거부되지 않음을 확인.
        """
        result = validate_path("docs/readme\t.md")
        assert "\t" in result


class TestQueryValidator:
    """validate_path_for_query — .md 정규화 / base_dir 없음."""

    def test_query_does_not_add_md_extension(self):
        """쿼리용은 확장자 정규화 안 함."""
        assert validate_path_for_query("docs/readme") == "docs/readme"

    def test_query_strips_whitespace(self):
        assert validate_path_for_query("  docs/x.md  ") == "docs/x.md"

    def test_query_rejects_empty(self):
        with pytest.raises(InvalidPathError) as exc:
            validate_path_for_query("")
        assert exc.value.context.details["reason"] == "empty"

    def test_query_rejects_parent_traversal(self):
        with pytest.raises(InvalidPathError) as exc:
            validate_path_for_query("../etc")
        assert exc.value.context.details["reason"] == "parent_traversal"


class TestErrorMessageHasReason:
    """모든 InvalidPathError가 reason을 details에 포함해야 한다 (v0.2.6 회귀)."""

    @pytest.mark.parametrize(
        "path,expected_reason",
        [
            ("", "empty"),
            ("   ", "empty"),
            ("/abs", "absolute"),
            ("../x", "parent_traversal"),
            ("x\x00", "null_byte"),
            ("x\\y", "backslash"),
            ("x%2fy", "percent_encoded"),
        ],
    )
    def test_each_branch_sets_reason(self, path: str, expected_reason: str):
        with pytest.raises(InvalidPathError) as exc:
            validate_path(path)
        assert exc.value.context.details["reason"] == expected_reason

    def test_backward_compat_reason_none(self):
        """``InvalidPathError.of(path)``로 인자 1개 호출이 여전히 동작해야 한다."""
        err = InvalidPathError.of("legacy/x.md")
        assert err.context.details["path"] == "legacy/x.md"
        assert err.context.details["reason"] is None
        assert "Path traversal attempt" in str(err)
