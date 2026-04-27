"""setup_logging 단위 테스트.

환경변수 의존성이 제거되고 인자로만 동작하는지 검증.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from wiki_search_mcp.core.logging import get_logger, setup_logging


def test_setup_logging_default_level():
    """기본 호출 시 WARNING 레벨."""
    setup_logging()
    pkg_logger = logging.getLogger("wiki_search_mcp")
    assert pkg_logger.level == logging.WARNING


def test_setup_logging_explicit_level():
    """명시적 레벨 인자 적용."""
    setup_logging(level="DEBUG")
    pkg_logger = logging.getLogger("wiki_search_mcp")
    assert pkg_logger.level == logging.DEBUG

    setup_logging(level="INFO")
    assert pkg_logger.level == logging.INFO

    setup_logging(level="ERROR")
    assert pkg_logger.level == logging.ERROR


def test_setup_logging_invalid_level_falls_back():
    """잘못된 레벨 문자열은 WARNING으로 폴백."""
    setup_logging(level="UNKNOWN_LEVEL")
    pkg_logger = logging.getLogger("wiki_search_mcp")
    assert pkg_logger.level == logging.WARNING


def test_setup_logging_lowercase_level():
    """소문자 레벨도 허용."""
    setup_logging(level="debug")
    pkg_logger = logging.getLogger("wiki_search_mcp")
    assert pkg_logger.level == logging.DEBUG


def test_setup_logging_with_log_file(tmp_path: Path):
    """log_file 인자 시 FileHandler 추가."""
    log_file = tmp_path / "test.log"
    setup_logging(level="INFO", log_file=log_file)

    logger = get_logger("test")
    logger.info("hello")

    # 핸들러에 FileHandler 포함 확인
    root = logging.getLogger()
    assert any(isinstance(h, logging.FileHandler) for h in root.handlers)


def test_setup_logging_does_not_read_env(
    monkeypatch: pytest.MonkeyPatch,
):
    """환경변수가 있어도 무시 (인자가 전부)."""
    monkeypatch.setenv("WIKI_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("WIKI_LOG_FILE", "/tmp/should-be-ignored.log")

    # 환경변수 무시되고 인자(WARNING) 적용
    setup_logging(level="WARNING")
    pkg_logger = logging.getLogger("wiki_search_mcp")
    assert pkg_logger.level == logging.WARNING


def test_get_logger_namespaced():
    """get_logger는 wiki_search_mcp 네임스페이스 적용."""
    logger = get_logger("foo")
    assert logger.name == "wiki_search_mcp.foo"
