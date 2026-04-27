#!/usr/bin/env python3
from __future__ import annotations

"""Wiki Search MCP CLI

명령줄 도구로 wiki-search-mcp를 관리합니다.

Commands:
- config: Claude Desktop 설정
- index: 수동 인덱싱
- serve: MCP 서버 실행 (직접 호출용)

`init` 명령은 zero-config 전환에 따라 제거되었습니다. 빈 디렉토리든
기존 노트 디렉토리든 ``config``로 등록만 하면 됩니다.
"""

import json
import os
from pathlib import Path

import click

from wiki_search_mcp import __version__


@click.group()
@click.version_option(version=__version__)
def main():
    """Wiki Search MCP - 시맨틱 Wiki 검색 도구"""
    pass  # Click group entry point - subcommands handle actual work


@main.command()
@click.argument("wiki_path", type=click.Path(exists=True))
@click.option(
    "--config-path",
    type=click.Path(),
    help="Claude Desktop 설정 파일 경로 (기본: 자동 탐지)",
)
def config(wiki_path: str, config_path: str | None):
    """Claude Desktop에 MCP 서버를 등록합니다.

    WIKI_PATH는 wiki 디렉토리 경로입니다. 빈 디렉토리도 허용되며,
    필요한 경우 자동으로 인덱스(.vectordb)가 생성됩니다.

    예시:
        wiki-search-mcp config ./my-notes
        wiki-search-mcp config ~/obsidian-vault
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

    # wiki-search 서버 설정
    existing_config["mcpServers"]["wiki-search"] = {
        "command": "wiki-search-mcp",
        "args": ["serve"],
        "env": {"WIKI_PATH": str(wiki_path)},
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
    click.echo(f"  WIKI_PATH: {wiki_path}")
    click.echo("")
    click.echo("Claude Desktop을 재시작하면 적용됩니다.")


@main.command()
@click.argument("wiki_path", type=click.Path(exists=True))
@click.option("--full", "-f", is_flag=True, help="전체 재구축")
def index(wiki_path: str, full: bool):
    """Wiki 인덱스를 수동으로 구축합니다.

    WIKI_PATH는 wiki 디렉토리 경로입니다.
    pages/ 하위 디렉토리가 있으면 사용, 없으면 루트를 문서 경로로 사용합니다.

    예시:
        wiki-search-mcp index ./my-notes
        wiki-search-mcp index ./my-notes --full
        wiki-search-mcp index ~/obsidian-vault  # pages/ 없는 구조도 지원
    """
    wiki_path = Path(wiki_path).resolve()

    # pages 디렉토리 확인 (경고만, 오류 아님)
    pages_path = wiki_path / "pages"
    if not pages_path.exists():
        # 루트에 .md 파일이 있는지 확인
        md_files = list(wiki_path.rglob("*.md"))
        if not md_files:
            click.echo(f"경고: {wiki_path}에 .md 파일이 없습니다.", err=True)
        else:
            click.echo(f"pages/ 없음. {wiki_path}를 문서 루트로 사용합니다.")

    click.echo(f"인덱싱 시작: {wiki_path}")
    if full:
        click.echo("모드: 전체 재구축")
    else:
        click.echo("모드: 증분 업데이트")

    # 환경변수 설정 후 인덱서 실행
    os.environ["WIKI_PATH"] = str(wiki_path)

    from wiki_search_mcp.infrastructure.indexing import WikiIndexer

    indexer = WikiIndexer(str(wiki_path))
    result = indexer.reindex(full=full)

    click.echo("")
    click.echo("결과:")
    click.echo(f"  인덱싱된 문서: {result['indexed']}")
    click.echo(f"  갱신된 문서: {result['updated']}")
    click.echo(f"  소요 시간: {result['duration_ms']}ms")


@main.command()
def serve():
    """MCP 서버를 실행합니다.

    일반적으로 Claude Desktop이 자동으로 호출합니다.
    디버깅 목적으로 직접 실행할 수 있습니다.
    """
    from wiki_search_mcp.adapters.mcp.server import main as server_main

    server_main()


if __name__ == "__main__":
    main()
