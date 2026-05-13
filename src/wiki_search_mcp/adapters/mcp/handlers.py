"""MCP Tool Handlers.

MCP 도구 핸들러 함수들입니다.
ServiceContainer를 통해 서비스를 호출하고 JSON 직렬화를 담당합니다.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

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


# =============================================================================
# Search Handlers
# =============================================================================


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
    try:
        # 입력 검증 (validators.py 사용)
        try:
            validated_query = validate_query(query)
        except ValueError as e:
            return _json_error(str(e))

        # 파라미터 정규화 (validators.py 사용)
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

    except BusinessException as e:
        logger.warning(f"wiki_search business error: {e}")
        return _json_error(str(e))
    except TechnicalException as e:
        logger.error(f"wiki_search technical error: {e}")
        return _json_error(str(e))
    except (ValueError, TypeError) as e:
        logger.warning(f"wiki_search input validation error: {e}")
        return _json_error(str(e))
    except OSError as e:
        logger.error(f"wiki_search I/O error: {e}")
        return _json_error("File system error")
    except Exception as e:
        logger.exception(f"wiki_search unexpected error: {e}")
        return _json_error("Internal error")


# =============================================================================
# Document Handlers
# =============================================================================


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
    try:
        # 입력 검증 (validators.py 사용)
        try:
            validated_path = validate_path_required(path)
        except ValueError as e:
            return _json_error(str(e))

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

    except InvalidPathError as e:
        logger.warning(f"wiki_get_document security error: {e}")
        return _json_error(str(e))
    except BusinessException as e:
        logger.warning(f"wiki_get_document business error: {e}")
        return _json_error(str(e))
    except TechnicalException as e:
        logger.error(f"wiki_get_document technical error: {e}")
        return _json_error(str(e))
    except (ValueError, TypeError) as e:
        logger.warning(f"wiki_get_document input validation error: {e}")
        return _json_error(str(e))
    except OSError as e:
        logger.error(f"wiki_get_document I/O error: {e}")
        return _json_error("File system error")
    except Exception as e:
        logger.exception(f"wiki_get_document unexpected error: {e}")
        return _json_error("Internal error")


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
    try:
        # 파라미터 정규화 (validators.py 사용)
        limit = validate_limit(limit)

        # 서비스 호출
        documents = container.document_service.list_documents(
            category=category,
            tag=tag,
            state=state,
            limit=limit,
        )

        # 결과 구성
        doc_list = [
            {
                "path": doc.path,
                "title": doc.title,
                "category": doc.category,
                "state": doc.state,
                "tags": list(doc.tags),
            }
            for doc in documents
        ]

        return _json_response({
            "documents": doc_list,
            "count": len(doc_list),
            "filters": {
                "category": category,
                "tag": tag,
                "state": state,
            },
        })

    except BusinessException as e:
        logger.warning(f"wiki_list_documents business error: {e}")
        return _json_error(str(e))
    except TechnicalException as e:
        logger.error(f"wiki_list_documents technical error: {e}")
        return _json_error(str(e))
    except (ValueError, TypeError) as e:
        logger.warning(f"wiki_list_documents input validation error: {e}")
        return _json_error(str(e))
    except OSError as e:
        logger.error(f"wiki_list_documents I/O error: {e}")
        return _json_error("File system error")
    except Exception as e:
        logger.exception(f"wiki_list_documents unexpected error: {e}")
        return _json_error("Internal error")


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
    try:
        # 입력 검증 (validators.py 사용)
        try:
            validated_path = validate_path_required(path)
        except ValueError as e:
            return _json_error(str(e))

        top_k = validate_top_k(top_k, max_val=20)

        # 서비스 호출
        similar_docs = container.document_service.get_similar(
            path=validated_path,
            top_k=top_k,
        )

        # 결과 구성
        similar_list = [
            {
                "path": doc.path,
                "title": doc.title,
                "category": doc.category,
            }
            for doc in similar_docs
        ]

        return _json_response({
            "source": validated_path,
            "similar": similar_list,
            "count": len(similar_list),
        })

    except InvalidPathError as e:
        logger.warning(f"wiki_get_similar security error: {e}")
        return _json_error(str(e))
    except BusinessException as e:
        logger.warning(f"wiki_get_similar business error: {e}")
        return _json_error(str(e))
    except TechnicalException as e:
        logger.error(f"wiki_get_similar technical error: {e}")
        return _json_error(str(e))
    except (ValueError, TypeError) as e:
        logger.warning(f"wiki_get_similar input validation error: {e}")
        return _json_error(str(e))
    except OSError as e:
        logger.error(f"wiki_get_similar I/O error: {e}")
        return _json_error("File system error")
    except Exception as e:
        logger.exception(f"wiki_get_similar unexpected error: {e}")
        return _json_error("Internal error")


# =============================================================================
# Graph Handlers
# =============================================================================


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
    try:
        # 입력 검증 (validators.py 사용)
        try:
            validated_path = validate_path_required(path)
        except ValueError as e:
            return _json_error(str(e))

        # 서비스 호출
        backlinks = container.graph_service.get_backlinks(validated_path)

        # 결과 구성
        backlink_list = [
            {
                "path": doc.path,
                "title": doc.title,
                "category": doc.category,
            }
            for doc in backlinks
        ]

        return _json_response({
            "target": validated_path,
            "backlinks": backlink_list,
            "count": len(backlink_list),
        })

    except InvalidPathError as e:
        logger.warning(f"wiki_get_backlinks security error: {e}")
        return _json_error(str(e))
    except BusinessException as e:
        logger.warning(f"wiki_get_backlinks business error: {e}")
        return _json_error(str(e))
    except TechnicalException as e:
        logger.error(f"wiki_get_backlinks technical error: {e}")
        return _json_error(str(e))
    except (ValueError, TypeError) as e:
        logger.warning(f"wiki_get_backlinks input validation error: {e}")
        return _json_error(str(e))
    except OSError as e:
        logger.error(f"wiki_get_backlinks I/O error: {e}")
        return _json_error("File system error")
    except Exception as e:
        logger.exception(f"wiki_get_backlinks unexpected error: {e}")
        return _json_error("Internal error")


def handle_wiki_find_orphans(container: "ServiceContainer") -> str:
    """고아 문서 검색 핸들러.

    Args:
        container: 서비스 컨테이너

    Returns:
        고아 문서 목록 JSON 문자열
    """
    try:
        # 서비스 호출
        orphans = container.graph_service.find_orphans()

        # 결과 구성
        orphan_list = [
            {
                "path": doc.path,
                "title": doc.title,
                "category": doc.category,
            }
            for doc in orphans
        ]

        return _json_response({
            "orphans": orphan_list,
            "count": len(orphan_list),
        })

    except BusinessException as e:
        logger.warning(f"wiki_find_orphans business error: {e}")
        return _json_error(str(e))
    except TechnicalException as e:
        logger.error(f"wiki_find_orphans technical error: {e}")
        return _json_error(str(e))
    except (ValueError, TypeError) as e:
        logger.warning(f"wiki_find_orphans input validation error: {e}")
        return _json_error(str(e))
    except OSError as e:
        logger.error(f"wiki_find_orphans I/O error: {e}")
        return _json_error("File system error")
    except Exception as e:
        logger.exception(f"wiki_find_orphans unexpected error: {e}")
        return _json_error("Internal error")


# =============================================================================
# Validation Handlers
# =============================================================================


def handle_wiki_validate(container: "ServiceContainer") -> str:
    """Wiki 검증 핸들러.

    Args:
        container: 서비스 컨테이너

    Returns:
        검증 결과 JSON 문자열
    """
    try:
        # 서비스 호출
        report = container.validation_service.validate()
        return _json_response(report.to_dict())

    except BusinessException as e:
        logger.warning(f"wiki_validate business error: {e}")
        return _json_error(str(e))
    except TechnicalException as e:
        logger.error(f"wiki_validate technical error: {e}")
        return _json_error(str(e))
    except (ValueError, TypeError) as e:
        logger.warning(f"wiki_validate input validation error: {e}")
        return _json_error(str(e))
    except OSError as e:
        logger.error(f"wiki_validate I/O error: {e}")
        return _json_error("File system error")
    except Exception as e:
        logger.exception(f"wiki_validate unexpected error: {e}")
        return _json_error("Internal error")


# =============================================================================
# Stats Handlers
# =============================================================================


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
    try:
        # 서비스 호출
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

    except BusinessException as e:
        logger.warning(f"wiki_stats business error: {e}")
        return _json_error(str(e))
    except TechnicalException as e:
        logger.error(f"wiki_stats technical error: {e}")
        return _json_error(str(e))
    except (ValueError, TypeError) as e:
        logger.warning(f"wiki_stats input validation error: {e}")
        return _json_error(str(e))
    except OSError as e:
        logger.error(f"wiki_stats I/O error: {e}")
        return _json_error("File system error")
    except Exception as e:
        logger.exception(f"wiki_stats unexpected error: {e}")
        return _json_error("Internal error")


# =============================================================================
# Index Handlers
# =============================================================================


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
    try:
        # 인덱싱 실행
        result = indexer.reindex(full=full)

        # 캐시 무효화
        container.invalidate_all()

        return _json_response(result)

    except BusinessException as e:
        logger.warning(f"wiki_reindex business error: {e}")
        return _json_error(str(e))
    except TechnicalException as e:
        logger.error(f"wiki_reindex technical error: {e}")
        return _json_error(str(e))
    except (ValueError, TypeError) as e:
        logger.warning(f"wiki_reindex input validation error: {e}")
        return _json_error(str(e))
    except OSError as e:
        logger.error(f"wiki_reindex I/O error: {e}")
        return _json_error("File system error")
    except Exception as e:
        logger.exception(f"wiki_reindex unexpected error: {e}")
        return _json_error("Internal error")


# =============================================================================
# Watcher Handlers
# =============================================================================


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
    try:
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

    except BusinessException as e:
        logger.warning(f"wiki_watch_status business error: {e}")
        return _json_error(str(e))
    except TechnicalException as e:
        logger.error(f"wiki_watch_status technical error: {e}")
        return _json_error(str(e))
    except (ValueError, TypeError) as e:
        logger.warning(f"wiki_watch_status input validation error: {e}")
        return _json_error(str(e))
    except OSError as e:
        logger.error(f"wiki_watch_status I/O error: {e}")
        return _json_error("File system error")
    except Exception as e:
        logger.exception(f"wiki_watch_status unexpected error: {e}")
        return _json_error("Internal error")


# =============================================================================
# Tag Handlers
# =============================================================================


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
    try:
        # 입력 검증 (validators.py 사용)
        try:
            validated_path = validate_path_required(path)
        except ValueError as e:
            return _json_error(str(e))

        top_n = validate_top_k(top_n, max_val=10)

        # 문서 조회 (본문 포함)
        doc = container.document_service.get_document(
            path=validated_path,
            include_content=True,
        )

        if doc is None:
            return _json_error(f"Document not found: {path}")

        # 본문 읽기
        content_info = container.document_service.read_content(
            path=validated_path,
            include_full=True,
        )

        content = content_info.get("content", "")
        if not content:
            return _json_error("Document has no content")

        # 자동 태그 추출
        from wiki_search_mcp.services.tagger_service import AutoTagger

        tagger = AutoTagger()
        suggested_tags = tagger.extract_tags(content, top_n)

        return _json_response({
            "path": validated_path,
            "suggested_tags": suggested_tags,
            "existing_tags": list(doc.tags),
        })

    except InvalidPathError as e:
        logger.warning(f"wiki_suggest_tags security error: {e}")
        return _json_error(str(e))
    except BusinessException as e:
        logger.warning(f"wiki_suggest_tags business error: {e}")
        return _json_error(str(e))
    except TechnicalException as e:
        logger.error(f"wiki_suggest_tags technical error: {e}")
        return _json_error(str(e))
    except (ValueError, TypeError) as e:
        logger.warning(f"wiki_suggest_tags input validation error: {e}")
        return _json_error(str(e))
    except OSError as e:
        logger.error(f"wiki_suggest_tags I/O error: {e}")
        return _json_error("File system error")
    except Exception as e:
        logger.exception(f"wiki_suggest_tags unexpected error: {e}")
        return _json_error("Internal error")


# =============================================================================
# Auto Classification Handlers
# =============================================================================


def handle_wiki_get_categories(container: "ServiceContainer") -> str:
    """현재 wiki에서 사용 가능한 카테고리 조회 핸들러.

    Args:
        container: 서비스 컨테이너

    Returns:
        카테고리 목록 JSON 문자열 (mode, categories, detected_at)
    """
    try:
        listing = container.category_service.list_categories()
        return _json_response(listing.to_dict())

    except BusinessException as e:
        logger.warning(f"wiki_get_categories business error: {e}")
        return _json_error(str(e))
    except TechnicalException as e:
        logger.error(f"wiki_get_categories technical error: {e}")
        return _json_error(str(e))
    except OSError as e:
        logger.error(f"wiki_get_categories I/O error: {e}")
        return _json_error("File system error")
    except Exception as e:
        logger.exception(f"wiki_get_categories unexpected error: {e}")
        return _json_error("Internal error")


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
    try:
        try:
            top_k = validate_top_k(top_k, min_val=1, max_val=20)
        except ValueError as e:
            return _json_error(str(e))

        suggestions = container.category_service.suggest_categories(top_k=top_k)
        return _json_response({"suggestions": suggestions})

    except BusinessException as e:
        logger.warning(f"wiki_suggest_categories business error: {e}")
        return _json_error(str(e))
    except TechnicalException as e:
        logger.error(f"wiki_suggest_categories technical error: {e}")
        return _json_error(str(e))
    except OSError as e:
        logger.error(f"wiki_suggest_categories I/O error: {e}")
        return _json_error("File system error")
    except Exception as e:
        logger.exception(f"wiki_suggest_categories unexpected error: {e}")
        return _json_error("Internal error")


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
    try:
        try:
            limit = validate_limit(limit, min_val=1, max_val=200)
        except ValueError as e:
            return _json_error(str(e))

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

    except BusinessException as e:
        logger.warning(f"wiki_pending business error: {e}")
        return _json_error(str(e))
    except TechnicalException as e:
        logger.error(f"wiki_pending technical error: {e}")
        return _json_error(str(e))
    except OSError as e:
        logger.error(f"wiki_pending I/O error: {e}")
        return _json_error("File system error")
    except Exception as e:
        logger.exception(f"wiki_pending unexpected error: {e}")
        return _json_error("Internal error")


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
    try:
        from wiki_search_mcp.infrastructure.daemon import (
            StatusFile,
            pid_file,
            status_file,
        )
        from wiki_search_mcp.infrastructure.daemon.pidfile import PidLock

        reader = status_reader if status_reader is not None else StatusFile(status_file(wiki_path))
        state_data = reader.read() or {}
        checker = pid_checker if pid_checker is not None else PidLock.is_alive
        alive, pid = checker(pid_file(wiki_path))
        if not state_data and not alive:
            return _json_response({"state": "not_running", "alive": False, "pid": None})
        return _json_response({**state_data, "alive": alive, "pid": pid})
    except Exception as e:  # noqa: BLE001 - status는 절대 raise하면 안 됨
        logger.exception("wiki_daemon_status unexpected error: %s", e)
        return _json_response({"state": "unknown", "error": str(e)[:200]})


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
    try:
        try:
            validated_path = validate_path_required(path)
        except ValueError as e:
            return _json_error(str(e))

        suggestion = container.classification_service.suggest_classification(
            validated_path
        )
        return _json_response(suggestion.to_dict())

    except InvalidPathError as e:
        logger.warning(f"wiki_suggest_classification security error: {e}")
        return _json_error(str(e))
    except BusinessException as e:
        logger.warning(f"wiki_suggest_classification business error: {e}")
        return _json_error(str(e))
    except TechnicalException as e:
        logger.error(f"wiki_suggest_classification technical error: {e}")
        return _json_error(str(e))
    except (ValueError, TypeError) as e:
        logger.warning(f"wiki_suggest_classification input validation error: {e}")
        return _json_error(str(e))
    except OSError as e:
        logger.error(f"wiki_suggest_classification I/O error: {e}")
        return _json_error("File system error")
    except Exception as e:
        logger.exception(f"wiki_suggest_classification unexpected error: {e}")
        return _json_error("Internal error")
