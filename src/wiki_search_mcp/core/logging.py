"""로깅 인프라.

CLI 옵션 (--log-level, --log-file) 또는 함수 인자로 명시적으로 설정합니다.
환경변수는 사용하지 않습니다.
"""

from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(
    level: str = "WARNING",
    log_file: str | Path | None = None,
) -> None:
    """로깅 설정 초기화.

    Args:
        level: DEBUG, INFO, WARNING, ERROR 중 하나 (기본: WARNING)
        log_file: 로그 파일 경로 (None이면 stderr만 출력)
    """
    # 로그 레벨 파싱
    level_value = getattr(logging, level.upper(), logging.WARNING)

    # 핸들러 설정
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(str(log_file)))

    # 로거 설정
    logging.basicConfig(
        level=level_value,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,  # 기존 설정 덮어쓰기
    )

    # wiki_search_mcp 네임스페이스 로거 레벨 설정
    pkg_logger = logging.getLogger("wiki_search_mcp")
    pkg_logger.setLevel(level_value)


def get_logger(name: str) -> logging.Logger:
    """wiki_search_mcp 네임스페이스의 로거 반환.

    Args:
        name: 로거 이름 (wiki_search_mcp. 접두사 자동 추가)

    Returns:
        설정된 로거 인스턴스

    Examples:
        >>> logger = get_logger("search_service")
        >>> logger.info("검색 시작")
        2024-01-01 12:00:00 [INFO] wiki_search_mcp.search_service: 검색 시작
    """
    return logging.getLogger(f"wiki_search_mcp.{name}")
