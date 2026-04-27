"""Filters 테스트.

검색 결과 필터링 유틸리티를 테스트합니다.
"""

import pytest

from wiki_search_mcp.core.models import SearchFilters
from wiki_search_mcp.services.filters import (
    apply_filters,
    apply_simple_filters,
    passes_filters,
)


class TestPassesFilters:
    """passes_filters 테스트."""

    def test_default_filter_passes_stable(self):
        """기본 필터는 stable 상태 허용."""
        doc = {"state": "stable", "category": "infra", "tags": ["nginx"]}
        filters = SearchFilters.of()
        assert passes_filters(doc, filters) is True

    def test_state_filter_blocks_excluded(self):
        """명시적으로 제외된 상태는 차단."""
        doc = {"state": "deprecated", "category": "infra", "tags": ["nginx"]}
        # deprecated 제외
        filters = SearchFilters.of(include_states=["stable", "draft"])
        assert passes_filters(doc, filters) is False

    def test_state_filter_with_deprecated_included(self):
        """deprecated 포함 시 허용."""
        doc = {"state": "deprecated", "category": "infra", "tags": ["nginx"]}
        filters = SearchFilters.of(include_states=["stable", "draft", "deprecated"])
        assert passes_filters(doc, filters) is True

    def test_category_filter_matches(self):
        """카테고리 일치 시 통과."""
        doc = {"state": "stable", "category": "infra", "tags": ["nginx"]}
        filters = SearchFilters.of(category="infra")
        assert passes_filters(doc, filters) is True

    def test_category_filter_no_match(self):
        """카테고리 불일치 시 차단."""
        doc = {"state": "stable", "category": "dev", "tags": ["nginx"]}
        filters = SearchFilters.of(category="infra")
        assert passes_filters(doc, filters) is False

    def test_tags_filter_or_condition(self):
        """태그 OR 조건: 하나만 일치해도 통과."""
        doc = {"state": "stable", "category": "infra", "tags": ["nginx", "linux"]}
        filters = SearchFilters.of(tags=["nginx", "docker"])
        assert passes_filters(doc, filters) is True

    def test_tags_filter_no_match(self):
        """태그 불일치 시 차단."""
        doc = {"state": "stable", "category": "infra", "tags": ["apache"]}
        filters = SearchFilters.of(tags=["nginx", "docker"])
        assert passes_filters(doc, filters) is False

    def test_confidence_min_filter(self):
        """신뢰도 최솟값 필터."""
        doc_high = {"state": "stable", "confidence_score": 80}
        doc_low = {"state": "stable", "confidence_score": 30}
        filters = SearchFilters.of(confidence_min=50)

        assert passes_filters(doc_high, filters) is True
        assert passes_filters(doc_low, filters) is False

    def test_confidence_min_zero_passes_all(self):
        """신뢰도 0이면 모든 문서 통과."""
        doc = {"state": "stable", "confidence_score": 0}
        filters = SearchFilters.of(confidence_min=0)
        assert passes_filters(doc, filters) is True

    def test_missing_state_defaults_stable(self):
        """state 없으면 stable로 처리."""
        doc = {"category": "infra", "tags": ["nginx"]}
        filters = SearchFilters.of()
        assert passes_filters(doc, filters) is True


class TestApplyFilters:
    """apply_filters 테스트."""

    def test_apply_filters_basic(self):
        """필터 적용."""
        results = [
            {"state": "stable", "category": "infra"},
            {"state": "deprecated", "category": "infra"},
            {"state": "draft", "category": "dev"},
        ]
        # deprecated 제외
        filters = SearchFilters.of(include_states=["stable", "draft"])

        filtered = apply_filters(results, filters)
        assert len(filtered) == 2
        assert all(r["state"] != "deprecated" for r in filtered)

    def test_apply_filters_empty_input(self):
        """빈 입력."""
        filters = SearchFilters.of()
        filtered = apply_filters([], filters)
        assert filtered == []


class TestApplySimpleFilters:
    """apply_simple_filters 테스트."""

    def test_category_filter(self):
        """카테고리 필터."""
        results = [
            {"category": "infra", "state": "stable"},
            {"category": "dev", "state": "stable"},
        ]
        filtered = apply_simple_filters(results, category="infra")
        assert len(filtered) == 1
        assert filtered[0]["category"] == "infra"

    def test_tag_filter(self):
        """태그 필터 (단일)."""
        results = [
            {"tags": ["nginx", "linux"], "state": "stable"},
            {"tags": ["docker"], "state": "stable"},
        ]
        filtered = apply_simple_filters(results, tag="nginx")
        assert len(filtered) == 1
        assert "nginx" in filtered[0]["tags"]

    def test_state_filter(self):
        """상태 필터."""
        results = [
            {"state": "stable"},
            {"state": "deprecated"},
        ]
        filtered = apply_simple_filters(results, state="stable")
        assert len(filtered) == 1
        assert filtered[0]["state"] == "stable"

    def test_combined_filters(self):
        """복합 필터."""
        results = [
            {"category": "infra", "tags": ["nginx"], "state": "stable"},
            {"category": "infra", "tags": ["docker"], "state": "stable"},
            {"category": "dev", "tags": ["nginx"], "state": "stable"},
        ]
        filtered = apply_simple_filters(
            results, category="infra", tag="nginx", state="stable"
        )
        assert len(filtered) == 1
        assert filtered[0]["category"] == "infra"
        assert "nginx" in filtered[0]["tags"]

    def test_no_filters(self):
        """필터 없으면 전체 반환."""
        results = [
            {"category": "infra"},
            {"category": "dev"},
        ]
        filtered = apply_simple_filters(results)
        assert len(filtered) == 2
