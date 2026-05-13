"""``wiki-search-mcp daemon ...`` 서브커맨드.

start / stop / status / logs / rollback 다섯 명령을 제공한다.
실제 daemon 로직은 ``infrastructure.daemon.runner.DaemonRunner``에 있고,
이 모듈은 그 진입점/라이프사이클/표시만 책임진다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import click

from wiki_search_mcp.core.exceptions import DaemonError
from wiki_search_mcp.infrastructure.daemon.options import DaemonOptions
from wiki_search_mcp.infrastructure.daemon.paths import (
    applied_jsonl,
    log_file,
    pending_jsonl,
    pid_file,
    state_dir,
    status_file,
)
from wiki_search_mcp.infrastructure.daemon.pidfile import PidLock
from wiki_search_mcp.infrastructure.daemon.statefile import StatusFile

# -----------------------------------------------------------------------------
# 사전 검증
# -----------------------------------------------------------------------------


def _resolve_claude_cli() -> str | None:
    """``claude`` CLI 경로 탐지.

    1. ``shutil.which("claude")``
    2. claude-agent-sdk가 번들한 CLI
    """
    p = shutil.which("claude")
    if p:
        return p
    try:
        import claude_agent_sdk  # type: ignore[import-untyped]

        sdk_dir = Path(claude_agent_sdk.__file__).parent
        # SDK 번들 경로 후보 (버전에 따라 다를 수 있음)
        for candidate in ("cli/claude", "bin/claude", "node_modules/.bin/claude"):
            full = sdk_dir / candidate
            if full.exists():
                return str(full)
    except Exception:
        pass
    return None


def _check_claude_cli_or_die() -> None:
    """claude CLI 또는 SDK 번들 검증. 실패 시 친절한 메시지로 종료."""
    if _resolve_claude_cli() is None:
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError as e:
            raise click.ClickException(
                "claude-agent-sdk가 설치되어 있지 않습니다.\n"
                "  pip install -U claude-agent-sdk\n"
                "또는 claude CLI 설치: https://docs.anthropic.com/claude/code"
            ) from e


def _check_claude_logged_in_or_hint() -> None:
    """OAuth credential 존재 여부 안내 (없어도 실패시키지 않고 경고만)."""
    candidates = [
        Path.home() / ".claude" / ".credentials.json",
        Path.home() / ".config" / "claude" / ".credentials.json",
    ]
    if not any(p.exists() for p in candidates):
        click.echo(
            "[주의] Claude OAuth 자격증명을 찾지 못했습니다. "
            "daemon이 분류에 실패할 수 있습니다.\n"
            "  먼저 `claude login` 을 실행하세요.",
            err=True,
        )


# -----------------------------------------------------------------------------
# 옵션 전달 헬퍼
# -----------------------------------------------------------------------------


def _passthrough_args(kw: dict) -> list[str]:
    """background subprocess에 다시 넘길 옵션 직렬화 (--foreground 제외)."""
    args: list[str] = []
    if kw.get("llm_model") and kw["llm_model"] != "haiku":
        args += ["--llm-model", str(kw["llm_model"])]
    if kw.get("confidence_threshold") not in (None, 0.70):
        args += ["--confidence-threshold", str(kw["confidence_threshold"])]
    if kw.get("concurrency") not in (None, 2):
        args += ["--concurrency", str(kw["concurrency"])]
    if kw.get("rate_per_minute") not in (None, 5):
        args += ["--rate-per-minute", str(kw["rate_per_minute"])]
    if kw.get("rate_per_hour") not in (None, 100):
        args += ["--rate-per-hour", str(kw["rate_per_hour"])]
    if kw.get("rate_per_day") not in (None, 500):
        args += ["--rate-per-day", str(kw["rate_per_day"])]
    if kw.get("debounce") not in (None, 2.0):
        args += ["--debounce", str(kw["debounce"])]
    if kw.get("auto_move") is False:
        args += ["--no-auto-move"]
    if kw.get("log_level") and kw["log_level"] != "INFO":
        args += ["--log-level", str(kw["log_level"])]
    return args


def _build_options(wiki: Path, kw: dict) -> DaemonOptions:
    return DaemonOptions(
        wiki_path=wiki,
        llm_model=kw["llm_model"],
        confidence_threshold=kw["confidence_threshold"],
        concurrency=kw["concurrency"],
        rate_per_minute=kw["rate_per_minute"],
        rate_per_hour=kw["rate_per_hour"],
        rate_per_day=kw["rate_per_day"],
        debounce=kw["debounce"],
        auto_move=kw["auto_move"],
        log_level=kw["log_level"],
    )


def _wait_for_pidfile(path: Path, *, timeout: float) -> int | None:
    """daemon이 PID 파일을 쓸 때까지 대기. 성공 시 PID 반환, 실패 시 None."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                return int(path.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                pass
        time.sleep(0.2)
    return None


# -----------------------------------------------------------------------------
# Commands
# -----------------------------------------------------------------------------


@click.group()
def daemon() -> None:
    """백그라운드 자동 분류 daemon 관리."""


@daemon.command("start")
@click.argument("wiki_path", type=click.Path(exists=True))
@click.option("--llm-model", default="haiku", show_default=True, help='Claude 모델 alias 또는 풀 ID')
@click.option("--confidence-threshold", type=float, default=0.70, show_default=True)
@click.option("--concurrency", type=int, default=2, show_default=True)
@click.option("--rate-per-minute", type=int, default=5, show_default=True)
@click.option("--rate-per-hour", type=int, default=100, show_default=True)
@click.option("--rate-per-day", type=int, default=500, show_default=True)
@click.option("--debounce", type=float, default=2.0, show_default=True)
@click.option("--auto-move/--no-auto-move", default=True, show_default=True)
@click.option("--foreground", is_flag=True, help="현재 터미널에서 실행 (디버깅용)")
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    show_default=True,
)
def start(wiki_path: str, **kw: object) -> None:
    """Wiki 폴더를 감시하며 LLM으로 자동 분류하는 daemon을 시작합니다."""
    wiki = Path(wiki_path).resolve()
    _check_claude_cli_or_die()
    _check_claude_logged_in_or_hint()

    alive, pid = PidLock.is_alive(pid_file(wiki))
    if alive:
        raise click.ClickException(
            f"daemon이 이미 실행 중입니다 (pid={pid}). 먼저 `daemon stop` 을 실행하세요."
        )

    opts = _build_options(wiki, kw)  # type: ignore[arg-type]

    foreground = bool(kw.get("foreground"))
    if foreground:
        from wiki_search_mcp.infrastructure.daemon.runner import DaemonRunner

        DaemonRunner(opts).start()
        return

    # 백그라운드 spawn: 같은 CLI를 --foreground로 다시 호출
    log_path = log_file(wiki)
    cmd = [
        sys.executable,
        "-m",
        "wiki_search_mcp.adapters.cli.main",
        "daemon",
        "start",
        str(wiki),
        "--foreground",
        *_passthrough_args(kw),  # type: ignore[arg-type]
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as lf:
        proc = subprocess.Popen(
            cmd,
            stdout=lf,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(wiki),
        )

    pid_value = _wait_for_pidfile(pid_file(wiki), timeout=15.0)
    if pid_value is None:
        # 시작 실패 — 로그 마지막 50줄 보여주고 종료
        click.echo("daemon 시작 실패. 로그 마지막 50줄:", err=True)
        try:
            text = log_path.read_text(encoding="utf-8")
            tail = "\n".join(text.splitlines()[-50:])
            click.echo(tail, err=True)
        except OSError:
            pass
        raise click.ClickException("daemon 시작 시 timeout 발생")

    click.echo(f"daemon 시작됨 (pid={pid_value}).")
    click.echo(f"로그: wiki-search-mcp daemon logs {wiki}")


@daemon.command("stop")
@click.argument("wiki_path", type=click.Path(exists=True))
@click.option("--timeout", type=float, default=10.0, show_default=True)
def stop(wiki_path: str, timeout: float) -> None:
    """실행 중인 daemon을 종료합니다 (SIGTERM → 10초 후 SIGKILL)."""
    wiki = Path(wiki_path).resolve()
    alive, pid = PidLock.is_alive(pid_file(wiki))
    if not alive or pid is None:
        raise click.ClickException("daemon이 실행 중이 아닙니다.")
    ok = PidLock.terminate(pid, timeout=timeout)
    if not ok:
        raise click.ClickException(f"daemon 종료 실패 (pid={pid})")
    # PID 파일 정리 — daemon 자체가 PidLock release에서 처리하지만 강제 종료 시 남을 수 있음
    try:
        pid_file(wiki).unlink()
    except FileNotFoundError:
        pass
    click.echo(f"daemon 종료 완료 (pid={pid}).")


@daemon.command("status")
@click.argument("wiki_path", type=click.Path(exists=True))
def status(wiki_path: str) -> None:
    """daemon 상태를 JSON으로 출력."""
    wiki = Path(wiki_path).resolve()
    alive, pid = PidLock.is_alive(pid_file(wiki))
    state = StatusFile(status_file(wiki)).read() or {}
    payload = {
        "wiki_path": str(wiki),
        "alive": alive,
        "pid": pid,
        "state_dir": str(state_dir(wiki)),
        **state,
    }
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@daemon.command("logs")
@click.argument("wiki_path", type=click.Path(exists=True))
@click.option("-n", "--lines", default=50, show_default=True, help="마지막 N줄")
@click.option("-f", "--follow", is_flag=True, help="실시간 출력")
def logs(wiki_path: str, lines: int, follow: bool) -> None:
    """daemon 로그를 표시 (tail / tail -f)."""
    wiki = Path(wiki_path).resolve()
    path = log_file(wiki)
    if not path.exists():
        raise click.ClickException(f"로그 파일 없음: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    tail = "\n".join(text.splitlines()[-lines:])
    click.echo(tail)
    if not follow:
        return
    pos = os.path.getsize(path)
    try:
        while True:
            try:
                size = os.path.getsize(path)
            except FileNotFoundError:
                size = 0
            if size > pos:
                with open(path, "r", encoding="utf-8", errors="replace") as fp:
                    fp.seek(pos)
                    chunk = fp.read()
                    if chunk:
                        click.echo(chunk, nl=False)
                pos = size
            elif size < pos:
                # truncate/rotate 발생
                pos = 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        return


@daemon.command("rollback")
@click.argument("wiki_path", type=click.Path(exists=True))
@click.option("--last", "last_n", type=int, default=1, show_default=True, help="마지막 N개 적용 되돌리기")
@click.option("--dry-run", is_flag=True, help="실제 변경 없이 영향만 표시")
@click.option("--force", is_flag=True, help="daemon이 실행 중이어도 진행")
def rollback(wiki_path: str, last_n: int, dry_run: bool, force: bool) -> None:
    """applied.jsonl의 마지막 N개 적용을 역재생합니다."""
    wiki = Path(wiki_path).resolve()
    alive, pid = PidLock.is_alive(pid_file(wiki))
    if alive and not force:
        raise click.ClickException(
            f"daemon이 실행 중입니다 (pid={pid}). 먼저 stop하거나 --force 사용."
        )

    from wiki_search_mcp.adapters.mcp.container import ServiceContainer
    from wiki_search_mcp.infrastructure.jsonl.log import JsonlLog
    from wiki_search_mcp.services.rollback_service import RollbackService

    container = ServiceContainer(str(wiki))
    applied_log = JsonlLog(applied_jsonl(wiki))
    service = RollbackService(applied_log=applied_log, pages_path=container.pages_path)
    results = service.rollback_last(last_n, dry_run=dry_run)
    click.echo(json.dumps({"dry_run": dry_run, "count": len(results), "results": results}, ensure_ascii=False, indent=2))


__all__ = ["daemon"]
