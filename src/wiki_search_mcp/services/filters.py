"""Filter utilities for search and document services.

검색 결과 및 문서 목록에 필터를 적용하는 유틸리티입니다.
중복 로직을 통합하여 일관된 필터링을 제공합니다.

사용 예:
    from wiki_search_mcp.services.filters import passes_filters, apply_filters

    if passes_filters(doc_dict, filters):
        results.append(doc_dict)

    # 또는 한번에 필터링
    filtered = apply_filters(raw_results, filters)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wiki_search_mcp.core.models import SearchFilters


def passes_filters(doc: dict[str, Any], filters: "SearchFilters") -> bool:
    """문서가 필터 조건을 통과하는지 확인.

    Args:
        doc: 문서 데이터 (dict)
        filters: 검색 필터

    Returns:
        True면 필터 통과, False면 필터링됨

    Filter 조건:
        - include_states: 문서 상태가 포함되어야 함
        - category: 카테고리가 일치해야 함 (지정된 경우)
        - tags: 태그 중 하나 이상이 일치해야 함 (OR 조건, 지정된 경우)
        - confidence_min: 신뢰도 점수가 최소값 이상이어야 함 (지정된 경우)
    """
    # state 필터: 문서 상태가 허용된 상태 목록에 있어야 함
    state = doc.get("state", "stable")
    if state not in filters.include_states:
        return False

    # 카테고리 필터: 지정된 경우 정확히 일치해야 함
    if filters.category and doc.get("category") != filters.category:
        return False

    # 태그 필터: 지정된 태그 중 하나 이상 포함 (OR 조건)
    if filters.tags:
        doc_tags = doc.get("tags", [])
        if not any(t in doc_tags for t in filters.tags):
            return False

    # 신뢰도 필터: 최소 점수 이상
    if filters.confidence_min > 0:
        if doc.get("confidence_score", 0) < filters.confidence_min:
            return False

    return True


def apply_filters(
    results: list[dict[str, Any]],
    filters: "SearchFilters",
) -> list[dict[str, Any]]:
    """검색 결과 리스트에 필터 적용.

    Args:
        results: 필터링할 문서 리스트
        filters: 검색 필터

    Returns:
        필터를 통과한 문서 리스트
    """
    return [doc for doc in results if passes_filters(doc, filters)]


def apply_simple_filters(
    results: list[dict[str, Any]],
    category: str | None = None,
    tag: str | None = None,
    state: str | None = None,
) -> list[dict[str, Any]]:
    """단순 필터 적용 (SearchFilters 없이).

    document_service.list_documents() 등에서 사용합니다.

    Args:
        results: 필터링할 문서 리스트
        category: 카테고리 필터 (선택)
        tag: 태그 필터 (선택, 단일)
        state: 상태 필터 (선택)

    Returns:
        필터를 통과한 문서 리스트
    """
    filtered = []
    for doc in results:
        if category and doc.get("category") != category:
            continue
        if tag and tag not in doc.get("tags", []):
            continue
        if state and doc.get("state") != state:
            continue
        filtered.append(doc)
    return filtered
