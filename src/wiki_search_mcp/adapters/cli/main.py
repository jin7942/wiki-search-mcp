#!/usr/bin/env python3
from __future__ import annotations

"""Wiki Search MCP CLI

명령줄 도구로 wiki-search-mcp를 관리합니다.

Commands:
- config: Claude Desktop 설정
- index: 수동 인덱싱
- serve: MCP 서버 실행 (직접 호출용)

환경변수를 사용하지 않습니다. 모든 설정은 위치 인자/플래그로 전달합니다.
"""

import json
from pathlib import Path

import click

from wiki_search_mcp import __version__


# =============================================================================
# 공통 옵션 데코레이터 + 직렬화 헬퍼
# =============================================================================


def _runtime_options(func):
    """serve / config 명령에 공통으로 붙는 런타임 옵션 데코레이터."""
    func = click.option(
        "--log-file",
        type=click.Path(),
        default=None,
        help="로그 파일 경로 (기본: stderr만)",
    )(func)
    func = click.option(
        "--log-level",
        type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
        default="WARNING",
        show_default=True,
        help="로그 레벨",
    )(func)
    func = click.option(
        "--debounce",
        type=float,
        default=2.0,
        show_default=True,
        help="파일 감시 디바운스(초)",
    )(func)
    func = click.option(
        "--no-watch",
        "watch",
        is_flag=True,
        flag_value=False,
        default=True,
        help="파일 감시 비활성화 (기본: 활성)",
    )(func)
    func = click.option(
        "--ignore",
        "ignore_patterns",
        multiple=True,
        metavar="PATTERN",
        help="추가 무시 패턴 (반복 가능, 예: --ignore draft --ignore '*.bak')",
    )(func)
    func = click.option(
        "--model",
        default=None,
        metavar="NAME",
        help="임베딩 모델 프리셋 (fast / accurate) 또는 모델명",
    )(func)
    return func


def _options_to_args(
    *,
    model: str | None,
    ignore_patterns: tuple[str, ...],
    watch: bool,
    debounce: float,
    log_level: str,
    log_file: str | None,
) -> list[str]:
    """런타임 옵션을 ``args`` 배열에 직렬화 (비-기본값만)."""
    args: list[str] = []
    if model:
        args += ["--model", model]
    for pattern in ignore_patterns:
        args += ["--ignore", pattern]
    if not watch:
        args += ["--no-watch"]
    if debounce != 2.0:
        args += ["--debounce", str(debounce)]
    if log_level != "WARNING":
        args += ["--log-level", log_level]
    if log_file:
        args += ["--log-file", str(log_file)]
    return args


# =============================================================================
# CLI Group
# =============================================================================


@click.group()
@click.version_option(version=__version__)
def main():
    """Wiki Search MCP - 자동 분류 PKM MCP 서버."""
    pass  # Click group entry point - subcommands handle actual work


# =============================================================================
# config
# =============================================================================


@main.command()
@click.argument("wiki_path", type=click.Path(exists=True))
@click.option(
    "--config-path",
    type=click.Path(),
    help="Claude Desktop 설정 파일 경로 (기본: 자동 탐지)",
)
@_runtime_options
def config(
    wiki_path: str,
    config_path: str | None,
    model: str | None,
    ignore_patterns: tuple[str, ...],
    watch: bool,
    debounce: float,
    log_level: str,
    log_file: str | None,
):
    """Claude Desktop에 MCP 서버를 등록합니다.

    WIKI_PATH는 노트 디렉토리 경로입니다. 빈 디렉토리도 허용되며,
    필요한 경우 자동으로 인덱스(.vectordb)가 생성됩니다.

    추가 옵션(--model, --no-watch 등)을 지정하면 ``args`` 배열에 함께
    직렬화되어 ``serve`` 호출 시 그대로 전달됩니다.

    예시:
        wiki-search-mcp config ./my-notes
        wiki-search-mcp config ~/obsidian-vault --model fast
        wiki-search-mcp config ~/notes --no-watch --ignore draft
    """
    wiki_path = Path(wiki_path).resolve()

    # Claude Desktop 설정 파일 경로 탐지
    if config_path:
        config_file = Path(config_path)
    else:
        # macOS
        config_file = Path.home() / ".claude" / "claude_desktop_config.json"
        if not config_file.exists():
            # Linux/Windows 대안
            config_file = (
                Path.home() / ".config" / "claude" / "claude_desktop_config.json"
            )

    # 설정 파일 로드 또는 생성
    if config_file.exists():
        existing_config = json.loads(config_file.read_text(encoding="utf-8"))
    else:
        existing_config = {}
        config_file.parent.mkdir(parents=True, exist_ok=True)

    # mcpServers 섹션 확인/생성
    if "mcpServers" not in existing_config:
        existing_config["mcpServers"] = {}

    # args 배열 빌드
    args = ["serve", str(wiki_path)] + _options_to_args(
        model=model,
        ignore_patterns=ignore_patterns,
        watch=watch,
        debounce=debounce,
        log_level=log_level,
        log_file=log_file,
    )

    # wiki-search 서버 설정 (env 사용 안 함)
    existing_config["mcpServers"]["wiki-search"] = {
        "command": "wiki-search-mcp",
        "args": args,
    }

    # 설정 저장
    config_file.write_text(
        json.dumps(existing_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    click.echo(f"설정이 저장되었습니다: {config_file}")
    click.echo("")
    click.echo("등록된 서버:")
    click.echo("  이름: wiki-search")
    click.echo(f"  Wiki path: {wiki_path}")
    click.echo(f"  args: {args}")
    click.echo("")
    click.echo("Claude Desktop을 재시작하면 적용됩니다.")


# =============================================================================
# index
# =============================================================================


@main.command()
@click.argument("wiki_path", type=click.Path(exists=True))
@click.option("--full", "-f", is_flag=True, help="전체 재구축")
@click.option(
    "--model",
    default=None,
    metavar="NAME",
    help="임베딩 모델 프리셋 (fast / accurate) 또는 모델명",
)
@click.option(
    "--ignore",
    "ignore_patterns",
    multiple=True,
    metavar="PATTERN",
    help="추가 무시 패턴 (반복 가능)",
)
def index(
    wiki_path: str,
    full: bool,
    model: str | None,
    ignore_patterns: tuple[str, ...],
):
    """Wiki 인덱스를 수동으로 구축합니다.

    예시:
        wiki-search-mcp index ./my-notes
        wiki-search-mcp index ./my-notes --full
        wiki-search-mcp index ~/notes --full --model fast --ignore draft
    """
    wiki_path = Path(wiki_path).resolve()

    # pages 디렉토리 확인 (경고만, 오류 아님)
    pages_path = wiki_path / "pages"
    if not pages_path.exists():
        md_files = list(wiki_path.rglob("*.md"))
        if not md_files:
            click.echo(f"경고: {wiki_path}에 .md 파일이 없습니다.", err=True)
        else:
            click.echo(f"pages/ 없음. {wiki_path}를 문서 루트로 사용합니다.")

    click.echo(f"인덱싱 시작: {wiki_path}")
    click.echo("모드: 전체 재구축" if full else "모드: 증분 업데이트")

    from wiki_search_mcp.infrastructure.indexing import WikiIndexer

    indexer = WikiIndexer(
        str(wiki_path),
        model_name=model,
        ignore_patterns=tuple(ignore_patterns),
    )
    result = indexer.reindex(full=full)

    click.echo("")
    click.echo("결과:")
    click.echo(f"  인덱싱된 문서: {result['indexed']}")
    click.echo(f"  갱신된 문서: {result['updated']}")
    click.echo(f"  소요 시간: {result['duration_ms']}ms")


# =============================================================================
# serve
# =============================================================================


@main.command()
@click.argument("wiki_path", type=click.Path())
@_runtime_options
def serve(
    wiki_path: str,
    model: str | None,
    ignore_patterns: tuple[str, ...],
    watch: bool,
    debounce: float,
    log_level: str,
    log_file: str | None,
):
    """MCP 서버를 실행합니다.

    일반적으로 Claude Desktop이 자동으로 호출합니다 (config 명령으로 등록 시).
    디버깅 목적으로 직접 실행할 수 있습니다.

    예시:
        wiki-search-mcp serve ~/my-notes
        wiki-search-mcp serve ~/my-notes --log-level DEBUG
        wiki-search-mcp serve ~/notes --no-watch --model fast
    """
    # 경로 존재 검증을 click ``exists=True`` 대신 여기서 직접 한다.
    # click 의 자동 거부는 stderr 에 "Invalid value for 'WIKI_PATH'" 만 남기고
    # 비표준 종료해, Claude Desktop 로그에는 "exited early" 로만 보여 원인 파악이
    # 어렵다. iCloud/Obsidian vault 는 동기화 지연이나 경로 변경(config 잔재)으로
    # 일시적으로 사라질 수 있으므로, 명확한 한 줄 안내를 남기고 종료한다.
    resolved = Path(wiki_path).expanduser().resolve()
    if not resolved.exists():
        click.echo(
            f"[wiki-search] vault 경로를 찾을 수 없습니다: {resolved}\n"
            "  - iCloud/Obsidian 동기화 중이면 잠시 후 자동 재시도됩니다.\n"
            "  - 경로가 바뀌었다면 Claude Desktop config 의 args 를 갱신하거나\n"
            "    `wiki-search-mcp config <새 경로>` 로 다시 등록하세요.",
            err=True,
        )
        raise SystemExit(1)
    if not resolved.is_dir():
        click.echo(
            f"[wiki-search] vault 경로가 디렉토리가 아닙니다: {resolved}",
            err=True,
        )
        raise SystemExit(1)

    from wiki_search_mcp.adapters.mcp.server import (
        ServerOptions,
        main as server_main,
    )

    options = ServerOptions(
        wiki_path=resolved,
        model=model,
        ignore_patterns=tuple(ignore_patterns),
        watch=watch,
        debounce=debounce,
        log_level=log_level,
        log_file=Path(log_file).resolve() if log_file else None,
    )
    server_main(options)


# =============================================================================
# daemon (백그라운드 자동 분류)
#
# 순환 import를 피하기 위해 의도적으로 모듈 하단에서 등록한다.
# pylint: disable=wrong-import-position
# =============================================================================

from wiki_search_mcp.adapters.cli.daemon_cli import daemon as _daemon_group  # noqa: E402

main.add_command(_daemon_group)


if __name__ == "__main__":
    main()
