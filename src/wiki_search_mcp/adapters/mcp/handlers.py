"""MCP Tool Handlers.

MCP 도구 핸들러 함수들입니다.
ServiceContainer를 통해 서비스를 호출하고 JSON 직렬화를 담당합니다.
"""

from __future__ import annotations

import functools
import json
import logging
import uuid
from typing import TYPE_CHECKING, Callable

from wiki_search_mcp.core.exceptions import (
    BusinessException,
    InvalidPathError,
    TechnicalException,
)
from wiki_search_mcp.core.models import SearchFilters
from wiki_search_mcp.core.validators import (
    validate_confidence_min,
    validate_limit,
    validate_path_required,
    validate_preview_size,
    validate_query,
    validate_search_mode,
    validate_sort_by,
    validate_sort_order,
    validate_top_k,
)

if TYPE_CHECKING:
    from .container import ServiceContainer

logger = logging.getLogger(__name__)


# =============================================================================
# JSON Serialization Helpers
# =============================================================================


def _json_response(data: dict) -> str:
    """dict를 JSON 문자열로 변환."""
    return json.dumps(data, ensure_ascii=False, indent=2)


def _doc_summary(doc, *, with_state_tags: bool = False) -> dict:
    """Document 를 응답용 요약 dict 로 변환.

    get_similar/get_backlinks/find_orphans 는 {path, title, category} 만,
    list_documents 는 state/tags 까지 포함한다. 네 핸들러에 흩어졌던 동일
    구성 코드를 한 곳으로 모은다.

    Args:
        doc: Document 객체(path/title/category[/state/tags] 속성 보유).
        with_state_tags: True 면 state, tags 도 포함.

    Returns:
        요약 dict.
    """
    summary = {
        "path": doc.path,
        "title": doc.title,
        "category": doc.category,
    }
    if with_state_tags:
        summary["state"] = doc.state
        summary["tags"] = list(doc.tags)
    return summary


def _json_error(message: str, include_id: bool = True) -> str:
    """에러 메시지를 JSON 문자열로 변환.

    Args:
        message: 에러 메시지
        include_id: 에러 ID 포함 여부 (기본 True)

    Returns:
        JSON 문자열 (error, error_id 포함)
    """
    if include_id:
        error_id = uuid.uuid4().hex[:8]
        logger.error(f"[{error_id}] {message}")
        return json.dumps({"error": message, "error_id": error_id}, ensure_ascii=False)
    return json.dumps({"error": message}, ensure_ascii=False)


def mcp_handler(op: str) -> Callable:
    """MCP 핸들러 공통 예외 처리 데코레이터.

    15개 핸들러가 동일한 5단계 예외 분기(InvalidPathError → BusinessException
    → TechnicalException → ValueError/TypeError → OSError → Exception)를
    복붙하던 것을 한 곳으로 모은다. 각 핸들러는 본문 로직만 작성하고,
    예외 변환/로깅/JSON 에러 응답은 데코레이터가 담당한다.

    동작 보존:
    - InvalidPathError 는 TechnicalException 하위지만, 보안 경로 오류를
      구분 로깅하기 위해 먼저 잡는다(응답은 동일하게 str(e)).
    - 모든 예외는 기존과 동일한 _json_error 문자열을 반환한다.

    Args:
        op: 로그에 표기할 작업 이름(예: "wiki_search").

    Returns:
        핸들러 함수를 감싸는 데코레이터.
    """

    def decorator(fn: Callable[..., str]) -> Callable[..., str]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> str:
            try:
                return fn(*args, **kwargs)
            except InvalidPathError as e:
                logger.warning(f"{op} security error: {e}")
                return _json_error(str(e))
            except BusinessException as e:
                logger.warning(f"{op} business error: {e}")
                return _json_error(str(e))
            except TechnicalException as e:
                logger.error(f"{op} technical error: {e}")
                return _json_error(str(e))
            except (ValueError, TypeError) as e:
                logger.warning(f"{op} input validation error: {e}")
                return _json_error(str(e))
            except OSError as e:
                logger.error(f"{op} I/O error: {e}")
                return _json_error("File system error")
            except Exception as e:  # noqa: BLE001 - 최종 방어선
                logger.exception(f"{op} unexpected error: {e}")
                return _json_error("Internal error")

        return wrapper

    return decorator


# =============================================================================
# Search Handlers
# =============================================================================


@mcp_handler("wiki_search")
def handle_wiki_search(
    container: "ServiceContainer",
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
) -> str:  # noqa: E501
    """Wiki 페이지 검색 핸들러.

    Args:
        container: 서비스 컨테이너
        query: 검색 질의
        top_k: 반환할 결과 수 (1-100)
        expand_graph: 그래프 확장 여부
        category: 카테고리 필터
        tags: 태그 필터 (OR 조건)
        states: 상태 필터
        confidence_min: 최소 신뢰도 점수 (0-100)
        mode: 검색 모드 ("hybrid", "vector", "keyword")
        sort_by: 정렬 기준
        sort_order: 정렬 순서 ("asc", "desc")
        expand: 동의어로 쿼리 확장 여부

    Returns:
        검색 결과 JSON 문자열
    """
    # 입력 검증 + 정규화 (실패 시 데코레이터가 ValueError 를 잡아 응답)
    validated_query = validate_query(query)
    top_k = validate_top_k(top_k)
    confidence_min = validate_confidence_min(confidence_min)
    mode = validate_search_mode(mode)
    sort_by = validate_sort_by(sort_by)
    sort_order = validate_sort_order(sort_order)

    # 필터 생성
    filters = SearchFilters.of(
        include_states=states,
        category=category,
        tags=tags,
        confidence_min=confidence_min,
    )

    # 서비스 호출
    response = container.search_service.search(
        query=validated_query,
        top_k=top_k,
        mode=mode,
        filters=filters,
        expand_graph=expand_graph,
        expand_query=expand,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    return _json_response(response.to_dict())


# =============================================================================
# Document Handlers
# =============================================================================


@mcp_handler("wiki_get_document")
def handle_wiki_get_document(
    container: "ServiceContainer",
    path: str,
    include_content: bool = False,
    preview_size: int = 500,
) -> str:
    """특정 문서 조회 핸들러.

    Args:
        container: 서비스 컨테이너
        path: 문서 상대 경로
        include_content: 전체 본문 포함 여부
        preview_size: 미리보기 크기

    Returns:
        문서 메타데이터 JSON 문자열
    """
    validated_path = validate_path_required(path)
    preview_size = validate_preview_size(preview_size)

    # 서비스 호출
    doc = container.document_service.get_document(
        path=validated_path,
        include_content=include_content,
        preview_size=preview_size,
    )

    if doc is None:
        return _json_error(f"Document not found: {path}")

    # 결과 구성
    result = doc.to_dict()

    # 본문 정보 추가
    content_info = container.document_service.read_content(
        path=validated_path,
        include_full=include_content,
        preview_size=preview_size,
    )
    result.update(content_info)

    return _json_response(result)


@mcp_handler("wiki_list_documents")
def handle_wiki_list_documents(
    container: "ServiceContainer",
    category: str | None = None,
    tag: str | None = None,
    state: str | None = None,
    limit: int = 50,
) -> str:
    """조건에 맞는 문서 목록 조회 핸들러.

    Args:
        container: 서비스 컨테이너
        category: 카테고리 필터
        tag: 태그 필터
        state: 상태 필터
        limit: 최대 결과 수 (1-500)

    Returns:
        문서 목록 JSON 문자열
    """
    limit = validate_limit(limit)

    documents = container.document_service.list_documents(
        category=category,
        tag=tag,
        state=state,
        limit=limit,
    )

    doc_list = [_doc_summary(doc, with_state_tags=True) for doc in documents]

    return _json_response({
        "documents": doc_list,
        "count": len(doc_list),
        "filters": {
            "category": category,
            "tag": tag,
            "state": state,
        },
    })


@mcp_handler("wiki_get_similar")
def handle_wiki_get_similar(
    container: "ServiceContainer",
    path: str,
    top_k: int = 5,
) -> str:
    """특정 문서와 유사한 문서 검색 핸들러.

    Args:
        container: 서비스 컨테이너
        path: 대상 문서 경로
        top_k: 반환할 유사 문서 수 (1-20)

    Returns:
        유사 문서 목록 JSON 문자열
    """
    validated_path = validate_path_required(path)
    top_k = validate_top_k(top_k, max_val=20)

    similar_docs = container.document_service.get_similar(
        path=validated_path,
        top_k=top_k,
    )

    similar_list = [_doc_summary(doc) for doc in similar_docs]

    return _json_response({
        "source": validated_path,
        "similar": similar_list,
        "count": len(similar_list),
    })


# =============================================================================
# Graph Handlers
# =============================================================================


@mcp_handler("wiki_get_backlinks")
def handle_wiki_get_backlinks(
    container: "ServiceContainer",
    path: str,
) -> str:
    """역링크 조회 핸들러.

    Args:
        container: 서비스 컨테이너
        path: 대상 문서 경로

    Returns:
        역링크 목록 JSON 문자열
    """
    validated_path = validate_path_required(path)

    backlinks = container.graph_service.get_backlinks(validated_path)

    backlink_list = [_doc_summary(doc) for doc in backlinks]

    return _json_response({
        "target": validated_path,
        "backlinks": backlink_list,
        "count": len(backlink_list),
    })


@mcp_handler("wiki_find_orphans")
def handle_wiki_find_orphans(container: "ServiceContainer") -> str:
    """고아 문서 검색 핸들러.

    Args:
        container: 서비스 컨테이너

    Returns:
        고아 문서 목록 JSON 문자열
    """
    orphans = container.graph_service.find_orphans()

    orphan_list = [_doc_summary(doc) for doc in orphans]

    return _json_response({
        "orphans": orphan_list,
        "count": len(orphan_list),
    })


# =============================================================================
# Validation Handlers
# =============================================================================


@mcp_handler("wiki_validate")
def handle_wiki_validate(container: "ServiceContainer") -> str:
    """Wiki 검증 핸들러.

    Args:
        container: 서비스 컨테이너

    Returns:
        검증 결과 JSON 문자열
    """
    report = container.validation_service.validate()
    return _json_response(report.to_dict())


# =============================================================================
# Stats Handlers
# =============================================================================


@mcp_handler("wiki_stats")
def handle_wiki_stats(
    container: "ServiceContainer",
    bootstrap_state: tuple[str, str | None] | None = None,
    daemon_status: dict | None = None,
) -> str:
    """Wiki 통계 조회 핸들러.

    Args:
        container: 서비스 컨테이너
        bootstrap_state: (state, error_message) — 자동 부트스트랩 진행 상태.
            None이면 응답에 포함되지 않음.
        daemon_status: daemon 상태 dict. None이면 응답에 포함 안 됨.

    Returns:
        통계 JSON 문자열
    """
    stats = container.stats_service.get_stats()
    result = stats.to_dict()
    if bootstrap_state is not None:
        state, err = bootstrap_state
        result["bootstrap"] = {"state": state}
        if err is not None:
            result["bootstrap"]["error"] = err
    if daemon_status is not None:
        result["daemon"] = daemon_status
    return _json_response(result)


# =============================================================================
# Index Handlers
# =============================================================================


@mcp_handler("wiki_reindex")
def handle_wiki_reindex(
    container: "ServiceContainer",
    indexer,  # WikiIndexer
    full: bool = False,
) -> str:
    """인덱스 재구축 핸들러.

    Args:
        container: 서비스 컨테이너
        indexer: WikiIndexer 인스턴스
        full: 전체 재구축 여부

    Returns:
        인덱싱 결과 JSON 문자열
    """
    result = indexer.reindex(full=full)
    container.invalidate_all()
    return _json_response(result)


# =============================================================================
# Watcher Handlers
# =============================================================================


@mcp_handler("wiki_watch_status")
def handle_wiki_watch_status(
    watcher,  # WikiWatcher | None
    enabled: bool,
    debounce_seconds: float,
    watching_path: str,
) -> str:
    """파일 감시 상태 조회 핸들러.

    Args:
        watcher: WikiWatcher 인스턴스 (None이면 비활성)
        enabled: 감시 활성화 설정 여부
        debounce_seconds: 디바운스 시간
        watching_path: 감시 대상 경로

    Returns:
        상태 JSON 문자열
    """
    if watcher is None:
        status = {
            "enabled": enabled,
            "running": False,
            "watching_path": watching_path,
            "debounce_seconds": debounce_seconds,
        }
    else:
        status = watcher.get_status()

    return _json_response(status)


# =============================================================================
# Tag Handlers
# =============================================================================


@mcp_handler("wiki_suggest_tags")
def handle_wiki_suggest_tags(
    container: "ServiceContainer",
    path: str,
    top_n: int = 5,
) -> str:
    """태그 제안 핸들러.

    Args:
        container: 서비스 컨테이너
        path: 대상 문서 경로
        top_n: 추출할 태그 수 (1-10)

    Returns:
        제안 태그 JSON 문자열
    """
    # 입력 검증 후 service 에 위임(태그 추출 유스케이스는 service 책임).
    validate_path_required(path)
    top_n = validate_top_k(top_n, max_val=10)

    result = container.document_service.suggest_tags(path, top_n=top_n)
    return _json_response(result)


# =============================================================================
# Auto Classification Handlers
# =============================================================================


@mcp_handler("wiki_get_categories")
def handle_wiki_get_categories(container: "ServiceContainer") -> str:
    """현재 wiki에서 사용 가능한 카테고리 조회 핸들러.

    Args:
        container: 서비스 컨테이너

    Returns:
        카테고리 목록 JSON 문자열 (mode, categories, detected_at)
    """
    listing = container.category_service.list_categories()
    return _json_response(listing.to_dict())


@mcp_handler("wiki_suggest_categories")
def handle_wiki_suggest_categories(
    container: "ServiceContainer", top_k: int = 10
) -> str:
    """카테고리가 비어있을 때 인덱스 분석으로 카테고리 후보 제안 핸들러.

    Args:
        container: 서비스 컨테이너
        top_k: 반환할 후보 수

    Returns:
        후보 목록 JSON 문자열
    """
    top_k = validate_top_k(top_k, min_val=1, max_val=20)
    suggestions = container.category_service.suggest_categories(top_k=top_k)
    return _json_response({"suggestions": suggestions})


@mcp_handler("wiki_pending")
def handle_wiki_pending(
    container: "ServiceContainer",
    limit: int = 20,
    daemon_pending: list[dict] | None = None,
) -> str:
    """미분류 / 정리 대기 파일 목록 핸들러.

    Args:
        container: 서비스 컨테이너
        limit: 최대 반환 개수
        daemon_pending: daemon이 pending.jsonl에 쌓아둔 active entry 목록.
            None이 아니면 ClassificationService 결과 앞에 머지하고 중복 path 제거.

    Returns:
        pending 목록 JSON 문자열
    """
    limit = validate_limit(limit, min_val=1, max_val=200)

    pending = container.classification_service.find_pending(limit=limit)
    items: list[dict] = []
    seen_paths: set[str] = set()
    if daemon_pending:
        for entry in daemon_pending:
            path = entry.get("path")
            if not isinstance(path, str) or path in seen_paths:
                continue
            seen_paths.add(path)
            items.append({**entry, "source": "daemon"})
    for item in pending:
        d = item.to_dict()
        if d.get("path") in seen_paths:
            continue
        seen_paths.add(d["path"])
        items.append({**d, "source": "index"})
        if len(items) >= limit:
            break

    return _json_response({"items": items[:limit], "count": len(items[:limit])})


def handle_wiki_daemon_status(
    wiki_path,
    status_reader=None,
    pid_checker=None,
) -> str:
    """Daemon 상태 조회 핸들러.

    Args:
        wiki_path: wiki 루트 ``Path``
        status_reader: ``StatusFile`` 인스턴스 또는 ``None`` (None이면 즉석 생성)
        pid_checker: 테스트 주입용 hook ``Callable[[Path], tuple[bool, int | None]]``

    Returns:
        ``{state, alive, pid, applied_count, pending_count, ...}`` JSON.
        오류가 나도 raise하지 않고 ``state=unknown``으로 응답.
    """
    # 읽기 로직은 infrastructure.daemon.read_daemon_status facade 에 위임한다
    # (server/handlers 중복 제거 + 계층 직접 의존 집중). facade 가 실패 시
    # {"state": "unknown", ...} 를 반환하므로 raise-금지 계약도 유지된다.
    from wiki_search_mcp.infrastructure.daemon import read_daemon_status

    data = read_daemon_status(
        wiki_path, status_reader=status_reader, pid_checker=pid_checker
    )
    return _json_response(data)


@mcp_handler("wiki_suggest_classification")
def handle_wiki_suggest_classification(
    container: "ServiceContainer", path: str
) -> str:
    """단일 파일 분류 추천 핸들러.

    Args:
        container: 서비스 컨테이너
        path: 대상 문서 경로

    Returns:
        ClassificationSuggestion JSON 문자열
    """
    validated_path = validate_path_required(path)
    suggestion = container.classification_service.suggest_classification(
        validated_path
    )
    return _json_response(suggestion.to_dict())


@mcp_handler("wiki_suggest_subfolders")
def handle_wiki_suggest_subfolders(
    container: "ServiceContainer", folder_path: str, min_cluster_size: int = 3
) -> str:
    """평면 프로젝트 폴더의 서브폴더 계층화 제안 핸들러.

    경로 검증은 서비스(``validate_dir_path``)가 수행한다(폴더 대상이라 .md
    강제 정규화를 하지 않기 위함).

    Args:
        container: 서비스 컨테이너
        folder_path: 대상 폴더 상대 경로 (예: "projects/KT_ITPARK")
        min_cluster_size: 서브폴더로 제안할 최소 파일 수

    Returns:
        SubfolderSuggestion JSON 문자열
    """
    suggestion = container.classification_service.suggest_subfolders(
        folder_path, min_cluster_size=min_cluster_size
    )
    return _json_response(suggestion.to_dict())


@mcp_handler("wiki_health_check")
def handle_wiki_health_check(
    container: "ServiceContainer", threshold_flat: int = 10
) -> str:
    """Wiki 구조 건강 진단 핸들러(평면 누적 + 빈 폴더).

    Args:
        container: 서비스 컨테이너
        threshold_flat: 평면 누적 경고 임계(직계 파일 수)

    Returns:
        HealthReport JSON 문자열
    """
    report = container.classification_service.health_check(
        threshold_flat=threshold_flat
    )
    return _json_response(report.to_dict())


@mcp_handler("wiki_suggest_filename_normalization")
def handle_wiki_suggest_filename_normalization(
    container: "ServiceContainer", folder_path: str | None = None
) -> str:
    """파일명 선두 날짜 표준화 제안 핸들러.

    Args:
        container: 서비스 컨테이너
        folder_path: 대상 폴더(None 이면 전체)

    Returns:
        FilenameNormalization JSON 문자열
    """
    result = container.classification_service.suggest_filename_normalization(
        folder_path
    )
    return _json_response(result.to_dict())
