#!/usr/bin/env python3
"""Wiki Search MCP Server.

Model Context Protocol 서버로 Claude Code에서 Wiki 검색 기능을 제공합니다.

Tools:
- wiki_search: 시맨틱 검색 + 그래프 확장
- wiki_reindex: 인덱스 재구축
- wiki_stats: 통계 조회
- wiki_watch_status: 파일 감시 상태 조회
- wiki_get_document: 특정 문서 조회
- wiki_list_documents: 문서 목록 조회
- wiki_get_backlinks: 역링크 조회
- wiki_find_orphans: 고아 문서 찾기
- wiki_get_similar: 유사 문서 검색
- wiki_validate: Wiki 품질 검증
- wiki_suggest_tags: 자동 태그 추출
- wiki_get_categories: 폴더 자동 감지된 카테고리 조회
- wiki_suggest_categories: 인덱스 분석 기반 카테고리 후보 제안
- wiki_pending: 미분류 / 정리 대기 파일 목록
- wiki_suggest_classification: 단일 파일에 대한 카테고리/태그 추천
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from wiki_search_mcp.core.logging import setup_logging
from wiki_search_mcp.core.utils import resolve_pages_path
from wiki_search_mcp.infrastructure.indexing import WikiIndexer
from wiki_search_mcp.infrastructure.watcher import WikiWatcher

from .container import ServiceContainer
from .handlers import (
    handle_wiki_find_orphans,
    handle_wiki_get_backlinks,
    handle_wiki_get_categories,
    handle_wiki_get_document,
    handle_wiki_get_similar,
    handle_wiki_list_documents,
    handle_wiki_pending,
    handle_wiki_reindex,
    handle_wiki_search,
    handle_wiki_stats,
    handle_wiki_suggest_categories,
    handle_wiki_suggest_classification,
    handle_wiki_suggest_tags,
    handle_wiki_validate,
    handle_wiki_watch_status,
)
from .instructions import WIKI_INSTRUCTIONS

# =============================================================================
# Logging Configuration
# =============================================================================

# 환경변수 기반 로깅 설정 초기화
setup_logging()
logger = logging.getLogger(__name__)

# =============================================================================
# Environment Configuration
# =============================================================================

WIKI_PATH = os.environ.get("WIKI_PATH", "./wiki")
WIKI_WATCH = os.environ.get("WIKI_WATCH", "true").lower() in ("true", "1", "yes")
WIKI_DEBOUNCE = float(os.environ.get("WIKI_DEBOUNCE", "2.0"))

# =============================================================================
# MCP Server Initialization
# =============================================================================

mcp = FastMCP("wiki-search", instructions=WIKI_INSTRUCTIONS)

# =============================================================================
# Global State (Lazy Initialization)
# =============================================================================

_container: ServiceContainer | None = None
_indexer: WikiIndexer | None = None
_watcher: WikiWatcher | None = None


def get_container() -> ServiceContainer:
    """ServiceContainer 싱글톤 반환."""
    global _container
    if _container is None:
        _container = ServiceContainer(WIKI_PATH)
    return _container


def get_indexer() -> WikiIndexer:
    """WikiIndexer 싱글톤 반환."""
    global _indexer
    if _indexer is None:
        _indexer = WikiIndexer(WIKI_PATH)
    return _indexer


# =============================================================================
# File Watcher Management
# =============================================================================

# Reindex 동시 실행 방지 Lock
_reindex_lock = threading.Lock()


def _auto_reindex() -> None:
    """Watcher에서 호출하는 자동 reindex 함수.

    동시에 여러 reindex가 실행되는 것을 방지하기 위해 Lock을 사용합니다.
    이미 reindex가 진행 중이면 스킵합니다.
    """
    # 이미 reindex 중이면 스킵 (non-blocking)
    if not _reindex_lock.acquire(blocking=False):
        logger.debug("Reindex already in progress, skipping")
        return

    try:
        indexer = get_indexer()
        result = indexer.reindex(full=False)
        logger.info(
            f"Auto-reindex complete: {result['indexed']} pages, "
            f"{result['duration_ms']}ms"
        )
        # 캐시 무효화
        container = get_container()
        container.invalidate_all()
    except Exception as e:
        logger.error(f"Auto-reindex error: {e}")
    finally:
        _reindex_lock.release()


def start_watcher() -> bool:
    """파일 감시 시작.

    Returns:
        True: 시작 성공
        False: 비활성화 상태이거나 시작 실패
    """
    global _watcher

    if not WIKI_WATCH:
        logger.info("File watching disabled (WIKI_WATCH=false)")
        return False

    # pages 디렉토리 탐지
    wiki_path = Path(WIKI_PATH)
    pages_path = resolve_pages_path(wiki_path)

    _watcher = WikiWatcher(
        pages_path=pages_path,
        reindex_callback=_auto_reindex,
        debounce_seconds=WIKI_DEBOUNCE,
    )

    if _watcher.start():
        logger.info(f"File watching enabled (debounce: {WIKI_DEBOUNCE}s)")
        return True
    else:
        logger.warning("Failed to start file watcher")
        _watcher = None
        return False


def stop_watcher() -> None:
    """파일 감시 중지."""
    global _watcher

    if _watcher is not None:
        _watcher.stop()
        _watcher = None


# =============================================================================
# MCP Tool Definitions
# =============================================================================


@mcp.tool()
def wiki_search(
    query: str,
    top_k: int = 5,
    expand_graph: bool = True,
    category: str | None = None,
    tags: list[str] | None = None,
    states: list[str] | None = None,
    confidence_min: int = 0,
    mode: str = "hybrid",
    sort_by: str = "similarity",
    sort_order: str = "desc",
    expand: bool = False,
) -> str:
    """Wiki 페이지를 검색합니다.

    하이브리드(벡터+키워드), 벡터, 키워드 검색 모드를 지원하며,
    wikilink로 연결된 관련 문서도 함께 반환합니다.

    Args:
        query: 검색 질의 (예: "SSL 인증서 적용 방법")
        top_k: 반환할 결과 수 (기본값: 5, 범위: 1-100)
        expand_graph: 그래프 확장 여부 (기본값: True)
        category: 카테고리 필터 (예: "infra", "devops")
        tags: 태그 필터 (하나라도 포함되면 통과, 예: ["nginx", "ssl"])
        states: 상태 필터 (기본값: archived 제외 전체)
        confidence_min: 최소 신뢰도 점수 (0-100, 기본값: 0)
        mode: 검색 모드 - "hybrid"(벡터+키워드), "vector"(벡터만), "keyword"(키워드만)
        sort_by: 정렬 기준 - "similarity", "confidence", "updated", "title"
        sort_order: 정렬 순서 - "asc"(오름차순), "desc"(내림차순)
        expand: 동의어로 쿼리 확장 여부 (기본값: False)

    Returns:
        검색 결과 JSON 문자열
    """
    return handle_wiki_search(
        container=get_container(),
        query=query,
        top_k=top_k,
        expand_graph=expand_graph,
        category=category,
        tags=tags,
        states=states,
        confidence_min=confidence_min,
        mode=mode,
        sort_by=sort_by,
        sort_order=sort_order,
        expand=expand,
    )


@mcp.tool()
def wiki_reindex(full: bool = False) -> str:
    """Wiki 인덱스를 재구축합니다.

    문서가 추가/수정/삭제된 후 호출하여 검색 인덱스를 갱신합니다.

    Args:
        full: True면 전체 재구축, False면 변경분만 (기본값: False)

    Returns:
        인덱싱 결과 JSON 문자열
    """
    return handle_wiki_reindex(
        container=get_container(),
        indexer=get_indexer(),
        full=full,
    )


@mcp.tool()
def wiki_stats() -> str:
    """Wiki 통계를 조회합니다.

    전체 페이지 수, 카테고리별/상태별 분포, 마지막 인덱싱 시간을 반환합니다.

    Returns:
        통계 JSON 문자열
    """
    return handle_wiki_stats(container=get_container())


@mcp.tool()
def wiki_get_document(
    path: str,
    include_content: bool = False,
    preview_size: int = 500,
) -> str:
    """특정 문서를 조회합니다.

    기본적으로 메타데이터 + 500자 미리보기만 반환합니다.
    전체 본문이 필요하면 include_content=True로 호출하세요.

    Args:
        path: 문서 상대 경로 (예: "infra/nginx-setup.md")
        include_content: True면 전체 본문 포함 (기본값: False)
        preview_size: 미리보기 크기 (기본값: 500자, 0이면 미리보기 없음)

    Returns:
        문서 메타데이터 JSON 문자열
    """
    return handle_wiki_get_document(
        container=get_container(),
        path=path,
        include_content=include_content,
        preview_size=preview_size,
    )


@mcp.tool()
def wiki_list_documents(
    category: str | None = None,
    tag: str | None = None,
    state: str | None = None,
    limit: int = 50,
) -> str:
    """조건에 맞는 문서 목록을 조회합니다.

    검색 없이 카테고리/태그/상태별로 문서를 필터링합니다.

    Args:
        category: 카테고리 필터 (예: "infra", "devops")
        tag: 태그 필터 (예: "nginx", "docker")
        state: 상태 필터 (예: "stable", "draft")
        limit: 최대 결과 수 (기본값: 50, 최대: 500)

    Returns:
        문서 목록 JSON 문자열
    """
    return handle_wiki_list_documents(
        container=get_container(),
        category=category,
        tag=tag,
        state=state,
        limit=limit,
    )


@mcp.tool()
def wiki_get_backlinks(path: str) -> str:
    """특정 문서를 참조하는 역링크를 조회합니다.

    어떤 문서들이 이 문서를 [[wikilink]]로 참조하는지 확인합니다.

    Args:
        path: 대상 문서 경로 (예: "infra/nginx.md")

    Returns:
        역링크 목록 JSON 문자열
    """
    return handle_wiki_get_backlinks(
        container=get_container(),
        path=path,
    )


@mcp.tool()
def wiki_watch_status() -> str:
    """파일 감시 상태를 조회합니다.

    wiki 디렉토리의 .md 파일 변경 감시 상태를 반환합니다.

    Returns:
        상태 JSON 문자열
    """
    wiki_path = Path(WIKI_PATH)
    pages_path = resolve_pages_path(wiki_path)

    return handle_wiki_watch_status(
        watcher=_watcher,
        enabled=WIKI_WATCH,
        debounce_seconds=WIKI_DEBOUNCE,
        watching_path=str(pages_path),
    )


@mcp.tool()
def wiki_find_orphans() -> str:
    """연결되지 않은 고아 문서를 찾습니다.

    다른 문서에서 wikilink로 참조하지 않는 문서 목록을 반환합니다.
    고아 문서는 연결이 필요하거나 정리 대상일 수 있습니다.

    Returns:
        고아 문서 목록 JSON 문자열
    """
    return handle_wiki_find_orphans(container=get_container())


@mcp.tool()
def wiki_get_similar(path: str, top_k: int = 5) -> str:
    """특정 문서와 유사한 문서를 찾습니다.

    벡터 유사도를 기반으로 내용이 비슷한 문서를 추천합니다.

    Args:
        path: 대상 문서 경로 (예: "infra/nginx-setup.md")
        top_k: 반환할 유사 문서 수 (기본값: 5, 최대: 20)

    Returns:
        유사 문서 목록 JSON 문자열
    """
    return handle_wiki_get_similar(
        container=get_container(),
        path=path,
        top_k=top_k,
    )


@mcp.tool()
def wiki_validate() -> str:
    """Wiki 인덱스 품질을 검사합니다.

    frontmatter 필수 필드 누락, 깨진 wikilink 등을 감지합니다.

    Returns:
        검증 결과 JSON 문자열
    """
    return handle_wiki_validate(container=get_container())


@mcp.tool()
def wiki_suggest_tags(path: str, top_n: int = 5) -> str:
    """문서에서 태그를 자동 추출합니다.

    문서 내용을 분석하여 적합한 태그를 제안합니다.

    Args:
        path: 대상 문서 경로 (예: "infra/nginx-setup.md")
        top_n: 추출할 태그 수 (기본값: 5, 최대: 10)

    Returns:
        제안 태그 JSON 문자열
    """
    return handle_wiki_suggest_tags(
        container=get_container(),
        path=path,
        top_n=top_n,
    )


@mcp.tool()
def wiki_get_categories() -> str:
    """현재 wiki에서 사용 가능한 카테고리를 조회합니다.

    사용자 폴더 구조를 자동 감지하여 반환합니다.
    설정 파일은 사용하지 않습니다.

    - mode='folder': 디렉토리 자동 감지 (categories에 폴더명 목록)
    - mode='empty': 카테고리 없음. wiki_suggest_categories() 호출하여
      AI 기반 제안을 받을 수 있습니다.

    Returns:
        {mode, categories, detected_at} JSON 문자열
    """
    return handle_wiki_get_categories(container=get_container())


@mcp.tool()
def wiki_suggest_categories(top_k: int = 10) -> str:
    """카테고리가 비어있을 때 인덱스 분석으로 카테고리 후보를 제안합니다.

    기존 인덱싱된 문서들의 카테고리 빈도와 본문 키워드 빈도를
    합쳐 후보를 반환합니다. wiki_get_categories()의 결과 mode가
    'empty'일 때 호출하세요.

    Args:
        top_k: 반환할 후보 수 (1-20, 기본값: 10)

    Returns:
        {suggestions: [{name, doc_count, keywords}, ...]} JSON 문자열
    """
    return handle_wiki_suggest_categories(
        container=get_container(), top_k=top_k
    )


@mcp.tool()
def wiki_pending(limit: int = 20) -> str:
    """미분류 / 정리 대기 파일 목록을 조회합니다.

    인덱스에서 frontmatter가 빈약하거나 category가 누락된 문서,
    그리고 디스크에는 있지만 아직 인덱싱되지 않은 신규 .md 파일을
    합쳐 반환합니다.

    Args:
        limit: 최대 반환 개수 (1-200, 기본값: 20)

    Returns:
        {items: [{path, reason, mtime}, ...], count} JSON 문자열
        reason은 'not_indexed', 'no_frontmatter', 'no_category' 중 하나
    """
    return handle_wiki_pending(container=get_container(), limit=limit)


@mcp.tool()
def wiki_suggest_classification(path: str) -> str:
    """단일 파일에 대한 카테고리/태그 추천을 받습니다.

    폴더 기반 카테고리 + 유사 문서 카테고리 투표 + 본문 키워드 분석을
    종합하여 후보를 제시합니다. 결과를 사용자에게 보고하고 승인받은 뒤
    Claude의 Read/Write 도구로 직접 frontmatter를 수정하세요.

    Args:
        path: 대상 문서 경로 (예: "Notes/memo.md")

    Returns:
        {path, category_candidates, tag_candidates, similar_paths, reasoning}
        JSON 문자열
    """
    return handle_wiki_suggest_classification(
        container=get_container(), path=path
    )


# =============================================================================
# Main Entry Point
# =============================================================================


def main():
    """MCP 서버 실행."""
    # 파일 감시 시작
    start_watcher()

    # 종료 시 정리
    atexit.register(stop_watcher)

    # MCP 서버 실행
    mcp.run()


if __name__ == "__main__":
    main()
