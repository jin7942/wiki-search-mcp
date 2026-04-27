"""Validators 테스트.

입력 검증 유틸리티 함수들을 테스트합니다.
"""

import pytest

from wiki_search_mcp.core.validators import (
    validate_confidence_min,
    validate_limit,
    validate_path_required,
    validate_preview_size,
    validate_query,
    validate_search_mode,
    validate_sort_by,
    validate_sort_order,
    validate_top_k,
)


class TestValidateTopK:
    """validate_top_k 테스트."""

    def test_within_range(self):
        """범위 내 값은 그대로 반환."""
        assert validate_top_k(1) == 1
        assert validate_top_k(50) == 50
        assert validate_top_k(100) == 100

    def test_below_min(self):
        """최솟값 미만은 최솟값으로."""
        assert validate_top_k(0) == 1
        assert validate_top_k(-10) == 1

    def test_above_max(self):
        """최댓값 초과는 최댓값으로."""
        assert validate_top_k(150) == 100
        assert validate_top_k(1000) == 100

    def test_custom_range(self):
        """커스텀 범위."""
        assert validate_top_k(5, min_val=10, max_val=20) == 10
        assert validate_top_k(25, min_val=10, max_val=20) == 20
        assert validate_top_k(15, min_val=10, max_val=20) == 15


class TestValidateLimit:
    """validate_limit 테스트."""

    def test_within_range(self):
        """범위 내 값은 그대로 반환."""
        assert validate_limit(50) == 50
        assert validate_limit(500) == 500

    def test_below_min(self):
        """최솟값 미만은 최솟값으로."""
        assert validate_limit(0) == 1

    def test_above_max(self):
        """최댓값 초과는 최댓값으로."""
        assert validate_limit(1000) == 500


class TestValidatePreviewSize:
    """validate_preview_size 테스트."""

    def test_within_range(self):
        """범위 내 값은 그대로 반환."""
        assert validate_preview_size(500) == 500
        assert validate_preview_size(0) == 0

    def test_above_max(self):
        """최댓값 초과는 최댓값으로."""
        assert validate_preview_size(5000) == 2000


class TestValidateConfidenceMin:
    """validate_confidence_min 테스트."""

    def test_within_range(self):
        """범위 내 값은 그대로 반환."""
        assert validate_confidence_min(50) == 50
        assert validate_confidence_min(0) == 0
        assert validate_confidence_min(100) == 100

    def test_below_min(self):
        """최솟값 미만은 최솟값으로."""
        assert validate_confidence_min(-10) == 0

    def test_above_max(self):
        """최댓값 초과는 최댓값으로."""
        assert validate_confidence_min(150) == 100


class TestValidateQuery:
    """validate_query 테스트."""

    def test_valid_query(self):
        """유효한 쿼리는 strip 후 반환."""
        assert validate_query("hello") == "hello"
        assert validate_query("  hello  ") == "hello"

    def test_empty_query_raises(self):
        """빈 쿼리는 ValueError."""
        with pytest.raises(ValueError, match="Query cannot be empty"):
            validate_query("")

    def test_whitespace_only_raises(self):
        """공백만 있으면 ValueError."""
        with pytest.raises(ValueError, match="Query cannot be empty"):
            validate_query("   ")

    def test_none_query_raises(self):
        """None 쿼리는 ValueError."""
        with pytest.raises(ValueError, match="Query cannot be empty"):
            validate_query(None)


class TestValidatePathRequired:
    """validate_path_required 테스트."""

    def test_valid_path(self):
        """유효한 경로는 strip 후 반환."""
        assert validate_path_required("docs/readme.md") == "docs/readme.md"
        assert validate_path_required("  docs/readme.md  ") == "docs/readme.md"

    def test_empty_path_raises(self):
        """빈 경로는 ValueError."""
        with pytest.raises(ValueError, match="Path cannot be empty"):
            validate_path_required("")

    def test_whitespace_only_raises(self):
        """공백만 있으면 ValueError."""
        with pytest.raises(ValueError, match="Path cannot be empty"):
            validate_path_required("   ")


class TestValidateSearchMode:
    """validate_search_mode 테스트."""

    def test_valid_modes(self):
        """유효한 모드는 그대로 반환."""
        assert validate_search_mode("hybrid") == "hybrid"
        assert validate_search_mode("vector") == "vector"
        assert validate_search_mode("keyword") == "keyword"

    def test_invalid_mode_defaults(self):
        """잘못된 모드는 hybrid로."""
        assert validate_search_mode("invalid") == "hybrid"
        assert validate_search_mode("") == "hybrid"


class TestValidateSortBy:
    """validate_sort_by 테스트."""

    def test_valid_values(self):
        """유효한 값은 그대로 반환."""
        assert validate_sort_by("similarity") == "similarity"
        assert validate_sort_by("confidence") == "confidence"
        assert validate_sort_by("updated") == "updated"
        assert validate_sort_by("title") == "title"

    def test_invalid_defaults(self):
        """잘못된 값은 similarity로."""
        assert validate_sort_by("invalid") == "similarity"
        assert validate_sort_by("") == "similarity"


class TestValidateSortOrder:
    """validate_sort_order 테스트."""

    def test_valid_values(self):
        """유효한 값은 그대로 반환."""
        assert validate_sort_order("asc") == "asc"
        assert validate_sort_order("desc") == "desc"

    def test_invalid_defaults(self):
        """잘못된 값은 desc로."""
        assert validate_sort_order("invalid") == "desc"
        assert validate_sort_order("") == "desc"
