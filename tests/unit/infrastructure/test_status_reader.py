"""daemon status_reader facade 테스트.

server/handlers 중복을 통합한 read_daemon_status/read_daemon_pending 검증.
"""

from __future__ import annotations

import json
from pathlib import Path

from wiki_search_mcp.infrastructure.daemon.status_reader import (
    read_daemon_pending,
    read_daemon_status,
)


class TestReadDaemonStatus:
    def test_not_running_when_no_state_no_pid(self, tmp_path: Path) -> None:
        """상태 파일 없고 daemon 미실행 → not_running."""
        data = read_daemon_status(
            tmp_path,
            pid_checker=lambda p: (False, None),
        )
        assert data["state"] == "not_running"
        assert data["alive"] is False
        assert data["pid"] is None

    def test_alive_merges_state(self, tmp_path: Path) -> None:
        """상태 데이터가 있으면 alive/pid 와 병합."""
        from wiki_search_mcp.infrastructure.daemon.statefile import StatusFile

        sf = StatusFile(tmp_path / "status.json")
        sf.write({"state": "running", "applied_count": 3})

        data = read_daemon_status(
            tmp_path,
            status_reader=sf,
            pid_checker=lambda p: (True, 1234),
        )
        assert data["state"] == "running"
        assert data["applied_count"] == 3
        assert data["alive"] is True
        assert data["pid"] == 1234

    def test_failure_returns_unknown(self, tmp_path: Path) -> None:
        """checker 가 예외를 던져도 raise 하지 않고 unknown 반환."""
        def boom(p):
            raise RuntimeError("kaboom")

        data = read_daemon_status(tmp_path, pid_checker=boom)
        assert data["state"] == "unknown"
        assert "kaboom" in data["error"]


class TestReadDaemonPending:
    def test_empty_when_no_files(self, tmp_path: Path) -> None:
        """pending.jsonl 없으면 빈 리스트."""
        assert read_daemon_pending(tmp_path) == []

    def test_excludes_applied_paths(self, tmp_path: Path) -> None:
        """이미 applied 된 path 는 제외, 최신순 정렬."""
        from wiki_search_mcp.infrastructure.daemon.paths import (
            applied_jsonl,
            pending_jsonl,
            state_dir,
        )

        # state_dir 생성 보장
        sd = state_dir(tmp_path)
        sd.mkdir(parents=True, exist_ok=True)

        pj = pending_jsonl(tmp_path)
        aj = applied_jsonl(tmp_path)
        pj.write_text(
            "\n".join(
                json.dumps(e)
                for e in [
                    {"path": "a.md", "recorded_at": "2026-01-01"},
                    {"path": "b.md", "recorded_at": "2026-02-01"},
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        # a.md 는 applied 됨 → 제외돼야 함
        aj.write_text(
            json.dumps({"path_before": "a.md", "path_after": "infra/a.md"}) + "\n",
            encoding="utf-8",
        )

        items = read_daemon_pending(tmp_path)
        paths = [e["path"] for e in items]
        assert "a.md" not in paths
        assert "b.md" in paths
