"""Tests for services/validation_service.py.

ValidationService의 기능을 테스트합니다.
Mock Repository를 사용합니다.
"""

import pytest
from unittest.mock import MagicMock

from wiki_search_mcp.services.validation_service import ValidationService


@pytest.fixture
def mock_vector_repo():
    """Mock VectorRepository."""
    repo = MagicMock()
    repo.exists.return_value = True
    repo.find_all.return_value = [
        {
            "path": "complete.md",
            "title": "Complete Doc",
            "category": "test",
            "tags": ["tag1"],
            "state": "stable",
            "confidence_score": 80,
            "confidence_level": "high",
            "created": "2024-01-01",
            "updated": "2024-12-01",
        },
        {
            "path": "partial.md",
            "title": "Partial Doc",
            "category": "test",
            "tags": [],  # missing
            "state": "stable",
            "confidence_score": 50,
            "confidence_level": "medium",
            "created": "",  # missing
            "updated": "",  # missing
        },
    ]
    return repo


@pytest.fixture
def mock_graph_repo():
    """Mock GraphRepository."""
    repo = MagicMock()
    repo.get_edges.return_value = [
        {"source": "complete.md", "target": "partial.md"},
    ]
    return repo


class TestValidationService:
    """ValidationService 테스트."""

    def test_validate_returns_report(self, mock_vector_repo, mock_graph_repo):
        """validate()로 검증 리포트 생성."""
        service = ValidationService(mock_vector_repo, mock_graph_repo)
        report = service.validate()

        assert report.total == 2
        assert report.status in ["valid", "warning", "error"]

    def test_validate_detects_missing_tags(self, mock_vector_repo, mock_graph_repo):
        """누락된 tags 감지."""
        service = ValidationService(mock_vector_repo, mock_graph_repo)
        report = service.validate()

        # partial.md에 tags가 없음
        missing_tags_issues = [
            i for i in report.issues if i.type == "missing_tags"
        ]
        assert len(missing_tags_issues) == 1
        assert missing_tags_issues[0].path == "partial.md"

    def test_validate_counts_complete_partial(self, mock_vector_repo, mock_graph_repo):
        """complete/partial 문서 카운트."""
        service = ValidationService(mock_vector_repo, mock_graph_repo)
        report = service.validate()

        summary = dict(report.summary)
        assert summary["complete"] >= 1
        # partial.md는 3개 필드 누락 (tags, created, updated)
        # NO_FRONTMATTER_FIELD_THRESHOLD(5)보다 적으므로 partial

    def test_validate_on_empty_index_returns_error(
        self, mock_vector_repo, mock_graph_repo
    ):
        """빈 인덱스는 error 상태."""
        mock_vector_repo.exists.return_value = False

        service = ValidationService(mock_vector_repo, mock_graph_repo)
        report = service.validate()

        assert report.status == "error"
        assert report.total == 0

    def test_validate_detects_broken_links(self, mock_vector_repo, mock_graph_repo):
        """깨진 wikilink 감지."""
        mock_graph_repo.get_edges.return_value = [
            {"source": "complete.md", "target": "nonexistent.md"},
        ]

        service = ValidationService(mock_vector_repo, mock_graph_repo)
        report = service.validate()

        broken_link_issues = [i for i in report.issues if i.type == "broken_link"]
        assert len(broken_link_issues) == 1


class TestValidationServiceEdgeCases:
    """ValidationService 엣지 케이스 테스트."""

    def test_missing_title_when_equals_path(self):
        """title이 path와 같으면 누락으로 간주."""
        mock_vector_repo = MagicMock()
        mock_vector_repo.exists.return_value = True
        mock_vector_repo.find_all.return_value = [
            {
                "path": "no-title.md",
                "title": "no-title.md",  # path와 동일
                "category": "test",
                "tags": ["tag"],
                "state": "stable",
                "confidence_score": 80,
                "confidence_level": "high",
            },
        ]

        mock_graph_repo = MagicMock()
        mock_graph_repo.get_edges.return_value = []

        service = ValidationService(mock_vector_repo, mock_graph_repo)
        report = service.validate()

        missing_title = [i for i in report.issues if i.type == "missing_title"]
        assert len(missing_title) == 1


class TestFieldRules:
    """선언적 필드 규칙 테이블(_FIELD_RULES) 술어 검증."""

    def test_title_missing_predicate(self):
        from wiki_search_mcp.services.validation_service import _title_missing

        assert _title_missing({"path": "a.md", "title": ""}) is True
        # title == path stem 이면 누락 간주
        assert _title_missing({"path": "a.md", "title": "a"}) is True
        assert _title_missing({"path": "a.md", "title": "Real Title"}) is False

    def test_confidence_missing_predicate(self):
        from wiki_search_mcp.services.validation_service import _confidence_missing

        # score 0 + level low → 누락
        assert _confidence_missing(
            {"confidence_score": 0, "confidence_level": "low"}
        ) is True
        # 기본값(50, medium) → 누락 아님
        assert _confidence_missing({}) is False
        assert _confidence_missing(
            {"confidence_score": 80, "confidence_level": "high"}
        ) is False

    def test_rule_table_covers_expected_fields(self):
        """규칙 테이블이 기대 issue type 을 모두 포함."""
        from wiki_search_mcp.services.validation_service import _FIELD_RULES

        types = {r.issue_type for r in _FIELD_RULES if r.issue_type}
        assert types == {
            "missing_title",
            "missing_state",
            "missing_tags",
            "missing_confidence",
        }
        # created/updated 는 issue_type=None(통계 전용) 규칙 2개
        none_rules = [r for r in _FIELD_RULES if r.issue_type is None]
        assert len(none_rules) == 2
