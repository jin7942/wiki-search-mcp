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
        quiescence_seconds: 파일이 정적 상태로 머물러야 분류 진입을 허용하는 최소 시간(초).
            사용자가 작성 중인 inbox 파일이 즉시 분류되어 다른 폴더로 이동하는 것을 막는다.
            ``_classify_and_apply`` 진입 시점에 ``now - mtime < quiescence_seconds`` 이면
            짧은 cooldown 후 다음 rescan에서 재시도한다.
        min_body_chars: 분류 진입을 허용하는 본문(frontmatter 제외) 최소 길이.
            너무 짧은 초안에 LLM이 호출되어 미완성 본문으로 카테고리가 결정되는 것을 막는다.
        rescan_interval_seconds: 외부 FS 이벤트가 없어도 daemon이 스스로 ``_rescan()`` 을
            호출하는 주기(초). 0 이하면 비활성. cooldown 만료 후 영원히 안 깨어나는
            문제를 방지.
        auto_move: 카테고리 폴더로 이동 여부
        rewrite_inbound_links: 파일 이동 시 다른 파일 본문에 박힌 wikilink(``[[옛 경로]]``)
            를 새 경로로 일괄 보정할지 여부. 깨진 링크 누적 방지.
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
    quiescence_seconds: float = 60.0
    min_body_chars: int = 200
    rescan_interval_seconds: float = 300.0
    auto_move: bool = True
    rewrite_inbound_links: bool = True
    log_level: str = "INFO"
    ignore_patterns: tuple[str, ...] = field(default_factory=tuple)
    provider_factory: Callable[[], "LLMProvider"] | None = None
