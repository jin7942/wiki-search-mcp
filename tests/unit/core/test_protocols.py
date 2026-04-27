"""Protocol 정합성 테스트.

Protocol에 정의된 메서드가 구현체에 존재하는지 확인합니다.
"""

from wiki_search_mcp.core.protocols import (
    GraphRepository,
    QueryExpanderProtocol,
    VectorRepository,
)


class TestVectorRepositoryProtocol:
    """VectorRepository Protocol 테스트."""

    def test_to_arrow_list_exists(self):
        """to_arrow_list 메서드 정의 확인."""
        # Protocol에 메서드가 정의되어 있는지 확인
        assert hasattr(VectorRepository, "to_arrow_list")

    def test_required_methods(self):
        """필수 메서드 정의 확인."""
        required_methods = [
            "search",
            "find_by_path",
            "find_all",
            "exists",
            "invalidate_cache",
            "to_arrow_list",
        ]
        for method in required_methods:
            assert hasattr(VectorRepository, method), f"Missing method: {method}"


class TestGraphRepositoryProtocol:
    """GraphRepository Protocol 테스트."""

    def test_node_count_exists(self):
        """node_count property 정의 확인."""
        assert hasattr(GraphRepository, "node_count")

    def test_required_methods(self):
        """필수 메서드 정의 확인."""
        required_methods = [
            "get_neighbors",
            "get_backlinks",
            "get_all_paths",
            "get_edges",
            "reload",
        ]
        for method in required_methods:
            assert hasattr(GraphRepository, method), f"Missing method: {method}"


class TestQueryExpanderProtocol:
    """QueryExpanderProtocol 테스트."""

    def test_protocol_exists(self):
        """QueryExpanderProtocol이 정의되어 있는지 확인."""
        assert QueryExpanderProtocol is not None

    def test_required_methods(self):
        """필수 메서드 정의 확인."""
        required_methods = ["expand", "get_synonyms"]
        for method in required_methods:
            assert hasattr(
                QueryExpanderProtocol, method
            ), f"Missing method: {method}"

    def test_implementation_satisfies_protocol(self):
        """QueryExpander가 Protocol을 만족하는지 확인."""
        from wiki_search_mcp.services.expander_service import QueryExpander

        expander = QueryExpander()

        # isinstance 체크 (runtime_checkable)
        assert isinstance(expander, QueryExpanderProtocol)


class TestImplementationCompliance:
    """구현체가 Protocol을 준수하는지 테스트."""

    def test_lance_vector_store_implements_protocol(self, tmp_path):
        """LanceVectorStore가 VectorRepository를 구현하는지 확인."""
        from wiki_search_mcp.infrastructure.storage.vector_store import (
            LanceVectorStore,
        )

        db_path = tmp_path / ".vectordb"
        db_path.mkdir()
        store = LanceVectorStore(db_path)

        # to_arrow_list 메서드 존재
        assert hasattr(store, "to_arrow_list")
        assert callable(getattr(store, "to_arrow_list"))

    def test_json_graph_store_implements_protocol(self, tmp_path):
        """JsonGraphStore가 GraphRepository를 구현하는지 확인."""
        from wiki_search_mcp.infrastructure.storage.graph_store import (
            JsonGraphStore,
        )

        db_path = tmp_path / ".vectordb"
        db_path.mkdir()
        store = JsonGraphStore(db_path)

        # node_count property 존재
        assert hasattr(store, "node_count")
        assert isinstance(store.node_count, int)
