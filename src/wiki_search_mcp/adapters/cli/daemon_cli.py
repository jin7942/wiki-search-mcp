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
# Wiki 경로 자동 탐지 (claude_desktop_config.json 재사용)
# -----------------------------------------------------------------------------

_CONFIG_LOCATIONS = (
    Path.home() / ".claude" / "claude_desktop_config.json",
    Path.home() / ".config" / "claude" / "claude_desktop_config.json",
)
_SERVER_NAME = "wiki-search"


def _find_claude_config_file() -> Path | None:
    for p in _CONFIG_LOCATIONS:
        if p.exists():
            return p
    return None


def _wiki_path_from_config() -> Path | None:
    """``claude_desktop_config.json``에서 wiki-search 서버 wiki 경로 추출.

    args 구조: ``["serve", "<wiki_path>", ...]``. 첫 위치 인자(serve 다음)를 사용.
    config 미존재 / 등록 서버 없음 / args 비정상 → ``None``.
    """
    cfg = _find_claude_config_file()
    if cfg is None:
        return None
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    servers = data.get("mcpServers") or {}
    server = servers.get(_SERVER_NAME)
    if not isinstance(server, dict):
        return None
    args = server.get("args")
    if not isinstance(args, list) or len(args) < 2:
        return None
    # 첫 인자는 'serve' (또는 다른 명령일 수도 있음). 두 번째가 wiki 경로.
    candidate = args[1]
    if not isinstance(candidate, str):
        return None
    p = Path(candidate).expanduser()
    return p if p.exists() else None


def _resolve_wiki_path(arg: str | None) -> Path:
    """위치 인자(또는 ``None``) → 절대 경로 ``Path``.

    인자 미지정 시 claude_desktop_config.json에서 자동 탐지.
    탐지 실패 시 친절한 안내와 함께 ``ClickException``.
    """
    if arg:
        p = Path(arg).expanduser().resolve()
        if not p.exists():
            raise click.ClickException(f"경로가 존재하지 않습니다: {p}")
        return p
    detected = _wiki_path_from_config()
    if detected is None:
        raise click.ClickException(
            "wiki 경로를 찾을 수 없습니다.\n"
            "다음 중 하나를 사용하세요:\n"
            "  1) 인자로 명시: wiki-search-mcp daemon <command> <path>\n"
            "  2) 먼저 등록:   wiki-search-mcp config <path>"
        )
    return detected.resolve()

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
    if kw.get("quiescence_seconds") not in (None, 60.0):
        args += ["--quiescence-seconds", str(kw["quiescence_seconds"])]
    if kw.get("min_body_chars") not in (None, 200):
        args += ["--min-body-chars", str(kw["min_body_chars"])]
    if kw.get("rescan_interval_seconds") not in (None, 300.0):
        args += ["--rescan-interval-seconds", str(kw["rescan_interval_seconds"])]
    if kw.get("auto_move") is False:
        args += ["--no-auto-move"]
    if kw.get("rewrite_inbound_links") is False:
        args += ["--no-rewrite-inbound-links"]
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
        quiescence_seconds=kw["quiescence_seconds"],
        min_body_chars=kw["min_body_chars"],
        rescan_interval_seconds=kw["rescan_interval_seconds"],
        auto_move=kw["auto_move"],
        rewrite_inbound_links=kw["rewrite_inbound_links"],
        log_level=kw["log_level"],
    )


def _maybe_migrate_state(wiki: Path) -> None:
    """vault 경로 이전으로 고립된 옛 daemon state 를 안전 조건 하에 자동 이전.

    안전 조건(``auto_migrate_if_safe``)을 만족하면 조용히 이전하고 결과를 echo한다.
    후보가 여러 개라 자동 이전을 보류한 경우, 사용자가 직접 정리하도록 안내만 한다.
    """
    from wiki_search_mcp.infrastructure.daemon.state_migrate import (
        auto_migrate_if_safe,
        find_stale_candidates,
    )

    migrated = auto_migrate_if_safe(wiki)
    if migrated is not None:
        click.echo(
            f"옛 작업 이력을 이전했습니다 "
            f"(applied={migrated.applied_count}, pending={migrated.pending_count}, "
            f"이전 경로={migrated.recorded_wiki_path})."
        )
        return
    # 자동 이전 안 된 경우 — 후보가 2개 이상이면 안내
    candidates = find_stale_candidates(wiki)
    if len(candidates) > 1:
        click.echo(
            f"[주의] 이전 가능한 옛 state 디렉토리가 {len(candidates)}개 발견됐습니다. "
            "어느 것이 현재 vault의 이력인지 모호해 자동 이전을 건너뜁니다.",
            err=True,
        )
        for c in candidates:
            click.echo(
                f"  - {c.state_dir} (applied={c.applied_count}, "
                f"pending={c.pending_count}, wiki_path={c.recorded_wiki_path})",
                err=True,
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
@click.argument("wiki_path", type=click.Path(exists=True), required=False)
@click.option("--llm-model", default="haiku", show_default=True, help='Claude 모델 alias 또는 풀 ID')
@click.option("--confidence-threshold", type=float, default=0.70, show_default=True)
@click.option("--concurrency", type=int, default=2, show_default=True)
@click.option("--rate-per-minute", type=int, default=5, show_default=True)
@click.option("--rate-per-hour", type=int, default=100, show_default=True)
@click.option("--rate-per-day", type=int, default=500, show_default=True)
@click.option("--debounce", type=float, default=2.0, show_default=True)
@click.option(
    "--quiescence-seconds",
    type=float,
    default=60.0,
    show_default=True,
    help="파일이 정적 상태로 머물러야 분류 진입을 허용하는 최소 시간 (작성 중 인터럽트 방지)",
)
@click.option(
    "--min-body-chars",
    type=int,
    default=200,
    show_default=True,
    help="분류 진입을 허용하는 본문 최소 길이 (미만이면 pending)",
)
@click.option(
    "--rescan-interval-seconds",
    type=float,
    default=300.0,
    show_default=True,
    help="외부 FS 이벤트 없이도 daemon이 스스로 rescan하는 주기 (0이면 비활성)",
)
@click.option("--auto-move/--no-auto-move", default=True, show_default=True)
@click.option(
    "--rewrite-inbound-links/--no-rewrite-inbound-links",
    default=True,
    show_default=True,
    help="파일 이동 시 다른 파일 본문의 [[옛 경로]] wikilink를 새 경로로 보정",
)
@click.option("--foreground", is_flag=True, help="현재 터미널에서 실행 (디버깅용)")
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    show_default=True,
)
def start(wiki_path: str | None, **kw: object) -> None:
    """Wiki 폴더를 감시하며 LLM으로 자동 분류하는 daemon을 시작합니다.

    WIKI_PATH는 선택입니다. 생략 시 ``claude_desktop_config.json``의 ``wiki-search``
    서버 등록 정보에서 자동으로 경로를 가져옵니다 (``wiki-search-mcp config`` 결과 재사용).
    """
    wiki = _resolve_wiki_path(wiki_path)
    _check_claude_cli_or_die()
    _check_claude_logged_in_or_hint()

    alive, pid = PidLock.is_alive(pid_file(wiki))
    if alive:
        raise click.ClickException(
            f"daemon이 이미 실행 중입니다 (pid={pid}). 먼저 `daemon stop` 을 실행하세요."
        )

    _maybe_migrate_state(wiki)

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
@click.argument("wiki_path", type=click.Path(exists=True), required=False)
@click.option("--timeout", type=float, default=10.0, show_default=True)
def stop(wiki_path: str | None, timeout: float) -> None:
    """실행 중인 daemon을 종료합니다 (SIGTERM → 10초 후 SIGKILL).

    WIKI_PATH 생략 시 config 등록 정보에서 자동 탐지.
    """
    wiki = _resolve_wiki_path(wiki_path)
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
@click.argument("wiki_path", type=click.Path(exists=True), required=False)
def status(wiki_path: str | None) -> None:
    """daemon 상태를 JSON으로 출력.

    WIKI_PATH 생략 시 config 등록 정보에서 자동 탐지.
    """
    wiki = _resolve_wiki_path(wiki_path)
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
@click.argument("wiki_path", type=click.Path(exists=True), required=False)
@click.option("-n", "--lines", default=50, show_default=True, help="마지막 N줄")
@click.option("-f", "--follow", is_flag=True, help="실시간 출력")
def logs(wiki_path: str | None, lines: int, follow: bool) -> None:
    """daemon 로그를 표시 (tail / tail -f).

    WIKI_PATH 생략 시 config 등록 정보에서 자동 탐지.
    """
    wiki = _resolve_wiki_path(wiki_path)
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


@daemon.command("migrate-state")
@click.argument("source", type=click.Path(exists=True))
@click.argument("wiki_path", type=click.Path(exists=True), required=False)
@click.option(
    "--overwrite",
    is_flag=True,
    help="현재 state 에 데이터가 있어도 덮어쓴다 (위험)",
)
def migrate_state(source: str, wiki_path: str | None, overwrite: bool) -> None:
    """수동으로 옛 daemon state 디렉토리를 현재 wiki 로 이전합니다.

    SOURCE 는 옛 state 디렉토리 (또는 그 안의 ``daemon_status.json``) 경로.
    자동 마이그레이션이 ambiguous (옛 후보 2개 이상) 로 보류된 경우의 fallback.

    WIKI_PATH 생략 시 config 등록 정보에서 자동 탐지.
    """
    from wiki_search_mcp.infrastructure.daemon.state_migrate import migrate_from

    wiki = _resolve_wiki_path(wiki_path)
    src = Path(source).expanduser().resolve()
    try:
        result = migrate_from(src, wiki, overwrite=overwrite)
    except FileExistsError as e:
        raise click.ClickException(str(e)) from e
    except FileNotFoundError as e:
        raise click.ClickException(str(e)) from e

    click.echo(
        f"옛 작업 이력을 이전했습니다 "
        f"(applied={result.applied_count}, pending={result.pending_count}, "
        f"이전 경로={result.recorded_wiki_path})."
    )


@daemon.command("rollback")
@click.argument("wiki_path", type=click.Path(exists=True), required=False)
@click.option("--last", "last_n", type=int, default=1, show_default=True, help="마지막 N개 적용 되돌리기")
@click.option("--dry-run", is_flag=True, help="실제 변경 없이 영향만 표시")
@click.option("--force", is_flag=True, help="daemon이 실행 중이어도 진행")
def rollback(wiki_path: str | None, last_n: int, dry_run: bool, force: bool) -> None:
    """applied.jsonl의 마지막 N개 적용을 역재생합니다.

    WIKI_PATH 생략 시 config 등록 정보에서 자동 탐지.
    """
    wiki = _resolve_wiki_path(wiki_path)
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


@daemon.command("install")
@click.argument("wiki_path", type=click.Path(exists=True), required=False)
def install(wiki_path: str | None) -> None:
    """daemon을 OS 서비스로 등록해 죽으면 자동 재기동되게 합니다.

    macOS는 launchd LaunchAgent, Linux는 systemd user service를 생성/로드합니다.
    OS가 supervisor 역할을 하므로 로그아웃/재부팅 후에도 daemon이 자동 기동됩니다.

    WIKI_PATH 생략 시 config 등록 정보에서 자동 탐지.
    """
    from wiki_search_mcp.infrastructure.daemon.service_unit import (
        build_unit,
        resolve_cli_path,
    )

    wiki = _resolve_wiki_path(wiki_path)
    _check_claude_cli_or_die()
    _check_claude_logged_in_or_hint()

    cli = resolve_cli_path()
    try:
        unit = build_unit(wiki, cli, log_file(wiki))
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e

    unit.unit_path.parent.mkdir(parents=True, exist_ok=True)
    unit.unit_path.write_text(unit.content, encoding="utf-8")
    click.echo(f"유닛 파일 생성: {unit.unit_path}")

    if unit.kind == "launchd":
        # 기존 로드 해제 후 재로드 (idempotent)
        subprocess.run(
            ["launchctl", "unload", str(unit.unit_path)],
            capture_output=True,
            check=False,
        )
        result = subprocess.run(
            ["launchctl", "load", str(unit.unit_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise click.ClickException(
                f"launchctl load 실패: {result.stderr.strip()}"
            )
        click.echo(f"launchd 서비스 로드됨: {unit.label}")
    else:  # systemd
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
            check=False,
        )
        result = subprocess.run(
            ["systemctl", "--user", "enable", "--now", f"{unit.label}.service"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise click.ClickException(
                f"systemctl enable --now 실패: {result.stderr.strip()}\n"
                "user service가 로그아웃 후에도 동작하려면 `loginctl enable-linger` 가 "
                "필요할 수 있습니다."
            )
        click.echo(f"systemd 서비스 활성화됨: {unit.label}")

    click.echo("daemon이 OS에 의해 자동 관리됩니다 (죽으면 재기동).")
    click.echo(f"상태 확인: wiki-search-mcp daemon status {wiki}")


@daemon.command("uninstall")
@click.argument("wiki_path", type=click.Path(exists=True), required=False)
def uninstall(wiki_path: str | None) -> None:
    """``daemon install`` 로 등록한 OS 서비스를 해제하고 유닛 파일을 삭제합니다.

    WIKI_PATH 생략 시 config 등록 정보에서 자동 탐지.
    """
    from wiki_search_mcp.infrastructure.daemon.service_unit import (
        build_unit,
        resolve_cli_path,
    )

    wiki = _resolve_wiki_path(wiki_path)
    try:
        unit = build_unit(wiki, resolve_cli_path(), log_file(wiki))
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e

    if unit.kind == "launchd":
        subprocess.run(
            ["launchctl", "unload", str(unit.unit_path)],
            capture_output=True,
            check=False,
        )
    else:  # systemd
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", f"{unit.label}.service"],
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
            check=False,
        )

    if unit.unit_path.exists():
        unit.unit_path.unlink()
        click.echo(f"유닛 파일 삭제: {unit.unit_path}")
    else:
        click.echo("등록된 유닛 파일이 없습니다.")
    click.echo(f"서비스 해제됨: {unit.label}")


__all__ = ["daemon"]
