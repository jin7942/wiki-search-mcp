"""Input validation utilities.

핸들러 레벨의 입력 검증 함수들입니다.
범위 검증, 빈 값 검증 등 공통 검증 로직을 제공합니다.

사용 예:
    from wiki_search_mcp.core.validators import validate_top_k, validate_query

    top_k = validate_top_k(user_input, min_val=1, max_val=100)
    query = validate_query(user_query)
"""

from __future__ import annotations


def validate_top_k(value: int, min_val: int = 1, max_val: int = 100) -> int:
    """top_k 범위 검증 및 클램핑.

    범위를 벗어나면 경계값으로 조정합니다.

    Args:
        value: 검증할 값
        min_val: 최솟값 (기본 1)
        max_val: 최댓값 (기본 100)

    Returns:
        클램핑된 값

    Examples:
        >>> validate_top_k(5)
        5
        >>> validate_top_k(0)
        1
        >>> validate_top_k(200)
        100
    """
    return max(min_val, min(max_val, value))


def validate_limit(value: int, min_val: int = 1, max_val: int = 500) -> int:
    """limit 범위 검증 및 클램핑.

    Args:
        value: 검증할 값
        min_val: 최솟값 (기본 1)
        max_val: 최댓값 (기본 500)

    Returns:
        클램핑된 값
    """
    return max(min_val, min(max_val, value))


def validate_preview_size(value: int, min_val: int = 0, max_val: int = 2000) -> int:
    """preview_size 범위 검증 및 클램핑.

    Args:
        value: 검증할 값
        min_val: 최솟값 (기본 0)
        max_val: 최댓값 (기본 2000)

    Returns:
        클램핑된 값
    """
    return max(min_val, min(max_val, value))


def validate_confidence_min(value: int, min_val: int = 0, max_val: int = 100) -> int:
    """confidence_min 범위 검증 및 클램핑.

    Args:
        value: 검증할 값
        min_val: 최솟값 (기본 0)
        max_val: 최댓값 (기본 100)

    Returns:
        클램핑된 값
    """
    return max(min_val, min(max_val, value))


def validate_query(query: str) -> str:
    """쿼리 문자열 검증.

    빈 문자열이면 ValueError를 발생시킵니다.

    Args:
        query: 검증할 쿼리

    Returns:
        정리된 쿼리 (strip 적용)

    Raises:
        ValueError: 쿼리가 비어있을 때

    Examples:
        >>> validate_query("  hello  ")
        'hello'
        >>> validate_query("")
        Traceback (most recent call last):
        ...
        ValueError: Query cannot be empty
    """
    stripped = query.strip() if query else ""
    if not stripped:
        raise ValueError("Query cannot be empty")
    return stripped


def validate_path_required(path: str) -> str:
    """필수 경로 검증.

    빈 문자열이면 ValueError를 발생시킵니다.

    Args:
        path: 검증할 경로

    Returns:
        정리된 경로 (strip 적용)

    Raises:
        ValueError: 경로가 비어있을 때

    Examples:
        >>> validate_path_required("docs/readme.md")
        'docs/readme.md'
        >>> validate_path_required("")
        Traceback (most recent call last):
        ...
        ValueError: Path cannot be empty
    """
    stripped = path.strip() if path else ""
    if not stripped:
        raise ValueError("Path cannot be empty")
    return stripped


def validate_search_mode(mode: str) -> str:
    """검색 모드 검증.

    유효하지 않은 모드면 기본값 "hybrid"를 반환합니다.

    Args:
        mode: 검증할 모드

    Returns:
        유효한 모드 ("hybrid" | "vector" | "keyword")

    Examples:
        >>> validate_search_mode("vector")
        'vector'
        >>> validate_search_mode("invalid")
        'hybrid'
    """
    valid_modes = ("hybrid", "vector", "keyword")
    return mode if mode in valid_modes else "hybrid"


def validate_sort_by(sort_by: str) -> str:
    """정렬 기준 검증.

    유효하지 않은 값이면 기본값 "similarity"를 반환합니다.

    Args:
        sort_by: 검증할 정렬 기준

    Returns:
        유효한 정렬 기준

    Examples:
        >>> validate_sort_by("confidence")
        'confidence'
        >>> validate_sort_by("invalid")
        'similarity'
    """
    valid_values = ("similarity", "confidence", "updated", "title")
    return sort_by if sort_by in valid_values else "similarity"


def validate_sort_order(sort_order: str) -> str:
    """정렬 순서 검증.

    유효하지 않은 값이면 기본값 "desc"를 반환합니다.

    Args:
        sort_order: 검증할 정렬 순서

    Returns:
        유효한 정렬 순서 ("asc" | "desc")

    Examples:
        >>> validate_sort_order("asc")
        'asc'
        >>> validate_sort_order("invalid")
        'desc'
    """
    return sort_order if sort_order in ("asc", "desc") else "desc"
