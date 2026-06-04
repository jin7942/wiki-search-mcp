"""Daemon 라이프사이클 인프라.

서브모듈:
- ``paths``: 상태 디렉토리/파일 경로 헬퍼
- ``pidfile``: PID 파일 + fcntl flock 기반 단일 인스턴스 보장
- ``statefile``: 원자적 JSON read/write로 daemon 상태 노출
- ``ratelimit``: 분/시/일 sliding window rate limiter
- ``options``: DaemonOptions dataclass
- ``runner``: DaemonRunner (asyncio main loop)
"""

from wiki_search_mcp.infrastructure.daemon.options import DaemonOptions
from wiki_search_mcp.infrastructure.daemon.paths import (
    applied_jsonl,
    log_file,
    pending_jsonl,
    pid_file,
    serve_lock_file,
    serve_pid_file,
    state_dir,
    state_lock_file,
    status_file,
)
from wiki_search_mcp.infrastructure.daemon.pidfile import PidLock
from wiki_search_mcp.infrastructure.daemon.ratelimit import SlidingWindowRateLimit
from wiki_search_mcp.infrastructure.daemon.statefile import StatusFile
from wiki_search_mcp.infrastructure.daemon.status_reader import (
    read_daemon_pending,
    read_daemon_status,
)

__all__ = [
    "DaemonOptions",
    "PidLock",
    "SlidingWindowRateLimit",
    "StatusFile",
    "applied_jsonl",
    "log_file",
    "pending_jsonl",
    "pid_file",
    "read_daemon_pending",
    "read_daemon_status",
    "serve_lock_file",
    "serve_pid_file",
    "state_dir",
    "state_lock_file",
    "status_file",
]
