"""Tests for infrastructure/cache/query_cache.py.

LRU 쿼리 캐시의 기능을 테스트합니다.
"""

import pytest

from wiki_search_mcp.infrastructure.cache import LRUQueryCache


class TestLRUQueryCache:
    """LRUQueryCache 테스트."""

    def test_get_or_compute_caches_result(self):
        """get_or_compute()가 결과를 캐싱."""
        cache = LRUQueryCache(maxsize=10)
        call_count = 0

        def compute(key: str) -> tuple[float, ...]:
            nonlocal call_count
            call_count += 1
            return (1.0, 2.0, 3.0)

        # 첫 호출: compute 실행
        result1 = cache.get_or_compute("query1", compute)
        assert result1 == (1.0, 2.0, 3.0)
        assert call_count == 1

        # 두 번째 호출: 캐시에서 반환
        result2 = cache.get_or_compute("query1", compute)
        assert result2 == (1.0, 2.0, 3.0)
        assert call_count == 1  # compute 호출 안 함

    def test_different_keys_cached_separately(self):
        """다른 키는 별도로 캐싱."""
        cache = LRUQueryCache(maxsize=10)

        def compute(key: str) -> tuple[float, ...]:
            return (float(len(key)),)

        result1 = cache.get_or_compute("short", compute)
        result2 = cache.get_or_compute("longer", compute)

        assert result1 == (5.0,)
        assert result2 == (6.0,)
        assert cache.size == 2

    def test_lru_eviction(self):
        """maxsize 초과 시 LRU 항목 제거."""
        cache = LRUQueryCache(maxsize=2)

        def compute(key: str) -> tuple[float, ...]:
            return (float(hash(key) % 100),)

        cache.get_or_compute("a", compute)
        cache.get_or_compute("b", compute)
        cache.get_or_compute("c", compute)  # "a" 제거됨

        assert cache.size == 2
        # "a"는 제거되었으므로 다시 계산 필요
        # "b", "c"는 캐시에 있음

    def test_lru_access_order_updated(self):
        """최근 사용된 항목은 LRU 순서에서 뒤로."""
        cache = LRUQueryCache(maxsize=3)
        call_count = {"a": 0, "b": 0, "c": 0, "d": 0}

        def compute(key: str) -> tuple[float, ...]:
            call_count[key] += 1
            return (1.0,)

        cache.get_or_compute("a", compute)  # [a]
        cache.get_or_compute("b", compute)  # [a, b]
        cache.get_or_compute("c", compute)  # [a, b, c]
        cache.get_or_compute("a", compute)  # [b, c, a] - "a" 접근 → LRU 순서 갱신
        cache.get_or_compute("d", compute)  # [c, a, d] - "b" 제거됨 (가장 오래됨)

        # "b"는 제거되어 다시 계산 필요
        cache.get_or_compute("b", compute)  # [a, d, b] - "c" 제거됨
        assert call_count["b"] == 2  # 두 번 계산됨

        # "a"는 캐시에 유지
        cache.get_or_compute("a", compute)  # [d, b, a]
        assert call_count["a"] == 1  # 여전히 한 번만 계산

    def test_clear_removes_all(self):
        """clear()로 모든 캐시 제거."""
        cache = LRUQueryCache(maxsize=10)

        def compute(key: str) -> tuple[float, ...]:
            return (1.0,)

        cache.get_or_compute("a", compute)
        cache.get_or_compute("b", compute)

        assert cache.size == 2

        cache.clear()

        assert cache.size == 0

    def test_cache_info(self):
        """cache_info()로 캐시 정보 조회."""
        cache = LRUQueryCache(maxsize=100)

        def compute(key: str) -> tuple[float, ...]:
            return (1.0,)

        cache.get_or_compute("a", compute)

        info = cache.cache_info()

        assert info["size"] == 1
        assert info["maxsize"] == 100
