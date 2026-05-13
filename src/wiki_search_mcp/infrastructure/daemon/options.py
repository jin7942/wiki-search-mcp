"""DaemonOptions dataclass — CLI에서 빌드하여 DaemonRunner에 주입."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wiki_search_mcp.services.llm.provider import LLMProvider


@dataclass(frozen=True)
class DaemonOptions:
    """daemon 실행 옵션.

    Attributes:
        wiki_path: wiki 루트 절대 경로
        embedding_model: 임베딩 모델 이름 (None이면 기본값)
        llm_model: Claude 모델 alias ("haiku"/"sonnet"/"opus") 또는 풀 ID
        confidence_threshold: 자동 적용 기준 (이상이면 적용, 미만이면 pending)
        concurrency: 동시 worker 수
        queue_max: 큐 최대 크기 (초과 시 enqueue 무시)
        rate_per_minute / rate_per_hour / rate_per_day: rate-limit 설정
        rate_max_wait_s: rate-limit 대기 허용 한도
        debounce: watcher 디바운스 (초)
        auto_move: 카테고리 폴더로 이동 여부
        log_level: 로그 레벨
        provider_factory: ``LLMProvider`` 생성 함수 (테스트에서 FakeProvider 주입용)
        ignore_patterns: 추가 무시 패턴
    """

    wiki_path: Path
    embedding_model: str | None = None
    llm_model: str = "haiku"
    confidence_threshold: float = 0.70
    concurrency: int = 2
    queue_max: int = 1024
    rate_per_minute: int = 5
    rate_per_hour: int = 100
    rate_per_day: int = 500
    rate_max_wait_s: float = 30.0
    debounce: float = 2.0
    auto_move: bool = True
    log_level: str = "INFO"
    ignore_patterns: tuple[str, ...] = field(default_factory=tuple)
    provider_factory: Callable[[], "LLMProvider"] | None = None
