"""JsonlLog 단위 테스트."""

from __future__ import annotations

import datetime as _dt
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


def test_append_serializes_date_and_datetime(tmp_path: Path) -> None:
    """frontmatter YAML이 ``created: 2026-04-23`` 같은 따옴표 없는 ISO 스칼라를
    ``datetime.date``로 파싱한다. AppliedRecord.frontmatter_before에 그게
    그대로 들어오면 표준 ``json.dumps``가 TypeError로 죽으면서 worker
    전체가 멈추는 회귀가 v0.2.0에서 발생했다 — default 핸들러로 ISO 문자열
    변환되는지 회귀 보장.
    """
    log = JsonlLog(tmp_path / "applied.jsonl")
    log.append(
        {
            "path": "infra/vim-manual.md",
            "frontmatter_before": {
                "created": _dt.date(2026, 4, 23),
                "updated": _dt.datetime(2026, 5, 13, 23, 4, 4),
            },
        }
    )
    items = list(log.scan())
    assert len(items) == 1
    fm = items[0]["frontmatter_before"]
    assert fm["created"] == "2026-04-23"
    assert fm["updated"].startswith("2026-05-13T23:04:04")


def test_append_serializes_path_and_set(tmp_path: Path) -> None:
    log = JsonlLog(tmp_path / "items.jsonl")
    log.append({"p": Path("/tmp/x"), "tags": {"a", "b"}})
    items = list(log.scan())
    assert items[0]["p"] == "/tmp/x"
    assert items[0]["tags"] == ["a", "b"]


def test_append_raises_on_unsupported_type(tmp_path: Path) -> None:
    log = JsonlLog(tmp_path / "items.jsonl")

    class Unknown:
        pass

    with pytest.raises(TypeError):
        log.append({"x": Unknown()})
