"""MCP server adapter.

Model Context Protocol 서버 구현입니다.

Modules:
    container: 서비스 의존성 컨테이너
    handlers: 도구 핸들러
    server: MCP 서버 설정
"""

from .container import ServiceContainer
from .server import main, mcp

__all__ = ["ServiceContainer", "main", "mcp"]
