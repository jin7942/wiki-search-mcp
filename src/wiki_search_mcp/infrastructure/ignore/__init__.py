"""파일/디렉토리 무시 패턴 처리.

dot-prefix 자동, .gitignore 자동 파싱, WIKI_IGNORE 환경변수를 결합합니다.
"""

from wiki_search_mcp.infrastructure.ignore.matcher import IgnoreMatcher

__all__ = ["IgnoreMatcher"]
