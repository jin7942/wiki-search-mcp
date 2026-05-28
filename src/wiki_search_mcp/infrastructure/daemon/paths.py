"""Daemon 상태 파일 경로 헬퍼.

XDG_STATE_HOME 표준을 따른다. 기본은 ``~/.local/state/wiki-search-mcp/<wiki-hash>/``.
wiki_path 별로 별도 디렉토리를 사용하므로 한 머신에서 여러 wiki를 동시 운영 가능.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def _hash_wiki_path(wiki_path: Path) -> str:
    """wiki 절대경로의 짧은 SHA-1 (12자) 해시."""
    return hashlib.sha1(str(wiki_path.resolve()).encode("utf-8")).hexdigest()[:12]


def state_dir(wiki_path: Path) -> Path:
    """``~/.local/state/wiki-search-mcp/<wiki-hash>/`` 반환 (자동 생성).

    ``XDG_STATE_HOME`` 환경변수가 설정돼 있으면 그것을 우선.
    """
    base_env = os.environ.get("XDG_STATE_HOME")
    base = Path(base_env) if base_env else Path.home() / ".local" / "state"
    out = base / "wiki-search-mcp" / _hash_wiki_path(Path(wiki_path))
    out.mkdir(parents=True, exist_ok=True)
    return out


def pid_file(wiki_path: Path) -> Path:
    return state_dir(wiki_path) / "daemon.pid"


def state_lock_file(wiki_path: Path) -> Path:
    return state_dir(wiki_path) / "daemon.lock"


def serve_pid_file(wiki_path: Path) -> Path:
    """MCP serve 프로세스용 PID 파일 (daemon과 별도).

    같은 vault에 대해 serve 인스턴스가 중복 기동되는 것을 막기 위한 단일 인스턴스
    표식. daemon.pid 와 구분해 두 프로세스가 독립적으로 락을 잡도록 한다.
    """
    return state_dir(wiki_path) / "serve.pid"


def serve_lock_file(wiki_path: Path) -> Path:
    """MCP serve 프로세스용 flock 락 파일 (daemon.lock 과 별도)."""
    return state_dir(wiki_path) / "serve.lock"


def log_file(wiki_path: Path) -> Path:
    return state_dir(wiki_path) / "daemon.log"


def status_file(wiki_path: Path) -> Path:
    return state_dir(wiki_path) / "daemon_status.json"


def pending_jsonl(wiki_path: Path) -> Path:
    return state_dir(wiki_path) / "pending.jsonl"


def applied_jsonl(wiki_path: Path) -> Path:
    return state_dir(wiki_path) / "applied.jsonl"
