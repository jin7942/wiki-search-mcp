"""StatusFile 단위 테스트."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from wiki_search_mcp.infrastructure.daemon.statefile import StatusFile


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    sf = StatusFile(tmp_path / "status.json")
    sf.write({"state": "running", "applied_count": 0})
    assert sf.read() == {"state": "running", "applied_count": 0}


def test_update_merges_fields(tmp_path: Path) -> None:
    sf = StatusFile(tmp_path / "status.json")
    sf.write({"state": "running", "applied_count": 0})
    sf.update(applied_count=5, last="2026-05-13")
    data = sf.read()
    assert data["applied_count"] == 5
    assert data["last"] == "2026-05-13"
    assert data["state"] == "running"


def test_increment_counter(tmp_path: Path) -> None:
    sf = StatusFile(tmp_path / "status.json")
    sf.write({"applied_count": 0})
    sf.increment("applied_count", 3)
    sf.increment("applied_count")  # default delta=1
    assert sf.read()["applied_count"] == 4


def test_read_missing_returns_empty(tmp_path: Path) -> None:
    sf = StatusFile(tmp_path / "absent.json")
    assert sf.read() == {}


def test_atomic_write_no_partial_file(tmp_path: Path) -> None:
    """동시 read 중에도 partial JSON이 보이지 않음을 검증."""
    target = tmp_path / "status.json"
    sf = StatusFile(target)
    sf.write({"v": 0})

    errors: list[Exception] = []

    def reader():
        for _ in range(200):
            try:
                _ = json.loads(target.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                errors.append(e)
            except FileNotFoundError:
                pass

    def writer():
        for i in range(200):
            sf.write({"v": i})

    t_r = threading.Thread(target=reader)
    t_w = threading.Thread(target=writer)
    t_r.start()
    t_w.start()
    t_r.join()
    t_w.join()
    assert errors == []
