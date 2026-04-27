"""Core domain layer.

순수 비즈니스 로직을 담는 계층입니다.
외부 의존성(DB, 프레임워크) 없이 도메인 규칙만 정의합니다.

Modules:
    models: 도메인 엔티티 및 Value Objects
    protocols: 저장소/서비스 인터페이스 (Protocol)
    exceptions: 도메인 예외 계층 구조
    config: 공통 설정 상수
    utils: 공통 유틸리티 함수
    logging: 로깅 인프라
"""

from wiki_search_mcp.core.config import (
    CATEGORY_FOLDER_THRESHOLD,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_PREVIEW_SIZE,
    DEFAULT_TOP_K,
    EMBEDDING_MODELS,
    LISTING_TTL_SECONDS,
    MAX_DOCS_LIMIT,
    MAX_GRAPH_DEPTH,
    MAX_RELATED_DOCS,
    NO_FRONTMATTER_ERROR_RATIO,
    NO_FRONTMATTER_FIELD_THRESHOLD,
    PARTIAL_WARNING_RATIO,
    RRF_K,
    SEARCH_MULTIPLIER,
    WikiConfig,
)
from wiki_search_mcp.core.utils import (
    parse_frontmatter,
    resolve_pages_path,
    tokenize,
)
from wiki_search_mcp.core.logging import get_logger, setup_logging

__all__ = [
    # config
    "CATEGORY_FOLDER_THRESHOLD",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_PREVIEW_SIZE",
    "DEFAULT_TOP_K",
    "EMBEDDING_MODELS",
    "LISTING_TTL_SECONDS",
    "MAX_DOCS_LIMIT",
    "MAX_GRAPH_DEPTH",
    "MAX_RELATED_DOCS",
    "NO_FRONTMATTER_ERROR_RATIO",
    "NO_FRONTMATTER_FIELD_THRESHOLD",
    "PARTIAL_WARNING_RATIO",
    "RRF_K",
    "SEARCH_MULTIPLIER",
    "WikiConfig",
    # utils
    "parse_frontmatter",
    "resolve_pages_path",
    "tokenize",
    # logging
    "get_logger",
    "setup_logging",
]
