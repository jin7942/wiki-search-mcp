"""_options_to_args 직렬화 단위 테스트.

config 명령에서 사용하는 옵션 → args 직렬화 헬퍼를 검증합니다.
기본값은 제외되고 비-기본값만 args에 포함되는지 확인합니다.
"""

from __future__ import annotations

from wiki_search_mcp.adapters.cli.main import _options_to_args


def test_all_defaults_returns_empty():
    """모든 옵션이 기본값이면 빈 args."""
    args = _options_to_args(
        model=None,
        ignore_patterns=(),
        watch=True,
        debounce=2.0,
        log_level="WARNING",
        log_file=None,
    )
    assert args == []


def test_model_serialized():
    args = _options_to_args(
        model="fast",
        ignore_patterns=(),
        watch=True,
        debounce=2.0,
        log_level="WARNING",
        log_file=None,
    )
    assert args == ["--model", "fast"]


def test_no_watch_serialized():
    args = _options_to_args(
        model=None,
        ignore_patterns=(),
        watch=False,
        debounce=2.0,
        log_level="WARNING",
        log_file=None,
    )
    assert args == ["--no-watch"]


def test_ignore_multiple_patterns():
    args = _options_to_args(
        model=None,
        ignore_patterns=("draft", "*.bak", "private"),
        watch=True,
        debounce=2.0,
        log_level="WARNING",
        log_file=None,
    )
    assert args == [
        "--ignore",
        "draft",
        "--ignore",
        "*.bak",
        "--ignore",
        "private",
    ]


def test_debounce_non_default():
    args = _options_to_args(
        model=None,
        ignore_patterns=(),
        watch=True,
        debounce=5.0,
        log_level="WARNING",
        log_file=None,
    )
    assert args == ["--debounce", "5.0"]


def test_debounce_default_not_serialized():
    args = _options_to_args(
        model=None,
        ignore_patterns=(),
        watch=True,
        debounce=2.0,
        log_level="WARNING",
        log_file=None,
    )
    assert "--debounce" not in args


def test_log_level_non_default():
    args = _options_to_args(
        model=None,
        ignore_patterns=(),
        watch=True,
        debounce=2.0,
        log_level="DEBUG",
        log_file=None,
    )
    assert args == ["--log-level", "DEBUG"]


def test_log_file_serialized():
    args = _options_to_args(
        model=None,
        ignore_patterns=(),
        watch=True,
        debounce=2.0,
        log_level="WARNING",
        log_file="/tmp/x.log",
    )
    assert args == ["--log-file", "/tmp/x.log"]


def test_combined_options():
    """여러 옵션 조합 직렬화 순서."""
    args = _options_to_args(
        model="fast",
        ignore_patterns=("draft",),
        watch=False,
        debounce=5.0,
        log_level="DEBUG",
        log_file="/tmp/x.log",
    )
    # 직렬화 순서: model → ignore → no-watch → debounce → log-level → log-file
    assert args == [
        "--model",
        "fast",
        "--ignore",
        "draft",
        "--no-watch",
        "--debounce",
        "5.0",
        "--log-level",
        "DEBUG",
        "--log-file",
        "/tmp/x.log",
    ]
