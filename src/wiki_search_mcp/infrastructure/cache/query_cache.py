"""LRU query cache implementation.

core.protocols.QueryCache 인터페이스의 구현체입니다.
쿼리 임베딩 결과를 LRU 캐시에 저장합니다.

사용 예:
    from wiki_search_mcp.infrastructure.cache import LRUQueryCache

    cache = LRUQueryCache(maxsize=100)
    embedding = cache.get_or_compute("nginx 설정", embedder.encode_as_tuple)
"""

from __future__ import annotations

import threading
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
        # FastMCP 는 여러 클라이언트의 검색 요청을 동시에 처리한다.
        # _cache/_order 의 remove/append, pop(0)+del 사이 race 를 막기 위해
        # 모든 자료구조 접근을 락으로 보호한다.
        self._lock = threading.Lock()

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
        # 1단계: 락 안에서 히트 확인 + LRU 순서 갱신.
        with self._lock:
            if key in self._cache:
                self._order.remove(key)
                self._order.append(key)
                return self._cache[key]

        # 2단계: 캐시 미스 → 락 밖에서 계산.
        # compute_fn(임베딩)은 느리므로 락을 잡은 채 호출하면 모든 검색이
        # 직렬화된다. 따라서 임계구역 밖에서 계산한다. 같은 키를 여러
        # 스레드가 동시에 계산할 수 있으나(중복 계산), 결과는 동일하므로
        # 정확성에는 문제없고 자료구조만 일관되면 된다.
        value = compute_fn(key)

        # 3단계: 락 안에서 저장 + eviction.
        with self._lock:
            # 계산 중 다른 스레드가 먼저 채웠을 수 있다 → 그 값을 정본으로.
            if key in self._cache:
                self._order.remove(key)
                self._order.append(key)
                return self._cache[key]

            if len(self._cache) >= self._maxsize:
                oldest_key = self._order.pop(0)
                del self._cache[oldest_key]

            self._cache[key] = value
            self._order.append(key)
            return value

    def clear(self) -> None:
        """캐시 초기화."""
        with self._lock:
            self._cache.clear()
            self._order.clear()

    @property
    def size(self) -> int:
        """현재 캐시 크기.

        Returns:
            캐시된 항목 수
        """
        with self._lock:
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
