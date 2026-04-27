"""Tests for core/models.py.

도메인 모델의 팩토리 메서드, 직렬화/역직렬화, 불변성을 테스트합니다.
"""

import pytest

from wiki_search_mcp.core.models import (
    Confidence,
    Document,
    SearchFilters,
    SearchResponse,
    SearchResult,
    ValidationIssue,
    ValidationReport,
    WikiStats,
)


class TestConfidence:
    """Confidence VO 테스트."""

    def test_of_creates_confidence(self):
        """of() 팩토리 메서드로 Confidence 생성."""
        conf = Confidence.of("high", 85, {"source": "test"})

        assert conf.level == "high"
        assert conf.score == 85
        assert ("source", "test") in conf.factors

    def test_from_dict_creates_confidence(self):
        """from_dict() 팩토리 메서드로 Confidence 생성."""
        data = {"level": "medium", "score": 50}
        conf = Confidence.from_dict(data)

        assert conf.level == "medium"
        assert conf.score == 50

    def test_to_dict_serializes(self):
        """to_dict()로 dict 변환."""
        conf = Confidence.of("low", 30)
        result = conf.to_dict()

        assert result == {"level": "low", "score": 30, "factors": {}}

    def test_frozen_raises_on_mutation(self):
        """frozen 속성으로 인해 변경 시 예외 발생."""
        conf = Confidence.of("high", 90)

        with pytest.raises(Exception):  # FrozenInstanceError
            conf.level = "low"


class TestValidationIssue:
    """ValidationIssue VO 테스트."""

    def test_of_creates_issue(self):
        """of() 팩토리 메서드로 ValidationIssue 생성."""
        issue = ValidationIssue.of("path/to/doc.md", "missing_title", "title 필드 없음")

        assert issue.path == "path/to/doc.md"
        assert issue.type == "missing_title"
        assert issue.message == "title 필드 없음"

    def test_to_dict_serializes(self):
        """to_dict()로 dict 변환."""
        issue = ValidationIssue.of("doc.md", "broken_link", "링크 깨짐")
        result = issue.to_dict()

        assert result == {
            "path": "doc.md",
            "type": "broken_link",
            "message": "링크 깨짐",
        }


class TestDocument:
    """Document 엔티티 테스트."""

    def test_from_dict_creates_document(self):
        """from_dict() 팩토리 메서드로 Document 생성."""
        data = {
            "path": "infra/nginx.md",
            "title": "Nginx 설정",
            "category": "infra",
            "tags": ["nginx", "web"],
            "summary": "Nginx 설정 방법",
            "state": "stable",
            "confidence_level": "high",
            "confidence_score": 90,
            "created": "2024-01-01",
            "updated": "2024-12-01",
        }
        doc = Document.from_dict(data)

        assert doc.path == "infra/nginx.md"
        assert doc.title == "Nginx 설정"
        assert doc.category == "infra"
        assert doc.tags == ("nginx", "web")
        assert doc.state == "stable"
        assert doc.confidence.level == "high"
        assert doc.confidence.score == 90

    def test_from_dict_with_defaults(self):
        """from_dict()에서 누락된 필드는 기본값 사용."""
        data = {"path": "test.md"}
        doc = Document.from_dict(data)

        assert doc.title == ""
        assert doc.category == "uncategorized"
        assert doc.tags == ()
        assert doc.state == "stable"

    def test_to_dict_serializes(self):
        """to_dict()로 dict 변환."""
        doc = Document.from_dict({
            "path": "test.md",
            "title": "Test",
            "category": "test",
            "tags": ["a"],
            "summary": "Summary",
            "state": "draft",
        })
        result = doc.to_dict()

        assert result["path"] == "test.md"
        assert result["tags"] == ["a"]  # tuple -> list


class TestSearchResult:
    """SearchResult VO 테스트."""

    def test_of_creates_search_result(self):
        """of() 팩토리 메서드로 SearchResult 생성."""
        doc = Document.from_dict({"path": "test.md", "title": "Test"})
        result = SearchResult.of(
            document=doc,
            similarity=0.95,
            related=["related1.md", "related2.md"],
            warning="deprecated",
        )

        assert result.document == doc
        assert result.similarity == 0.95
        assert result.related == ("related1.md", "related2.md")
        assert result.warning == "deprecated"

    def test_to_dict_includes_all_fields(self):
        """to_dict()는 document 필드를 펼쳐서 반환."""
        doc = Document.from_dict({"path": "test.md", "title": "Test"})
        result = SearchResult.of(doc, 0.8, ["r.md"])
        data = result.to_dict()

        assert data["path"] == "test.md"
        assert data["similarity"] == 0.8
        assert data["related"] == ["r.md"]


class TestSearchFilters:
    """SearchFilters VO 테스트."""

    def test_of_creates_filters(self):
        """of() 팩토리 메서드로 SearchFilters 생성."""
        filters = SearchFilters.of(
            include_states=["stable", "review"],
            category="infra",
            tags=["nginx"],
            confidence_min=50,
        )

        assert filters.include_states == ("stable", "review")
        assert filters.category == "infra"
        assert filters.tags == ("nginx",)
        assert filters.confidence_min == 50

    def test_default_states(self):
        """기본 상태 필터는 archived 제외."""
        filters = SearchFilters.of()

        assert "stable" in filters.include_states
        assert "archived" not in filters.include_states


class TestSearchResponse:
    """SearchResponse VO 테스트."""

    def test_of_creates_response(self):
        """of() 팩토리 메서드로 SearchResponse 생성."""
        doc = Document.from_dict({"path": "test.md", "title": "Test"})
        result = SearchResult.of(doc, 0.9)
        response = SearchResponse.of(
            results=[result],
            total_pages=100,
            query="test query",
            mode="hybrid",
        )

        assert len(response.results) == 1
        assert response.total_pages == 100
        assert response.query == "test query"
        assert response.mode == "hybrid"

    def test_to_dict_serializes(self):
        """to_dict()로 dict 변환."""
        response = SearchResponse.of(
            results=[],
            total_pages=0,
            query="",
            mode="vector",
            error="Index not found",
        )
        data = response.to_dict()

        assert data["error"] == "Index not found"
        assert data["mode"] == "vector"


class TestValidationReport:
    """ValidationReport Aggregate Root 테스트."""

    def test_create_builds_report(self):
        """create() 팩토리 메서드로 ValidationReport 생성."""
        issues = [
            ValidationIssue.of("a.md", "missing_title", "title 없음"),
            ValidationIssue.of("b.md", "broken_link", "링크 깨짐"),
        ]
        report = ValidationReport.create(
            status="warning",
            total=100,
            issues=issues,
            stats={"missing_title": 1, "broken_links": 1},
            summary={"complete": 98, "partial": 2},
        )

        assert report.status == "warning"
        assert report.total == 100
        assert len(report.issues) == 2

    def test_to_dict_serializes(self):
        """to_dict()로 dict 변환."""
        report = ValidationReport.create(
            status="valid",
            total=10,
            issues=[],
            stats={},
            summary={"complete": 10},
        )
        data = report.to_dict()

        assert data["status"] == "valid"
        assert data["summary"] == {"complete": 10}


class TestWikiStats:
    """WikiStats VO 테스트."""

    def test_create_builds_stats(self):
        """create() 팩토리 메서드로 WikiStats 생성."""
        stats = WikiStats.create(
            total_pages=150,
            by_category={"infra": 50, "dev": 100},
            by_state={"stable": 140, "draft": 10},
            by_confidence={"high": 100, "medium": 50},
            last_indexed="2024-12-01T10:00:00",
        )

        assert stats.total_pages == 150
        assert dict(stats.by_category) == {"infra": 50, "dev": 100}

    def test_from_dict_creates_stats(self):
        """from_dict() 팩토리 메서드로 WikiStats 생성."""
        data = {
            "total_pages": 50,
            "by_category": {"test": 50},
            "by_state": {"stable": 50},
            "by_confidence": {"high": 50},
            "last_indexed": None,
        }
        stats = WikiStats.from_dict(data)

        assert stats.total_pages == 50
        assert stats.last_indexed is None
