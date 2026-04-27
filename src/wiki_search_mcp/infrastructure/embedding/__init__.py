"""Embedding infrastructure.

임베딩 모델 로드 및 인코딩 기능을 제공합니다.

Modules:
    model_provider: 싱글톤 모델 로더
    embedder: EmbeddingProvider 구현체
"""

from .embedder import Embedder
from .model_provider import clear_cache, get_model

__all__ = ["Embedder", "get_model", "clear_cache"]
