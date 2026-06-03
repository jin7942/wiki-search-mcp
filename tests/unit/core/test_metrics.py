"""core.metrics 구조화 메트릭 싱크 테스트 (v0.5.0)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wiki_search_mcp.core import metrics


@pytest.fixture(autouse=True)
def _reset_sink():
    """각 테스트 후 전역 싱크 초기화 (테스트 간 누수 방지)."""
    yield
    metrics.configure_metrics(None)


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_record_writes_jsonl(tmp_path: Path) -> None:
    p = tmp_path / "metrics.jsonl"
    metrics.configure_metrics(p)

    metrics.record("reindex", duration_ms=120, indexed=5, changed=2)

    rows = _read(p)
    assert len(rows) == 1
    assert rows[0]["event"] == "reindex"
    assert rows[0]["duration_ms"] == 120
    assert rows[0]["indexed"] == 5
    assert "ts" in rows[0]


def test_no_sink_is_noop(tmp_path: Path) -> None:
    """싱크 미설정이면 record 가 예외 없이 무시된다."""
    metrics.configure_metrics(None)
    # 예외 없이 통과해야 함
    metrics.record("search", duration_ms=10)


def test_timer_records_duration_and_extra(tmp_path: Path) -> None:
    p = tmp_path / "metrics.jsonl"
    metrics.configure_metrics(p)

    with metrics.timer("reindex", mode="incremental") as m:
        m["embed_ms"] = 80
        m["indexed"] = 3

    rows = _read(p)
    assert len(rows) == 1
    r = rows[0]
    assert r["event"] == "reindex"
    assert r["mode"] == "incremental"
    assert r["embed_ms"] == 80
    assert r["indexed"] == 3
    assert r["ok"] is True
    assert isinstance(r["duration_ms"], (int, float))


def test_timer_records_error_and_reraises(tmp_path: Path) -> None:
    p = tmp_path / "metrics.jsonl"
    metrics.configure_metrics(p)

    raised = False
    try:
        with metrics.timer("reindex"):
            raise ValueError("boom")
    except ValueError:
        raised = True

    assert raised  # 예외는 재전파
    rows = _read(p)
    assert rows[0]["ok"] is False
    assert "boom" in rows[0]["error"]


def test_record_failure_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    """싱크 append 가 실패해도 record 는 예외를 던지지 않는다."""
    p = tmp_path / "metrics.jsonl"
    metrics.configure_metrics(p)

    def _boom(obj):
        raise OSError("disk full")

    monkeypatch.setattr(metrics._sink, "append", _boom)
    # 예외 없이 통과해야 함 (메트릭은 보조 신호)
    metrics.record("search", duration_ms=5)
