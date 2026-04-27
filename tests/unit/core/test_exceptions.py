"""Tests for core/exceptions.py.

예외 계층 구조와 팩토리 메서드를 테스트합니다.
"""

import pytest

from wiki_search_mcp.core.exceptions import (
    BusinessException,
    DocumentNotFoundError,
    EmbeddingError,
    ErrorContext,
    IndexNotFoundError,
    InvalidPathError,
    InvalidQueryError,
    TechnicalException,
    ValidationError,
    WikiSearchError,
)


class TestErrorContext:
    """ErrorContext 테스트."""

    def test_creates_context(self):
        """ErrorContext 생성."""
        ctx = ErrorContext(code="TEST_ERROR", details={"key": "value"})

        assert ctx.code == "TEST_ERROR"
        assert ctx.details == {"key": "value"}

    def test_frozen(self):
        """frozen으로 인해 변경 불가."""
        ctx = ErrorContext(code="TEST")

        with pytest.raises(Exception):
            ctx.code = "CHANGED"


class TestExceptionHierarchy:
    """예외 계층 구조 테스트."""

    def test_business_exception_inherits_wiki_search_error(self):
        """BusinessException은 WikiSearchError 상속."""
        exc = BusinessException("test")

        assert isinstance(exc, WikiSearchError)

    def test_technical_exception_inherits_wiki_search_error(self):
        """TechnicalException은 WikiSearchError 상속."""
        exc = TechnicalException("test")

        assert isinstance(exc, WikiSearchError)

    def test_document_not_found_is_business(self):
        """DocumentNotFoundError는 BusinessException."""
        exc = DocumentNotFoundError.of("test.md")

        assert isinstance(exc, BusinessException)
        assert not isinstance(exc, TechnicalException)

    def test_index_not_found_is_technical(self):
        """IndexNotFoundError는 TechnicalException."""
        exc = IndexNotFoundError.of("/path/to/db")

        assert isinstance(exc, TechnicalException)
        assert not isinstance(exc, BusinessException)


class TestFactoryMethods:
    """예외 팩토리 메서드 테스트."""

    def test_document_not_found_of(self):
        """DocumentNotFoundError.of() 팩토리 메서드."""
        exc = DocumentNotFoundError.of("infra/nginx.md")

        assert "infra/nginx.md" in str(exc)
        assert exc.context.code == "DOCUMENT_NOT_FOUND"
        assert exc.context.details["path"] == "infra/nginx.md"

    def test_invalid_query_of(self):
        """InvalidQueryError.of() 팩토리 메서드."""
        exc = InvalidQueryError.of("*", "쿼리가 너무 짧음")

        assert "*" in str(exc)
        assert exc.context.code == "INVALID_QUERY"
        assert exc.context.details["reason"] == "쿼리가 너무 짧음"

    def test_validation_error_of(self):
        """ValidationError.of() 팩토리 메서드."""
        exc = ValidationError.of("email", "잘못된 형식")

        assert "email" in str(exc)
        assert exc.context.code == "VALIDATION_ERROR"

    def test_index_not_found_of(self):
        """IndexNotFoundError.of() 팩토리 메서드."""
        exc = IndexNotFoundError.of("/wiki/.vectordb")

        assert "/wiki/.vectordb" in str(exc)
        assert exc.context.code == "INDEX_NOT_FOUND"

    def test_invalid_path_of(self):
        """InvalidPathError.of() 팩토리 메서드."""
        exc = InvalidPathError.of("../../../etc/passwd")

        assert "traversal" in str(exc).lower()
        assert exc.context.code == "INVALID_PATH"

    def test_embedding_error_of(self):
        """EmbeddingError.of() 팩토리 메서드."""
        exc = EmbeddingError.of("all-MiniLM-L6-v2", "모델 로드 실패")

        assert "all-MiniLM-L6-v2" in str(exc)
        assert exc.context.code == "EMBEDDING_ERROR"
        assert exc.context.details["reason"] == "모델 로드 실패"


class TestExceptionWithoutContext:
    """컨텍스트 없이 예외 생성 테스트."""

    def test_create_without_context(self):
        """context 없이 예외 생성 가능."""
        exc = WikiSearchError("Simple error")

        assert str(exc) == "Simple error"
        assert exc.context is None
