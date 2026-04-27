"""Wiki Search MCP Server

A Model Context Protocol server for semantic wiki search with vector database
and graph expansion capabilities.

Architecture (Clean Architecture):
    core/           - Domain models, protocols, exceptions
    services/       - Application services (use cases)
    infrastructure/ - External systems (DB, embedding model)
    adapters/       - Entry points (MCP, CLI)

Public API:
    ServiceContainer - DI container for services
"""

from typing import TYPE_CHECKING

try:
    from ._version import __version__
except ImportError:
    __version__ = "0.0.0.dev0"


# TYPE_CHECKING: 타입 체커에게만 보이는 import (런타임 성능 영향 없음)
if TYPE_CHECKING:
    from .adapters.mcp.container import ServiceContainer as ServiceContainer


# Public API (런타임 lazy import)
def __getattr__(name: str):
    """Lazy import for public API.

    모듈 임포트 시점을 지연하여 초기 로드 시간을 줄입니다.
    TYPE_CHECKING 블록과 함께 사용하여 타입 힌트도 지원합니다.
    """
    if name == "ServiceContainer":
        from .adapters.mcp.container import ServiceContainer

        return ServiceContainer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "__version__",
    "ServiceContainer",
]
