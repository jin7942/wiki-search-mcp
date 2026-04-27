"""JSON graph store implementation.

core.protocols.GraphRepository 인터페이스의 구현체입니다.
graph.json 파일에서 wikilink 그래프를 관리합니다.

사용 예:
    from wiki_search_mcp.infrastructure.storage import JsonGraphStore

    store = JsonGraphStore(Path("/wiki/.vectordb"))
    neighbors = store.get_neighbors("infra/nginx.md", max_depth=2)
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from wiki_search_mcp.core.utils import normalize_document_path


class JsonGraphStore:
    """JSON 기반 그래프 스토어 구현.

    GraphRepository 프로토콜을 구현합니다.
    양방향 인접 리스트를 캐싱하여 BFS 탐색 성능을 최적화합니다.

    Attributes:
        _graph: {"nodes": [...], "edges": [...]} 형식의 원본 그래프
        _neighbors: 양방향 인접 리스트 캐시
    """

    def __init__(self, db_path: Path):
        """JsonGraphStore 초기화.

        Args:
            db_path: 그래프 저장 경로 (.vectordb)
        """
        self._db_path = db_path
        self._graph: dict[str, Any] = {}
        self._neighbors: dict[str, set[str]] = {}
        self._load()

    def _load(self) -> None:
        """graph.json 로드 + 인접 리스트 캐싱."""
        graph_path = self._db_path / "graph.json"
        if graph_path.exists():
            self._graph = json.loads(graph_path.read_text(encoding="utf-8"))
            self._neighbors = self._build_adjacency_list(self._graph)
        else:
            self._graph = {"nodes": [], "edges": []}
            self._neighbors = {}

    def _build_adjacency_list(self, graph: dict[str, Any]) -> dict[str, set[str]]:
        """양방향 인접 리스트 구축.

        Args:
            graph: {"nodes": [...], "edges": [...]} 형식의 그래프

        Returns:
            {path: {neighbor1, neighbor2, ...}} 형식의 인접 리스트
        """
        neighbors: dict[str, set[str]] = {}
        for edge in graph.get("edges", []):
            src, tgt = edge["source"], edge["target"]
            neighbors.setdefault(src, set()).add(tgt)
            neighbors.setdefault(tgt, set()).add(src)
        return neighbors

    def get_neighbors(self, path: str, max_depth: int = 2) -> list[str]:
        """이웃 노드 탐색 (BFS).

        캐시된 인접 리스트를 사용하여 성능을 최적화합니다.

        Args:
            path: 출발 노드 경로
            max_depth: 최대 탐색 깊이

        Returns:
            이웃 노드 경로 리스트 (거리순)
        """
        related: list[tuple[str, int]] = []  # (path, distance)
        queue: deque[tuple[str, int]] = deque([(path, 0)])
        visited: set[str] = {path}

        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue

            for neighbor in self._neighbors.get(current, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    related.append((neighbor, depth + 1))
                    queue.append((neighbor, depth + 1))

        # 거리순 정렬 후 경로만 반환
        related.sort(key=lambda x: x[1])
        return [p for p, _ in related]

    def get_backlinks(self, path: str) -> list[str]:
        """역방향 링크 조회.

        Args:
            path: 대상 문서 경로

        Returns:
            이 문서를 참조하는 문서 경로 리스트
        """
        # .md 확장자 처리 (확장자 유무 모두 매칭)
        path_with_md, path_without_md = normalize_document_path(path)
        target_variants = [path_with_md, path_without_md]

        # 역링크 수집
        backlink_sources: set[str] = set()
        for edge in self._graph.get("edges", []):
            if edge["target"] in target_variants:
                backlink_sources.add(edge["source"])

        return list(backlink_sources)

    def get_all_paths(self) -> set[str]:
        """모든 노드 경로.

        Returns:
            모든 문서 경로 집합
        """
        return set(node["id"] for node in self._graph.get("nodes", []))

    def get_edges(self) -> list[dict[str, str]]:
        """모든 엣지.

        Returns:
            {"source": str, "target": str} 형태의 엣지 리스트
        """
        return self._graph.get("edges", [])

    def reload(self) -> None:
        """그래프 리로드.

        graph.json이 갱신된 후 호출합니다.
        """
        self._load()

    @property
    def node_count(self) -> int:
        """노드 수.

        Returns:
            그래프 노드 수
        """
        return len(self._graph.get("nodes", []))

    @property
    def edge_count(self) -> int:
        """엣지 수.

        Returns:
            그래프 엣지 수
        """
        return len(self._graph.get("edges", []))
