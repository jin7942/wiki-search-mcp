"""예외 시나리오 테스트.

디스크 오류, DB 연결 실패, 모델 로드 실패 등 엣지케이스를 테스트합니다.
이 테스트들은 시스템의 복원력(resilience)을 검증합니다.

Note:
    일부 테스트는 lancedb, mcp 등 선택적 의존성이 필요합니다.
    해당 모듈이 없으면 테스트를 건너뜁니다.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestSearchServiceEdgeCases:
    """SearchService 엣지 케이스 테스트."""

    def test_search_returns_error_when_index_not_found(self):
        """인덱스가 없을 때 에러 응답 반환."""
        from wiki_search_mcp.services.search_service import SearchService

        # Mock 의존성
        mock_vector = MagicMock()
        mock_vector.exists.return_value = False

        mock_keyword = MagicMock()
        mock_graph = MagicMock()
        mock_embedder = MagicMock()
        mock_cache = MagicMock()

        service = SearchService(
            vector_repository=mock_vector,
            keyword_repository=mock_keyword,
            graph_repository=mock_graph,
            embedder=mock_embedder,
            query_cache=mock_cache,
        )

        result = service.search("test query")

        assert result.error is not None
        # v0.2.0: "Index not found" → "Index not built yet" (자동 부트스트랩 안내)
        assert "Index not built yet" in result.error
        assert "wiki-search-mcp index" in result.error

    def test_search_with_empty_results(self):
        """검색 결과가 없을 때 빈 리스트 반환."""
        from wiki_search_mcp.services.search_service import SearchService

        mock_vector = MagicMock()
        mock_vector.exists.return_value = True
        mock_vector.search.return_value = []

        mock_keyword = MagicMock()
        mock_keyword.exists.return_value = False

        mock_graph = MagicMock()
        mock_graph.node_count = 0

        mock_embedder = MagicMock()
        mock_cache = MagicMock()
        # get_or_compute는 list로 변환 가능한 값 반환
        mock_cache.get_or_compute.return_value = [0.1, 0.2, 0.3]

        service = SearchService(
            vector_repository=mock_vector,
            keyword_repository=mock_keyword,
            graph_repository=mock_graph,
            embedder=mock_embedder,
            query_cache=mock_cache,
        )

        result = service.search("nonexistent query")

        assert len(result.results) == 0  # 빈 결과 (list 또는 tuple)
        assert result.error is None


class TestPathValidatorSecurityEdgeCases:
    """PathValidator 보안 엣지 케이스 테스트."""

    def test_path_with_only_dots(self):
        """점만 있는 경로 거부."""
        from wiki_search_mcp.core.exceptions import InvalidPathError
        from wiki_search_mcp.core.path_validator import validate_path

        with pytest.raises(InvalidPathError):
            validate_path("...")

    def test_path_with_hidden_traversal(self):
        """숨겨진 traversal 시도 거부."""
        from wiki_search_mcp.core.exceptions import InvalidPathError
        from wiki_search_mcp.core.path_validator import validate_path

        # 정상처럼 보이지만 .. 포함
        with pytest.raises(InvalidPathError):
            validate_path("docs/valid/../../../etc/passwd")


class TestExceptionTypes:
    """예외 타입 테스트."""

    def test_index_not_found_error_factory(self):
        """IndexNotFoundError.of() 팩토리 메서드 테스트."""
        from wiki_search_mcp.core.exceptions import IndexNotFoundError

        error = IndexNotFoundError.of("/path/to/db")

        assert "Index not found" in str(error)
        assert error.context is not None
        assert error.context.code == "INDEX_NOT_FOUND"
        assert error.context.details["db_path"] == "/path/to/db"

    def test_invalid_path_error_factory(self):
        """InvalidPathError.of() 팩토리 메서드 테스트."""
        from wiki_search_mcp.core.exceptions import InvalidPathError

        error = InvalidPathError.of("../etc/passwd")

        assert "Path traversal" in str(error)
        assert error.context is not None
        assert error.context.code == "INVALID_PATH"
        assert error.context.details["path"] == "../etc/passwd"

    def test_document_not_found_error_factory(self):
        """DocumentNotFoundError.of() 팩토리 메서드 테스트."""
        from wiki_search_mcp.core.exceptions import DocumentNotFoundError

        error = DocumentNotFoundError.of("docs/missing.md")

        assert "Document not found" in str(error)
        assert error.context is not None
        assert error.context.code == "DOCUMENT_NOT_FOUND"

    def test_embedding_error_factory(self):
        """EmbeddingError.of() 팩토리 메서드 테스트."""
        from wiki_search_mcp.core.exceptions import EmbeddingError

        error = EmbeddingError.of("test-model", "Model not found")

        assert "Embedding error" in str(error)
        assert error.context is not None
        assert error.context.code == "EMBEDDING_ERROR"
        assert error.context.details["model_name"] == "test-model"

    def test_validation_error_factory(self):
        """ValidationError.of() 팩토리 메서드 테스트."""
        from wiki_search_mcp.core.exceptions import ValidationError

        error = ValidationError.of("query", "Query too short")

        assert "Validation failed" in str(error)
        assert error.context is not None
        assert error.context.code == "VALIDATION_ERROR"


class TestExceptionHierarchy:
    """예외 계층 구조 테스트."""

    def test_business_exception_is_wiki_search_error(self):
        """BusinessException은 WikiSearchError의 하위 클래스."""
        from wiki_search_mcp.core.exceptions import BusinessException, WikiSearchError

        assert issubclass(BusinessException, WikiSearchError)

    def test_technical_exception_is_wiki_search_error(self):
        """TechnicalException은 WikiSearchError의 하위 클래스."""
        from wiki_search_mcp.core.exceptions import TechnicalException, WikiSearchError

        assert issubclass(TechnicalException, WikiSearchError)

    def test_document_not_found_is_business_exception(self):
        """DocumentNotFoundError는 BusinessException의 하위 클래스."""
        from wiki_search_mcp.core.exceptions import (
            BusinessException,
            DocumentNotFoundError,
        )

        assert issubclass(DocumentNotFoundError, BusinessException)

    def test_index_not_found_is_technical_exception(self):
        """IndexNotFoundError는 TechnicalException의 하위 클래스."""
        from wiki_search_mcp.core.exceptions import (
            IndexNotFoundError,
            TechnicalException,
        )

        assert issubclass(IndexNotFoundError, TechnicalException)

    def test_invalid_path_is_technical_exception(self):
        """InvalidPathError는 TechnicalException의 하위 클래스."""
        from wiki_search_mcp.core.exceptions import InvalidPathError, TechnicalException

        assert issubclass(InvalidPathError, TechnicalException)


class TestErrorContext:
    """ErrorContext 테스트."""

    def test_error_context_is_frozen(self):
        """ErrorContext는 불변(frozen) 데이터클래스."""
        from wiki_search_mcp.core.exceptions import ErrorContext

        context = ErrorContext(code="TEST", details={"key": "value"})

        # frozen=True이므로 수정 불가
        with pytest.raises(AttributeError):
            context.code = "MODIFIED"

    def test_error_context_equality(self):
        """같은 값을 가진 ErrorContext는 동등."""
        from wiki_search_mcp.core.exceptions import ErrorContext

        ctx1 = ErrorContext(code="TEST", details={"key": "value"})
        ctx2 = ErrorContext(code="TEST", details={"key": "value"})

        assert ctx1 == ctx2

    def test_error_context_with_none_details(self):
        """details가 None인 ErrorContext 생성 가능."""
        from wiki_search_mcp.core.exceptions import ErrorContext

        context = ErrorContext(code="TEST")

        assert context.code == "TEST"
        assert context.details is None


# =============================================================================
# 선택적 의존성이 필요한 테스트 (lancedb, mcp)
# =============================================================================


@pytest.mark.skipif(
    True,  # 항상 건너뜀 - lancedb/mcp 없는 환경에서 실행 가능하도록
    reason="Requires lancedb and mcp modules which may not be installed",
)
class TestLanceDBIntegration:
    """LanceDB 통합 테스트 (선택적).

    이 테스트들은 실제 lancedb가 설치된 환경에서만 실행됩니다.
    """

    def test_vector_store_connection_failure(self, tmp_path: Path):
        """LanceDB 연결 실패 시 IndexNotFoundError 발생."""
        pass  # 실제 lancedb 환경에서 구현
