"""Tests for infrastructure/cache/query_cache.py.

LRU 쿼리 캐시의 기능을 테스트합니다.
"""

import threading

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


class TestLRUQueryCacheConcurrency:
    """동시 접근 안전성 테스트 (FastMCP 다중 클라이언트 시나리오)."""

    def test_concurrent_access_no_corruption(self):
        """다중 스레드 동시 접근 시 _cache/_order 손상 없음.

        과거에는 락이 없어 _order.remove/append, pop(0)+del 사이에서
        race 가 발생할 수 있었다. 락 도입 후에는 예외 없이 일관 상태를
        유지해야 한다.
        """
        cache = LRUQueryCache(maxsize=50)
        errors: list[Exception] = []

        def worker(tid: int) -> None:
            try:
                for i in range(200):
                    # 키 공간을 작게(0~99) 해 히트/미스/eviction 이 뒤섞이게 한다.
                    key = f"k{i % 100}"
                    cache.get_or_compute(key, lambda k: (float(len(k)),))
            except Exception as e:  # noqa: BLE001 - 테스트에서 race 노출용
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"동시 접근 중 예외 발생: {errors}"
        # 불변식: maxsize 초과 금지, _cache 와 _order 크기 일치.
        assert cache.size <= 50
        assert len(cache._cache) == len(cache._order)
        assert set(cache._cache.keys()) == set(cache._order)

    def test_compute_runs_outside_lock(self):
        """compute_fn 실행 중 다른 스레드가 캐시에 접근 가능(락 점유 안 함).

        느린 compute 가 락을 잡고 있으면 전체 검색이 직렬화된다. compute 는
        락 밖에서 실행돼야 하므로, 한 키 계산이 진행 중이어도 다른 키의
        캐시 히트는 즉시 반환돼야 한다.
        """
        cache = LRUQueryCache(maxsize=10)
        cache.get_or_compute("fast", lambda k: (1.0,))  # 미리 캐싱

        started = threading.Event()
        release = threading.Event()

        def slow_compute(k: str) -> tuple[float, ...]:
            started.set()
            release.wait(timeout=2.0)
            return (9.0,)

        slow_thread = threading.Thread(
            target=lambda: cache.get_or_compute("slow", slow_compute)
        )
        slow_thread.start()
        assert started.wait(timeout=2.0), "slow_compute 가 시작되지 않음"

        # slow compute 가 진행 중인 동안 캐시 히트가 블록되지 않아야 함
        hit_done = threading.Event()

        def hit() -> None:
            cache.get_or_compute("fast", lambda k: (1.0,))
            hit_done.set()

        hit_thread = threading.Thread(target=hit)
        hit_thread.start()
        assert hit_done.wait(timeout=1.0), "compute 중 캐시 히트가 블록됨(락 점유)"

        release.set()
        slow_thread.join(timeout=2.0)
        hit_thread.join(timeout=2.0)
