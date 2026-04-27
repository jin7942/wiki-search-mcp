"""Singleton embedding model provider.

임베딩 모델을 전역 캐시로 관리하여 메모리 중복 로드를 방지합니다.
Indexer와 Searcher가 동일한 모델 인스턴스를 공유합니다.

사용 예:
    from wiki_search_mcp.infrastructure.embedding import get_model

    # 동일한 모델은 한 번만 로드됨
    model1 = get_model("accurate")
    model2 = get_model("accurate")  # 캐시에서 반환
    assert model1 is model2  # True
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING

from wiki_search_mcp.core.config import DEFAULT_EMBEDDING_MODEL, EMBEDDING_MODELS

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

# 전역 모델 캐시 (싱글톤)
_model_cache: dict[str, "SentenceTransformer"] = {}
_lock = threading.Lock()


def get_model(model_name: str | None = None) -> "SentenceTransformer":
    """싱글톤 모델 반환.

    동일 모델은 한 번만 로드하고 이후에는 캐시에서 반환합니다.
    스레드 안전하게 구현되어 있습니다.

    Args:
        model_name: 모델 이름 또는 프리셋 ("fast", "accurate").
                    None이면 환경변수 또는 기본값 사용.

    Returns:
        SentenceTransformer 모델 인스턴스

    Examples:
        >>> model1 = get_model("accurate")
        >>> model2 = get_model("accurate")
        >>> model1 is model2
        True
    """
    from sentence_transformers import SentenceTransformer

    # 모델 키 결정
    model_key = model_name or os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)

    # 프리셋 → 실제 모델 경로 변환
    model_path = EMBEDDING_MODELS.get(model_key, model_key)

    # 스레드 안전하게 캐시 접근
    with _lock:
        if model_path not in _model_cache:
            _model_cache[model_path] = SentenceTransformer(model_path)
        return _model_cache[model_path]


def clear_cache() -> None:
    """모델 캐시 클리어.

    테스트에서 모델 캐시를 초기화할 때 사용합니다.
    운영 환경에서는 사용하지 마세요.
    """
    global _model_cache
    with _lock:
        _model_cache = {}


def get_cached_models() -> list[str]:
    """캐시된 모델 목록 반환 (디버그용).

    Returns:
        캐시된 모델 경로 리스트
    """
    with _lock:
        return list(_model_cache.keys())
