"""Daemon 상태/pending 조회 facade.

daemon 은 별도 프로세스라 service 계층이 그 상태를 추상화하지 않는다. 그래서
adapters(MCP server/handlers)가 daemon 상태 파일을 직접 읽어야 했고, 동일한
읽기 로직이 server._read_daemon_status / server._read_daemon_pending /
handlers.handle_wiki_daemon_status 3곳에 복붙돼 있었다.

이 모듈이 그 읽기 로직을 한 곳으로 모은다. adapters 는 이 facade 만 호출하면
되므로, infrastructure.daemon 내부 구조(StatusFile/PidLock/JsonlLog/paths)에
대한 직접 의존이 이 파일 한 곳으로 집중된다(계층 경계 침범 완화).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from wiki_search_mcp.infrastructure.daemon.paths import (
    applied_jsonl,
    pending_jsonl,
    pid_file,
    status_file,
)
from wiki_search_mcp.infrastructure.daemon.pidfile import PidLock
from wiki_search_mcp.infrastructure.daemon.statefile import StatusFile
from wiki_search_mcp.infrastructure.jsonl.log import JsonlLog


def read_daemon_status(
    wiki_path: Path,
    *,
    status_reader: StatusFile | None = None,
    pid_checker: Callable[[Path], tuple[bool, int | None]] | None = None,
) -> dict[str, Any]:
    """daemon 상태를 ``{state/alive/pid/...}`` dict 로 반환.

    실패해도 raise 하지 않고 항상 dict 를 돌려준다(상태 조회는 본 응답을
    막아서는 안 된다).

    Args:
        wiki_path: wiki 루트 경로.
        status_reader: 테스트 주입용 StatusFile. None 이면 즉석 생성.
        pid_checker: 테스트 주입용 PID 생존 확인 hook. None 이면 PidLock.is_alive.

    Returns:
        - daemon 미실행: ``{"state": "not_running", "alive": False, "pid": None}``
        - 실행/상태 있음: ``{**state_data, "alive": ..., "pid": ...}``
        - 조회 실패: ``{"state": "unknown", "error": "..."}``
    """
    try:
        reader = (
            status_reader
            if status_reader is not None
            else StatusFile(status_file(wiki_path))
        )
        state_data = reader.read() or {}
        checker = pid_checker if pid_checker is not None else PidLock.is_alive
        alive, pid = checker(pid_file(wiki_path))
        if not state_data and not alive:
            return {"state": "not_running", "alive": False, "pid": None}
        return {**state_data, "alive": alive, "pid": pid}
    except Exception as e:  # noqa: BLE001 - 상태 조회 실패는 응답을 막으면 안 됨
        return {"state": "unknown", "error": str(e)[:200]}


def read_daemon_pending(wiki_path: Path, limit: int = 50) -> list[dict[str, Any]]:
    """daemon pending.jsonl 의 active entry 를 path별 최신 1개만 반환.

    이미 applied 된 path 는 제외한다. 실패 시 빈 리스트.

    Args:
        wiki_path: wiki 루트 경로.
        limit: 최대 반환 개수.

    Returns:
        recorded_at 내림차순으로 정렬된 pending entry 리스트(최대 limit).
    """
    try:
        pending = JsonlLog(pending_jsonl(wiki_path))
        applied = JsonlLog(applied_jsonl(wiki_path))
        latest_pending: dict[str, dict] = {}
        for entry in pending.scan():
            path = entry.get("path")
            if isinstance(path, str):
                latest_pending[path] = entry
        applied_paths: set[str] = set()
        for entry in applied.scan():
            for key in ("path_before", "path_after"):
                v = entry.get(key)
                if isinstance(v, str):
                    applied_paths.add(v)
        items = [e for p, e in latest_pending.items() if p not in applied_paths]
        items.sort(key=lambda e: e.get("recorded_at", ""), reverse=True)
        return items[:limit]
    except Exception:  # noqa: BLE001
        return []
