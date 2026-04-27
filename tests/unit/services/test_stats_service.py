"""Tests for services/stats_service.py.

StatsService의 기능을 테스트합니다.
Mock Repository를 사용합니다.
"""

import pytest
from unittest.mock import MagicMock

from wiki_search_mcp.services.stats_service import StatsService


@pytest.fixture
def mock_vector_repo():
    """Mock VectorRepository."""
    repo = MagicMock()
    repo.exists.return_value = True
    repo.to_arrow_list.return_value = [
        {"category": "infra", "state": "stable", "confidence_level": "high"},
        {"category": "infra", "state": "stable", "confidence_level": "high"},
        {"category": "dev", "state": "draft", "confidence_level": "medium"},
        {"category": "dev", "state": "stable", "confidence_level": "low"},
    ]
    return repo


@pytest.fixture
def mock_meta_repo():
    """Mock MetaRepository."""
    repo = MagicMock()
    repo.get_last_indexed.return_value = "2024-12-01T10:00:00"
    return repo


class TestStatsService:
    """StatsService 테스트."""

    def test_get_stats_returns_wiki_stats(self, mock_vector_repo, mock_meta_repo):
        """get_stats()로 WikiStats 생성."""
        service = StatsService(mock_vector_repo, mock_meta_repo)
        stats = service.get_stats()

        assert stats.total_pages == 4
        assert stats.last_indexed == "2024-12-01T10:00:00"

    def test_get_stats_counts_by_category(self, mock_vector_repo, mock_meta_repo):
        """카테고리별 집계."""
        service = StatsService(mock_vector_repo, mock_meta_repo)
        stats = service.get_stats()

        by_category = dict(stats.by_category)
        assert by_category["infra"] == 2
        assert by_category["dev"] == 2

    def test_get_stats_counts_by_state(self, mock_vector_repo, mock_meta_repo):
        """상태별 집계."""
        service = StatsService(mock_vector_repo, mock_meta_repo)
        stats = service.get_stats()

        by_state = dict(stats.by_state)
        assert by_state["stable"] == 3
        assert by_state["draft"] == 1

    def test_get_stats_counts_by_confidence(self, mock_vector_repo, mock_meta_repo):
        """신뢰도별 집계."""
        service = StatsService(mock_vector_repo, mock_meta_repo)
        stats = service.get_stats()

        by_confidence = dict(stats.by_confidence)
        assert by_confidence["high"] == 2
        assert by_confidence["medium"] == 1
        assert by_confidence["low"] == 1

    def test_get_stats_on_empty_index(self, mock_vector_repo, mock_meta_repo):
        """빈 인덱스에서 통계 조회."""
        mock_vector_repo.exists.return_value = False

        service = StatsService(mock_vector_repo, mock_meta_repo)
        stats = service.get_stats()

        assert stats.total_pages == 0
        assert stats.last_indexed is None

    def test_to_dict_serializes_correctly(self, mock_vector_repo, mock_meta_repo):
        """to_dict()로 dict 변환."""
        service = StatsService(mock_vector_repo, mock_meta_repo)
        stats = service.get_stats()
        data = stats.to_dict()

        assert "total_pages" in data
        assert "by_category" in data
        assert isinstance(data["by_category"], dict)
