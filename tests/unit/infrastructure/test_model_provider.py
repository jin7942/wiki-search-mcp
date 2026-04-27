"""Tests for infrastructure/embedding/model_provider.py.

싱글톤 모델 로더의 캐싱 및 스레드 안전성을 테스트합니다.
sentence_transformers가 설치되지 않은 환경에서도 테스트 가능합니다.
"""

import sys
import threading
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_sentence_transformers():
    """sentence_transformers 모듈 Mock 설정."""
    mock_st = MagicMock()
    mock_st.SentenceTransformer = MagicMock()
    sys.modules["sentence_transformers"] = mock_st
    yield mock_st
    # 테스트 후 캐시 정리
    if "wiki_search_mcp.infrastructure.embedding.model_provider" in sys.modules:
        from wiki_search_mcp.infrastructure.embedding import clear_cache

        clear_cache()


class TestModelProviderSingleton:
    """모델 싱글톤 테스트."""

    def test_get_model_returns_same_instance(self, mock_sentence_transformers):
        """동일 모델 요청 시 같은 인스턴스 반환."""
        # 모듈 재로드하여 mock 적용
        import importlib

        if "wiki_search_mcp.infrastructure.embedding.model_provider" in sys.modules:
            importlib.reload(
                sys.modules["wiki_search_mcp.infrastructure.embedding.model_provider"]
            )

        from wiki_search_mcp.infrastructure.embedding import clear_cache, get_model

        mock_model = MagicMock()
        mock_sentence_transformers.SentenceTransformer.return_value = mock_model

        clear_cache()

        model1 = get_model("fast")
        model2 = get_model("fast")

        assert model1 is model2
        # SentenceTransformer는 한 번만 호출됨
        assert mock_sentence_transformers.SentenceTransformer.call_count == 1

    def test_different_models_cached_separately(self, mock_sentence_transformers):
        """다른 모델은 별도로 캐싱."""
        from wiki_search_mcp.infrastructure.embedding import clear_cache, get_model

        mock_fast = MagicMock()
        mock_accurate = MagicMock()

        def create_mock(model_path):
            if "MiniLM" in model_path:
                return mock_fast
            return mock_accurate

        mock_sentence_transformers.SentenceTransformer.side_effect = create_mock

        clear_cache()

        model_fast = get_model("fast")
        model_accurate = get_model("accurate")

        assert model_fast is not model_accurate
        assert model_fast is mock_fast
        assert model_accurate is mock_accurate

    def test_clear_cache_removes_models(self, mock_sentence_transformers):
        """clear_cache()로 캐시 초기화."""
        from wiki_search_mcp.infrastructure.embedding import clear_cache, get_model
        from wiki_search_mcp.infrastructure.embedding.model_provider import (
            get_cached_models,
        )

        mock_sentence_transformers.SentenceTransformer.return_value = MagicMock()

        clear_cache()
        get_model("fast")

        assert len(get_cached_models()) == 1

        clear_cache()

        assert len(get_cached_models()) == 0


class TestModelProviderThreadSafety:
    """스레드 안전성 테스트."""

    def test_concurrent_access(self, mock_sentence_transformers):
        """동시 접근 시 스레드 안전."""
        from wiki_search_mcp.infrastructure.embedding import clear_cache, get_model

        mock_model = MagicMock()
        call_count = 0
        lock = threading.Lock()

        def mock_init(model_path):
            nonlocal call_count
            with lock:
                call_count += 1
            return mock_model

        mock_sentence_transformers.SentenceTransformer.side_effect = mock_init

        clear_cache()

        results = []
        threads = []

        def get_and_store():
            model = get_model("fast")
            results.append(model)

        # 10개 스레드 동시 실행
        for _ in range(10):
            t = threading.Thread(target=get_and_store)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # 모든 결과가 동일한 인스턴스
        assert all(r is results[0] for r in results)
        # SentenceTransformer는 한 번만 호출됨 (스레드 안전)
        assert call_count == 1


class TestModelProviderPresets:
    """프리셋 변환 테스트."""

    def test_fast_preset_uses_minilm(self, mock_sentence_transformers):
        """fast 프리셋은 MiniLM 모델 사용."""
        from wiki_search_mcp.infrastructure.embedding import clear_cache, get_model

        mock_sentence_transformers.SentenceTransformer.return_value = MagicMock()

        clear_cache()
        get_model("fast")

        # all-MiniLM-L6-v2 모델로 호출됨
        call_args = mock_sentence_transformers.SentenceTransformer.call_args[0][0]
        assert "MiniLM" in call_args

    def test_accurate_preset_uses_kosroberta(self, mock_sentence_transformers):
        """accurate 프리셋은 ko-sroberta 모델 사용."""
        from wiki_search_mcp.infrastructure.embedding import clear_cache, get_model

        mock_sentence_transformers.SentenceTransformer.return_value = MagicMock()

        clear_cache()
        get_model("accurate")

        call_args = mock_sentence_transformers.SentenceTransformer.call_args[0][0]
        assert "ko-sroberta" in call_args

    def test_custom_model_path_used_directly(self, mock_sentence_transformers):
        """프리셋이 아닌 경우 직접 모델 경로 사용."""
        from wiki_search_mcp.infrastructure.embedding import clear_cache, get_model

        mock_sentence_transformers.SentenceTransformer.return_value = MagicMock()

        clear_cache()
        get_model("custom/model/path")

        call_args = mock_sentence_transformers.SentenceTransformer.call_args[0][0]
        assert call_args == "custom/model/path"
