"""JsonlLog 단위 테스트."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from wiki_search_mcp.infrastructure.jsonl.log import JsonlLog


def test_append_and_scan_roundtrip(tmp_path: Path) -> None:
    log = JsonlLog(tmp_path / "items.jsonl")
    log.append({"a": 1, "b": "한글"})
    log.append({"a": 2})
    items = list(log.scan())
    assert items == [{"a": 1, "b": "한글"}, {"a": 2}]


def test_scan_returns_empty_when_missing(tmp_path: Path) -> None:
    log = JsonlLog(tmp_path / "missing.jsonl")
    assert list(log.scan()) == []


def test_tail_returns_last_n(tmp_path: Path) -> None:
    log = JsonlLog(tmp_path / "items.jsonl")
    for i in range(5):
        log.append({"i": i})
    assert log.tail(2) == [{"i": 3}, {"i": 4}]
    assert log.tail(0) == []
    assert log.tail(100) == [{"i": i} for i in range(5)]


def test_scan_skips_corrupt_lines(tmp_path: Path) -> None:
    p = tmp_path / "items.jsonl"
    p.write_text('{"a": 1}\nINVALID\n{"a": 2}\n', encoding="utf-8")
    log = JsonlLog(p)
    assert list(log.scan()) == [{"a": 1}, {"a": 2}]


def test_thread_safe_append(tmp_path: Path) -> None:
    log = JsonlLog(tmp_path / "items.jsonl")

    def writer(start: int) -> None:
        for i in range(start, start + 50):
            log.append({"i": i})

    threads = [threading.Thread(target=writer, args=(s,)) for s in (0, 100, 200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    items = list(log.scan())
    assert len(items) == 150
    # 모든 라인이 깨지지 않고 JSON으로 복원되었는지
    assert all(isinstance(it.get("i"), int) for it in items)


def test_rotate(tmp_path: Path) -> None:
    log = JsonlLog(tmp_path / "items.jsonl")
    log.append({"a": 1})
    rotated = log.rotate("2026-05-13")
    assert rotated == tmp_path / "items.jsonl.2026-05-13"
    assert rotated.exists()
    assert not (tmp_path / "items.jsonl").exists()
    # 새 append는 신규 파일에 들어감
    log.append({"a": 2})
    assert list(log.scan()) == [{"a": 2}]


def test_rotate_when_missing(tmp_path: Path) -> None:
    log = JsonlLog(tmp_path / "missing.jsonl")
    assert log.rotate("2026-05-13") is None
