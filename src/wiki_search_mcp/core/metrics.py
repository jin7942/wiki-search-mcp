"""구조화 성능 메트릭 싱크.

평문 로그(daemon.log)와 별개로, reindex / 검색 / LLM 분류 같은 이벤트를
``metrics.jsonl`` 에 한 줄당 JSON 객체로 기록한다. 각 라인은 최소한
``event`` / ``duration_ms`` / ``ts`` 를 가지며 이벤트별 메타 필드(단계별
timing, 처리 건수 등)를 덧붙인다. 외부 도구가 라인 단위로 집계(평균/p95/횟수)
할 수 있게 하는 것이 목적이다.

설계:
- 전역 싱크는 ``configure_metrics(path)`` 로 한 번 설정한다. 미설정이면
  ``record()`` / ``timer()`` 는 조용히 no-op 이라, serve/daemon/CLI/테스트
  어디서 호출해도 안전하다.
- 기록 실패(디스크 가득 등)는 절대 호출자 로직을 깨면 안 되므로 모두 삼킨다
  (메트릭은 보조 신호다).
- 동일 프로세스 내 동시 기록은 JsonlLog 의 threading.Lock 으로 직렬화된다.
  서로 다른 프로세스가 같은 파일에 append 해도 각 record 가 단일 write+fsync
  라 라인 단위로는 안전하다.
"""

from __future__ import annotations

import datetime as _dt
import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from wiki_search_mcp.infrastructure.jsonl.log import JsonlLog

logger = logging.getLogger(__name__)

_sink: JsonlLog | None = None


def configure_metrics(path: Path | None) -> None:
    """메트릭 싱크 경로 설정. ``None`` 이면 비활성(no-op)."""
    global _sink
    if path is None:
        _sink = None
        return
    try:
        _sink = JsonlLog(Path(path))
    except Exception:
        # 싱크 생성 실패해도 본 기능에 영향 없어야 한다.
        logger.debug("configure_metrics failed", exc_info=True)
        _sink = None


def _utc_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def record(event: str, **fields: Any) -> None:
    """메트릭 이벤트 한 건 기록. 싱크 미설정/실패 시 no-op.

    Args:
        event: 이벤트 종류 (예: ``"reindex"``, ``"search"``, ``"llm_classify"``).
        **fields: ``duration_ms`` 등 이벤트별 메타. ``event`` / ``ts`` 는 자동 부여.
    """
    sink = _sink
    if sink is None:
        return
    try:
        obj: dict[str, Any] = {"event": event, "ts": _utc_iso()}
        obj.update(fields)
        sink.append(obj)
    except Exception:
        logger.debug("metrics.record(%s) failed", event, exc_info=True)


@contextmanager
def timer(event: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """블록 실행 시간을 재서 ``record(event, duration_ms=..., **fields)`` 한다.

    yield 되는 dict 에 키를 추가하면 그 값도 함께 기록된다 (단계별 timing 등).
    블록에서 예외가 나면 ``ok=False`` + ``error`` 를 붙여 기록하고 예외는 재전파.

    예::

        with timer("reindex", mode="incremental") as m:
            ...
            m["embed_ms"] = embed_ms
            m["indexed"] = len(records)
    """
    extra: dict[str, Any] = {}
    start = time.perf_counter()
    ok = True
    err: str | None = None
    try:
        yield extra
    except BaseException as e:  # noqa: BLE001 - 기록 후 재전파
        ok = False
        err = f"{type(e).__name__}: {e}"
        raise
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        payload = {**fields, **extra, "duration_ms": duration_ms, "ok": ok}
        if err is not None:
            payload["error"] = err
        record(event, **payload)
