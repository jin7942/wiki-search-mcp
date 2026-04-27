"""LRU query cache implementation.

core.protocols.QueryCache 인터페이스의 구현체입니다.
쿼리 임베딩 결과를 LRU 캐시에 저장합니다.

사용 예:
    from wiki_search_mcp.infrastructure.cache import LRUQueryCache

    cache = LRUQueryCache(maxsize=100)
    embedding = cache.get_or_compute("nginx 설정", embedder.encode_as_tuple)
"""

from __future__ import annotations

import functools
from typing import Callable


class LRUQueryCache:
    """LRU 쿼리 캐시 구현.

    QueryCache 프로토콜을 구현합니다.
    functools.lru_cache를 사용하여 구현합니다.

    Attributes:
        _cache_fn: 캐시된 함수
        _maxsize: 최대 캐시 크기
    """

    def __init__(self, maxsize: int = 100):
        """LRUQueryCache 초기화.

        Args:
            maxsize: 최대 캐시 항목 수 (기본값: 100)
        """
        self._maxsize = maxsize
        self._cache: dict[str, tuple[float, ...]] = {}
        self._order: list[str] = []

    def get_or_compute(
        self, key: str, compute_fn: Callable[[str], tuple[float, ...]]
    ) -> tuple[float, ...]:
        """캐시 조회 또는 계산.

        Args:
            key: 캐시 키 (쿼리 문자열)
            compute_fn: 캐시 미스 시 호출할 함수

        Returns:
            임베딩 벡터 (hashable tuple)
        """
        if key in self._cache:
            # LRU: 최근 사용된 키를 뒤로 이동
            self._order.remove(key)
            self._order.append(key)
            return self._cache[key]

        # 캐시 미스: 계산
        value = compute_fn(key)

        # LRU eviction
        if len(self._cache) >= self._maxsize:
            oldest_key = self._order.pop(0)
            del self._cache[oldest_key]

        self._cache[key] = value
        self._order.append(key)

        return value

    def clear(self) -> None:
        """캐시 초기화."""
        self._cache.clear()
        self._order.clear()

    @property
    def size(self) -> int:
        """현재 캐시 크기.

        Returns:
            캐시된 항목 수
        """
        return len(self._cache)

    def cache_info(self) -> dict[str, int]:
        """캐시 정보.

        Returns:
            캐시 크기 및 최대 크기
        """
        return {
            "size": self.size,
            "maxsize": self._maxsize,
        }
