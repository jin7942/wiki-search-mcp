"""Domain exceptions.

예외 계층 구조:
- BusinessException: 비즈니스 규칙 위반 (복구 가능, 클라이언트 메시지)
- TechnicalException: 시스템/인프라 오류 (재시도 또는 관리자 개입)

각 예외는 ErrorContext를 통해 구조화된 에러 정보를 제공합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorContext:
    """에러 컨텍스트 정보.

    Attributes:
        code: 에러 코드 (예: "DOCUMENT_NOT_FOUND")
        details: 추가 컨텍스트 정보
    """

    code: str
    details: dict[str, Any] | None = None


class WikiSearchError(Exception):
    """Base exception for wiki-search-mcp.

    모든 도메인 예외의 기본 클래스입니다.
    ErrorContext를 통해 구조화된 에러 정보를 제공합니다.
    """

    def __init__(self, message: str, context: ErrorContext | None = None):
        super().__init__(message)
        self.context = context


# =============================================================================
# BusinessException: 비즈니스 로직 예외 (복구 가능)
# =============================================================================


class BusinessException(WikiSearchError):
    """비즈니스 규칙 위반.

    클라이언트에게 명확한 메시지를 전달해야 하는 예외입니다.
    예: 문서 미발견, 잘못된 쿼리, 입력 검증 실패
    """


class DocumentNotFoundError(BusinessException):
    """문서를 찾을 수 없음."""

    @classmethod
    def of(cls, path: str) -> DocumentNotFoundError:
        """팩토리 메서드: 경로로 예외 생성."""
        return cls(
            f"Document not found: {path}",
            ErrorContext(code="DOCUMENT_NOT_FOUND", details={"path": path}),
        )


class InvalidQueryError(BusinessException):
    """잘못된 검색 쿼리."""

    @classmethod
    def of(cls, query: str, reason: str) -> InvalidQueryError:
        """팩토리 메서드: 쿼리와 이유로 예외 생성."""
        return cls(
            f"Invalid query '{query}': {reason}",
            ErrorContext(
                code="INVALID_QUERY", details={"query": query, "reason": reason}
            ),
        )


class ValidationError(BusinessException):
    """입력 검증 실패."""

    @classmethod
    def of(cls, field: str, reason: str) -> ValidationError:
        """팩토리 메서드: 필드와 이유로 예외 생성."""
        return cls(
            f"Validation failed for '{field}': {reason}",
            ErrorContext(
                code="VALIDATION_ERROR", details={"field": field, "reason": reason}
            ),
        )


# =============================================================================
# TechnicalException: 기술적 예외 (시스템 오류)
# =============================================================================


class TechnicalException(WikiSearchError):
    """시스템/인프라 오류.

    재시도 또는 관리자 개입이 필요한 예외입니다.
    예: 인덱스 미존재, 경로 탐색 공격, 임베딩 모델 오류
    """


class IndexNotFoundError(TechnicalException):
    """인덱스가 존재하지 않음."""

    @classmethod
    def of(cls, db_path: str) -> IndexNotFoundError:
        """팩토리 메서드: DB 경로로 예외 생성."""
        return cls(
            f"Index not found at: {db_path}",
            ErrorContext(code="INDEX_NOT_FOUND", details={"db_path": db_path}),
        )


class InvalidPathError(TechnicalException):
    """유효하지 않은 경로 (빈/절대/.. /NUL/백슬래시/percent/base 밖/resolve 실패)."""

    @classmethod
    def of(cls, path: str, reason: str | None = None) -> InvalidPathError:
        """팩토리 메서드: 경로 + 거부 사유로 예외 생성.

        Args:
            path: 거부된 경로 문자열
            reason: 거부 사유 (empty/absolute/parent_traversal/null_byte/
                backslash/percent_encoded/outside_base/resolve_failed).
                None이면 v0.2.5 이전 메시지 ``"Path traversal attempt"`` 유지
                (backward compat).
        """
        if reason is None:
            message = f"Path traversal attempt: {path}"
        else:
            message = f"Invalid path ({reason}): {path}"
        return cls(
            message,
            ErrorContext(
                code="INVALID_PATH",
                details={"path": path, "reason": reason},
            ),
        )


class EmbeddingError(TechnicalException):
    """임베딩 모델 오류."""

    @classmethod
    def of(cls, model_name: str, reason: str) -> EmbeddingError:
        """팩토리 메서드: 모델명과 이유로 예외 생성."""
        return cls(
            f"Embedding error for model '{model_name}': {reason}",
            ErrorContext(
                code="EMBEDDING_ERROR",
                details={"model_name": model_name, "reason": reason},
            ),
        )


# =============================================================================
# v0.2.0: Daemon / Classifier 관련 예외
# =============================================================================


class ClassifierError(TechnicalException):
    """LLM 분류 호출 실패.

    code 예시:
    - "CLI_NOT_FOUND": claude CLI 미설치/미로그인
    - "SDK_ERROR": Claude Agent SDK 호출 자체 실패
    - "INVALID_JSON": LLM 응답이 유효한 JSON이 아님
    - "INVALID_FIELDS": JSON은 파싱됐으나 필드 검증 실패
    - "TIMEOUT": 호출 시간 초과
    """

    @classmethod
    def of(cls, message: str, code: str, details: dict[str, Any] | None = None) -> ClassifierError:
        return cls(message, ErrorContext(code=code, details=details))


class DaemonError(TechnicalException):
    """Daemon 라이프사이클 오류.

    code 예시:
    - "ALREADY_RUNNING": 이미 다른 daemon이 실행 중
    - "NOT_RUNNING": daemon이 실행 중이 아님
    - "PIDFILE_ERROR": PID 파일 read/write 실패
    """

    @classmethod
    def of(cls, message: str, code: str, details: dict[str, Any] | None = None) -> DaemonError:
        return cls(message, ErrorContext(code=code, details=details))


class RateLimitError(BusinessException):
    """Rate limit window 초과.

    daemon은 이를 잡아 pending.jsonl에 reason=rate_limited로 기록한다.
    """

    @classmethod
    def of(cls, wait_seconds: float) -> RateLimitError:
        return cls(
            f"Rate limit hit; would need to wait {wait_seconds:.1f}s",
            ErrorContext(code="RATE_LIMIT", details={"wait_seconds": wait_seconds}),
        )
