"""Tests for services/graph_service.py.

GraphService의 기능을 테스트합니다.
Mock Repository를 사용합니다.
"""

import pytest
from unittest.mock import MagicMock

from wiki_search_mcp.core.exceptions import InvalidPathError
from wiki_search_mcp.services.graph_service import GraphService


@pytest.fixture
def mock_graph_repo():
    """Mock GraphRepository."""
    repo = MagicMock()
    repo.get_backlinks.return_value = ["source1.md", "source2.md"]
    repo.get_all_paths.return_value = {"a.md", "b.md", "c.md"}
    repo.get_edges.return_value = [
        {"source": "a.md", "target": "b.md"},
        {"source": "b.md", "target": "c.md"},
    ]
    repo.get_neighbors.return_value = ["b.md", "c.md"]
    return repo


@pytest.fixture
def mock_vector_repo():
    """Mock VectorRepository."""
    repo = MagicMock()
    repo.find_by_path.side_effect = lambda path: {
        "path": path,
        "title": f"Title of {path}",
        "category": "test",
        "tags": [],
        "summary": "",
        "state": "stable",
    }
    return repo


class TestGraphService:
    """GraphService 테스트."""

    def test_get_backlinks_returns_documents(self, mock_graph_repo, mock_vector_repo):
        """get_backlinks()로 역링크 문서 조회."""
        service = GraphService(mock_graph_repo, mock_vector_repo)
        backlinks = service.get_backlinks("target.md")

        assert len(backlinks) == 2
        assert backlinks[0].path == "source1.md"
        mock_graph_repo.get_backlinks.assert_called_once_with("target.md")

    def test_get_backlinks_validates_path(self, mock_graph_repo, mock_vector_repo):
        """get_backlinks()에서 경로 검증."""
        service = GraphService(mock_graph_repo, mock_vector_repo)

        with pytest.raises(InvalidPathError):
            service.get_backlinks("../etc/passwd")

        with pytest.raises(InvalidPathError):
            service.get_backlinks("/absolute/path.md")

    def test_find_orphans_returns_unreferenced_docs(
        self, mock_graph_repo, mock_vector_repo
    ):
        """find_orphans()로 고아 문서 조회."""
        # a.md는 참조되지 않음 (edges에서 target이 아님)
        service = GraphService(mock_graph_repo, mock_vector_repo)
        orphans = service.find_orphans()

        # a.md만 고아 (b.md, c.md는 target으로 참조됨)
        orphan_paths = [o.path for o in orphans]
        assert "a.md" in orphan_paths

    def test_get_related_returns_neighbors(self, mock_graph_repo, mock_vector_repo):
        """get_related()로 관련 문서 조회."""
        service = GraphService(mock_graph_repo, mock_vector_repo)
        related = service.get_related("a.md", max_depth=2, limit=3)

        assert related == ["b.md", "c.md"]
        mock_graph_repo.get_neighbors.assert_called_once_with("a.md", 2)

    def test_get_related_respects_limit(self, mock_graph_repo, mock_vector_repo):
        """get_related()에서 limit 적용."""
        mock_graph_repo.get_neighbors.return_value = ["b.md", "c.md", "d.md", "e.md"]
        service = GraphService(mock_graph_repo, mock_vector_repo)

        related = service.get_related("a.md", limit=2)

        assert len(related) == 2
