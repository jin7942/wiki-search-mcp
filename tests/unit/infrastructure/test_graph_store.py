"""Tests for infrastructure/storage/graph_store.py.

JSON 그래프 스토어의 기능을 테스트합니다.
외부 의존성 없이 테스트 가능합니다.
"""

import json

import pytest

# 직접 import (외부 의존성 없음)
from wiki_search_mcp.infrastructure.storage.graph_store import JsonGraphStore


@pytest.fixture
def temp_graph(tmp_path):
    """임시 그래프 생성."""
    db_path = tmp_path / ".vectordb"
    db_path.mkdir()

    # 그래프 생성: A -> B -> C, A -> D
    graph_data = {
        "nodes": [
            {"id": "a.md"},
            {"id": "b.md"},
            {"id": "c.md"},
            {"id": "d.md"},
        ],
        "edges": [
            {"source": "a.md", "target": "b.md"},
            {"source": "b.md", "target": "c.md"},
            {"source": "a.md", "target": "d.md"},
        ],
    }
    (db_path / "graph.json").write_text(json.dumps(graph_data), encoding="utf-8")

    return db_path


class TestJsonGraphStore:
    """JsonGraphStore 테스트."""

    def test_get_neighbors_returns_connected_nodes(self, temp_graph):
        """get_neighbors()로 연결된 노드 조회."""
        store = JsonGraphStore(temp_graph)
        neighbors = store.get_neighbors("a.md", max_depth=1)

        assert set(neighbors) == {"b.md", "d.md"}

    def test_get_neighbors_respects_max_depth(self, temp_graph):
        """max_depth에 따라 탐색 깊이 제한."""
        store = JsonGraphStore(temp_graph)

        # depth=1: b, d만
        neighbors_1 = store.get_neighbors("a.md", max_depth=1)
        assert "c.md" not in neighbors_1

        # depth=2: b, d, c까지
        neighbors_2 = store.get_neighbors("a.md", max_depth=2)
        assert "c.md" in neighbors_2

    def test_get_neighbors_returns_distance_sorted(self, temp_graph):
        """거리순 정렬."""
        store = JsonGraphStore(temp_graph)
        neighbors = store.get_neighbors("a.md", max_depth=2)

        # 가까운 노드가 먼저 (b, d는 거리 1, c는 거리 2)
        assert neighbors.index("c.md") > neighbors.index("b.md")

    def test_get_backlinks_returns_sources(self, temp_graph):
        """get_backlinks()로 역링크 조회."""
        store = JsonGraphStore(temp_graph)
        backlinks = store.get_backlinks("b.md")

        assert "a.md" in backlinks

    def test_get_backlinks_handles_md_extension(self, temp_graph):
        """.md 확장자 유무 모두 매칭."""
        store = JsonGraphStore(temp_graph)

        # 확장자 없이 조회해도 매칭
        backlinks_without_ext = store.get_backlinks("b")
        backlinks_with_ext = store.get_backlinks("b.md")

        # 둘 다 a.md를 포함해야 함 (edge target이 "b.md"이므로)
        assert "a.md" in backlinks_with_ext

    def test_get_all_paths_returns_all_nodes(self, temp_graph):
        """get_all_paths()로 모든 노드 경로."""
        store = JsonGraphStore(temp_graph)
        paths = store.get_all_paths()

        assert paths == {"a.md", "b.md", "c.md", "d.md"}

    def test_get_edges_returns_all_edges(self, temp_graph):
        """get_edges()로 모든 엣지."""
        store = JsonGraphStore(temp_graph)
        edges = store.get_edges()

        assert len(edges) == 3

    def test_node_count_and_edge_count(self, temp_graph):
        """node_count, edge_count 속성."""
        store = JsonGraphStore(temp_graph)

        assert store.node_count == 4
        assert store.edge_count == 3

    def test_reload_refreshes_graph(self, temp_graph):
        """reload() 후 그래프 갱신."""
        store = JsonGraphStore(temp_graph)

        # 그래프 파일 수정
        new_graph = {"nodes": [{"id": "new.md"}], "edges": []}
        (temp_graph / "graph.json").write_text(json.dumps(new_graph), encoding="utf-8")

        store.reload()

        assert store.node_count == 1


class TestJsonGraphStoreEmpty:
    """빈 스토어 테스트."""

    def test_empty_graph_on_missing_file(self, tmp_path):
        """파일 없으면 빈 그래프."""
        db_path = tmp_path / ".vectordb"
        db_path.mkdir()

        store = JsonGraphStore(db_path)

        assert store.node_count == 0
        assert store.edge_count == 0

    def test_get_neighbors_on_empty(self, tmp_path):
        """빈 그래프에서 이웃 조회하면 빈 리스트."""
        db_path = tmp_path / ".vectordb"
        db_path.mkdir()

        store = JsonGraphStore(db_path)
        neighbors = store.get_neighbors("any.md")

        assert neighbors == []
