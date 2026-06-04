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
import threading
from dataclasses import dataclass, field
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from wiki_search_mcp.core.exceptions import DaemonError
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

logger = logging.getLogger(__name__)


# =============================================================================
# Server Options (CLI에서 주입)
# =============================================================================


@dataclass(frozen=True)
class ServerOptions:
    """MCP 서버 런타임 옵션. CLI에서 빌드되어 main()에 주입됩니다.

    Attributes:
        wiki_path: wiki 루트 (필수)
        model: 임베딩 모델 프리셋 또는 모델명 (None이면 기본값 'accurate')
        ignore_patterns: 추가 무시 패턴 (CLI --ignore 누적)
        watch: 파일 감시 활성 여부 (기본 True)
        debounce: 감시 디바운스 (초)
        log_level: 로그 레벨
        log_file: 로그 파일 경로 (None이면 stderr만)
    """

    wiki_path: Path
    model: str | None = None
    ignore_patterns: tuple[str, ...] = field(default_factory=tuple)
    watch: bool = True
    debounce: float = 2.0
    log_level: str = "WARNING"
    log_file: Path | None = None


# =============================================================================
# MCP Server Initialization
# =============================================================================

mcp = FastMCP("wiki-search", instructions=WIKI_INSTRUCTIONS)

# =============================================================================
# Global State (Lazy Initialization)
# =============================================================================

_options: ServerOptions | None = None
_container: ServiceContainer | None = None
_indexer: WikiIndexer | None = None
_watcher: WikiWatcher | None = None
# watcher 소유권 락. 같은 vault 에 여러 serve 가 떠도 watcher(자동 reindex)는
# 락을 잡은 한 인스턴스만 돌린다. 락을 못 잡은 serve 는 검색 전용으로 계속 동작.
# 프로세스 생명주기 동안 보유하고 atexit 에서 release.
_serve_lock = None  # PidLock | None
_owns_watcher = False  # 이 serve 인스턴스가 watcher 소유권을 가졌는지


def _require_options() -> ServerOptions:
    """_options이 설정되지 않았으면 RuntimeError. main()이 먼저 호출되어야 함."""
    if _options is None:
        raise RuntimeError(
            "ServerOptions not initialized. Call main(options) first."
        )
    return _options


def get_container() -> ServiceContainer:
    """ServiceContainer 싱글톤 반환."""
    global _container
    if _container is None:
        opts = _require_options()
        _container = ServiceContainer(
            str(opts.wiki_path),
            model_name=opts.model,
            ignore_patterns=opts.ignore_patterns,
        )
    return _container


def get_indexer() -> WikiIndexer:
    """WikiIndexer 싱글톤 반환."""
    global _indexer
    if _indexer is None:
        opts = _require_options()
        _indexer = WikiIndexer(
            str(opts.wiki_path),
            model_name=opts.model,
            ignore_patterns=opts.ignore_patterns,
        )
    return _indexer


# =============================================================================
# File Watcher Management
# =============================================================================

# Reindex 동시 실행 방지 Lock
_reindex_lock = threading.Lock()

# 부트스트랩 진행 상태 (검색/통계 응답에서 사용자에게 노출)
# "not_started" | "in_progress" | "completed" | "failed" | "skipped"
_bootstrap_state: str = "not_started"
_bootstrap_error: str | None = None


def _auto_reindex(full: bool = False) -> None:
    """자동 reindex 함수. Watcher와 부트스트랩에서 공통 사용.

    동시에 여러 reindex가 실행되는 것을 방지하기 위해 Lock을 사용합니다.
    이미 reindex가 진행 중이면 스킵합니다.

    Args:
        full: True면 전체 재구축 (부트스트랩용), False면 증분 (watcher용)
    """
    # 이미 reindex 중이면 스킵 (non-blocking)
    if not _reindex_lock.acquire(blocking=False):
        logger.debug("Reindex already in progress, skipping")
        return

    try:
        indexer = get_indexer()
        result = indexer.reindex(full=full)
        logger.info(
            f"Auto-reindex complete (full={full}): {result['indexed']} pages, "
            f"{result['duration_ms']}ms"
        )
        # 캐시 무효화
        container = get_container()
        container.invalidate_all()
    except Exception as e:
        logger.error(f"Auto-reindex error: {e}")
    finally:
        _reindex_lock.release()


def _bootstrap_index_if_empty() -> None:
    """서버 기동 시 인덱스가 비어있으면 백그라운드로 자동 인덱싱 실행.

    Read-only 원칙은 사용자 wiki 데이터를 변경하지 않는다는 의미이며,
    내부 인덱스 DB(LanceDB/BM25/graph)는 도구 자체의 상태이므로
    자동 빌드해도 원칙 위반이 아닙니다.

    동작:
    - 인덱스가 이미 존재 (vector store 테이블 있음) → 스킵
    - 비어있음 → 백그라운드 스레드로 full reindex 시작
    """
    global _bootstrap_state, _bootstrap_error

    try:
        container = get_container()
        if container.vector_repository.exists():
            logger.info("Index already exists; skipping bootstrap")
            _bootstrap_state = "skipped"
            return
    except Exception as e:
        logger.warning(f"Bootstrap check failed: {e}; proceeding with bootstrap")

    _bootstrap_state = "in_progress"
    logger.info("Index empty; starting background bootstrap reindex (full)")

    def _run():
        global _bootstrap_state, _bootstrap_error
        try:
            _auto_reindex(full=True)
            _bootstrap_state = "completed"
            logger.info("Bootstrap reindex completed")
        except Exception as e:
            _bootstrap_state = "failed"
            _bootstrap_error = str(e)
            logger.error(f"Bootstrap reindex failed: {e}")

    thread = threading.Thread(
        target=_run, name="wiki-bootstrap-reindex", daemon=True
    )
    thread.start()


def get_bootstrap_state() -> tuple[str, str | None]:
    """현재 부트스트랩 상태 반환. (state, error_message)"""
    return _bootstrap_state, _bootstrap_error


def start_watcher() -> bool:
    """파일 감시 시작.

    Returns:
        True: 시작 성공
        False: 비활성화 상태이거나 시작 실패
    """
    global _watcher

    opts = _require_options()
    if not opts.watch:
        logger.info("File watching disabled (--no-watch)")
        return False

    # pages 디렉토리 탐지
    pages_path = resolve_pages_path(opts.wiki_path)

    _watcher = WikiWatcher(
        pages_path=pages_path,
        reindex_callback=_auto_reindex,
        debounce_seconds=opts.debounce,
    )

    if _watcher.start():
        logger.info(f"File watching enabled (debounce: {opts.debounce}s)")
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


def _read_daemon_status() -> dict | None:
    """daemon status 파일을 읽어 dict 반환. 미존재/실패면 ``None``.

    실제 읽기는 infrastructure.daemon.read_daemon_status facade 에 위임한다
    (server/handlers 중복 제거 + 계층 직접 의존 집중).
    """
    from wiki_search_mcp.infrastructure.daemon import read_daemon_status

    data = read_daemon_status(_require_options().wiki_path)
    # facade 는 실패 시 {"state": "unknown", ...} 를 주지만, stats 응답에서는
    # 기존 계약(조회 불가 시 daemon 섹션 생략)을 유지하기 위해 None 으로 변환.
    if data.get("state") == "unknown":
        return None
    return data


def _read_daemon_pending(limit: int = 50) -> list[dict] | None:
    """daemon pending.jsonl의 active entries를 path별 최신 1개만 반환."""
    from wiki_search_mcp.infrastructure.daemon import read_daemon_pending

    items = read_daemon_pending(_require_options().wiki_path, limit=limit)
    # 기존 계약: 항목 없거나 실패면 None (응답에서 pending 섹션 생략).
    return items or None


@mcp.tool()
def wiki_stats() -> str:
    """Wiki 통계를 조회합니다.

    전체 페이지 수, 카테고리별/상태별 분포, 마지막 인덱싱 시간,
    자동 부트스트랩 진행 상태, daemon 상태를 함께 반환합니다.

    Returns:
        통계 JSON 문자열. ``bootstrap.state`` 필드는 다음 중 하나:
        ``not_started`` | ``in_progress`` | ``completed`` | ``failed`` | ``skipped``.
        ``daemon`` 필드는 daemon 미실행 시 ``{"state": "not_running"}`` 형태.
    """
    return handle_wiki_stats(
        container=get_container(),
        bootstrap_state=get_bootstrap_state(),
        daemon_status=_read_daemon_status(),
    )


@mcp.tool()
def wiki_daemon_status() -> str:
    """자동 분류 daemon의 현재 상태를 조회합니다.

    Returns:
        JSON: ``{state, alive, pid, started_at, applied_count, pending_count, ...}``.
        daemon이 실행 중이 아니면 ``{state: not_running}``.
    """
    from wiki_search_mcp.adapters.mcp.handlers import handle_wiki_daemon_status

    opts = _require_options()
    return handle_wiki_daemon_status(opts.wiki_path)


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
    opts = _require_options()
    pages_path = resolve_pages_path(opts.wiki_path)

    return handle_wiki_watch_status(
        watcher=_watcher,
        enabled=opts.watch,
        debounce_seconds=opts.debounce,
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
    합쳐 반환합니다. daemon이 실행 중이면 daemon의 ``pending.jsonl``에
    쌓인 항목을 함께 머지하여 우선 노출합니다.

    Args:
        limit: 최대 반환 개수 (1-200, 기본값: 20)

    Returns:
        ``{items: [...], count}`` JSON. 각 item은 ``source`` (``"daemon"`` 또는
        ``"index"``)와 함께 daemon 항목인 경우 ``reason``, ``decision`` 포함.
    """
    return handle_wiki_pending(
        container=get_container(),
        limit=limit,
        daemon_pending=_read_daemon_pending(limit=limit),
    )


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


def _acquire_watcher_lock(wiki_path: Path) -> bool:
    """watcher 소유권 락 획득 (best-effort).

    같은 vault에 여러 serve(예: Claude Code + Claude Desktop)가 동시에 떠도
    watcher(자동 reindex)는 한 인스턴스만 돌리도록 한다. 락을 못 잡은 serve는
    watcher 없이 검색 전용으로 계속 동작하며 종료하지 않는다.

    reindex 자체의 동시성 안전은 indexer 의 cross-process reindex flock 이
    보장하므로, 이 락은 정확성이 아니라 "중복 watcher → 중복 reindex" 비효율을
    줄이기 위한 최적화다.

    Args:
        wiki_path: wiki 루트

    Returns:
        락 획득 성공 시 True (watcher 소유). 이미 다른 serve가 소유 중이면 False.
    """
    global _serve_lock
    from wiki_search_mcp.infrastructure.daemon.paths import (
        serve_lock_file,
        serve_pid_file,
    )
    from wiki_search_mcp.infrastructure.daemon.pidfile import PidLock

    lock = PidLock(serve_lock_file(wiki_path), serve_pid_file(wiki_path))
    try:
        lock.acquire()
    except DaemonError as e:
        existing = e.context.details.get("pid") if e.context else None
        logger.info(
            "another wiki-search serve owns the watcher for this vault "
            "(pid=%s); running in search-only mode (no watcher)",
            existing,
        )
        return False
    _serve_lock = lock
    atexit.register(lock.release)
    return True


def main(options: ServerOptions) -> None:
    """MCP 서버 실행.

    Args:
        options: CLI에서 빌드한 런타임 옵션 (wiki_path 필수)
    """
    global _options, _owns_watcher

    # 옵션 보관 (다른 함수들이 _require_options()로 참조)
    _options = options

    # 로깅 초기화 (CLI 옵션 기반)
    setup_logging(level=options.log_level, log_file=options.log_file)

    # 구조화 성능 메트릭 싱크 (metrics.jsonl) 설정.
    from wiki_search_mcp.core.metrics import configure_metrics
    from wiki_search_mcp.infrastructure.daemon.paths import metrics_jsonl

    configure_metrics(metrics_jsonl(options.wiki_path))

    # watcher 소유권 락 (best-effort). 같은 vault 에 다른 serve 가 이미 watcher 를
    # 돌리고 있으면 이 인스턴스는 검색 전용으로 동작한다. 종료하지 않으므로
    # 여러 MCP 클라이언트가 같은 vault 를 동시에 쓸 수 있다.
    _owns_watcher = _acquire_watcher_lock(options.wiki_path)

    if _owns_watcher:
        # 파일 감시 + 부트스트랩을 백그라운드 스레드에서 시작한다.
        #
        # 과거에는 main 스레드에서 start_watcher() → _bootstrap 을 동기로 호출한 뒤
        # mcp.run() 으로 진입했다. 그 결과 무거운 작업(임베딩 모델 로드, 첫 reindex)
        # 이 MCP 핸드셰이크(initialize 응답)와 같은 프로세스에서 CPU/GIL 을 다투어
        # 핸드셰이크가 수 분~십수 분 지연되고 클라이언트가 30초 타임아웃으로
        # "연결 실패" 를 띄웠다 (운영 로그의 17분 initialize 지연).
        #
        # watcher 등록/부트스트랩은 핸드셰이크 정확성과 무관하므로, 짧게 뒤로
        # 미뤄 mcp.run() 이 먼저 stdio 핸드셰이크를 받게 한다. reindex 동시성
        # 안전은 indexer 의 cross-process flock 이 보장한다.
        atexit.register(stop_watcher)

        def _deferred_startup() -> None:
            try:
                start_watcher()
                _bootstrap_index_if_empty()
            except Exception:
                logger.exception("deferred startup (watcher/bootstrap) failed")

        threading.Thread(
            target=_deferred_startup, name="wiki-deferred-startup", daemon=True
        ).start()

    # MCP 서버 실행 (stdio 핸드셰이크를 즉시 처리)
    mcp.run()


# 직접 실행 (`python -m wiki_search_mcp.adapters.mcp.server`)은 인자 파싱이 필요해
# 지원하지 않습니다. 항상 CLI 진입점(`wiki-search-mcp serve <path>`)을 사용하세요.
