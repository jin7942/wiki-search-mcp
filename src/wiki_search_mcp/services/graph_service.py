"""Graph service.

그래프 연산 유스케이스를 담당합니다.
역링크 조회, 고아 문서 찾기 등을 지원합니다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wiki_search_mcp.core.exceptions import InvalidPathError
from wiki_search_mcp.core.models import Document
from wiki_search_mcp.core.path_validator import validate_path_for_query
from wiki_search_mcp.core.utils import normalize_document_path

if TYPE_CHECKING:
    from wiki_search_mcp.core.protocols import GraphRepository, VectorRepository


class GraphService:
    """그래프 연산 유스케이스 담당."""

    def __init__(
        self,
        graph_repository: "GraphRepository",
        vector_repository: "VectorRepository",
    ):
        """GraphService 초기화.

        Args:
            graph_repository: 그래프 저장소
            vector_repository: 벡터 저장소 (문서 정보 조회용)
        """
        self._graph = graph_repository
        self._vector = vector_repository

    def get_backlinks(self, path: str) -> list[Document]:
        """특정 문서를 참조하는 역링크 조회.

        Args:
            path: 대상 문서 경로

        Returns:
            참조하는 Document 리스트

        Raises:
            InvalidPathError: 경로가 유효하지 않은 경우
        """
        self._validate_path(path)

        backlink_paths = self._graph.get_backlinks(path)

        # 문서 정보 조회
        backlinks = []
        for source_path in backlink_paths:
            doc_data = self._vector.find_by_path(source_path)
            if doc_data:
                backlinks.append(Document.from_dict(doc_data))
            else:
                # 인덱스에 없는 경우 (삭제된 파일 등)
                backlinks.append(
                    Document.from_dict({
                        "path": source_path,
                        "title": source_path,
                        "category": "unknown",
                    })
                )

        return backlinks

    def find_orphans(self) -> list[Document]:
        """wikilink로 연결되지 않은 고아 문서 목록.

        Returns:
            고아 Document 리스트
        """
        # 모든 문서 경로
        all_paths = self._graph.get_all_paths()

        # 다른 문서에서 참조하는 경로 (엣지의 target)
        referenced_paths: set[str] = set()
        for edge in self._graph.get_edges():
            target = edge["target"]
            # 확장자 유무 모두 추가
            target_with_md, target_without_md = normalize_document_path(target)
            referenced_paths.add(target_with_md)
            referenced_paths.add(target_without_md)

        # 참조되지 않는 문서
        orphan_paths = all_paths - referenced_paths

        # 문서 정보 조회
        orphans = []
        for path in orphan_paths:
            doc_data = self._vector.find_by_path(path)
            if doc_data:
                orphans.append(Document.from_dict(doc_data))

        return orphans

    def get_related(
        self, path: str, max_depth: int = 2, limit: int = 3
    ) -> list[str]:
        """그래프 확장으로 관련 문서 조회.

        Args:
            path: 출발 문서 경로
            max_depth: 최대 탐색 깊이
            limit: 반환할 관련 문서 수

        Returns:
            관련 문서 경로 리스트
        """
        self._validate_path(path)

        neighbors = self._graph.get_neighbors(path, max_depth)
        return neighbors[:limit]

    def _validate_path(self, path: str) -> None:
        """경로 유효성 검사(검증 전용, 정규화/반환 없음).

        DocumentService._validate_path 와 달리 .md 정규화나 반환값이 없다.
        이는 의도된 차이다: 그래프 조회(get_backlinks/get_neighbors)는
        GraphRepository 내부에서 normalize_document_path 로 .md 유무 양쪽을
        매칭하므로(graph_store.get_backlinks 참고), 서비스 계층에서 다시
        정규화할 필요가 없다. 여기서는 path traversal 등 보안 검증만 수행한다.
        """
        validate_path_for_query(path)
