"""EmbeddingProvider implementation.

core.protocols.EmbeddingProvider 인터페이스의 구현체입니다.
model_provider를 사용하여 싱글톤 모델을 공유합니다.

사용 예:
    from wiki_search_mcp.infrastructure.embedding import Embedder

    embedder = Embedder()  # 기본 모델 사용
    vector = embedder.encode("텍스트")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .model_provider import get_model

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class Embedder:
    """EmbeddingProvider 구현.

    싱글톤 model_provider를 사용하여 메모리 효율적입니다.
    여러 Embedder 인스턴스가 동일한 모델을 공유합니다.

    Attributes:
        _model: 공유 SentenceTransformer 인스턴스
    """

    def __init__(self, model_name: str | None = None):
        """Embedder 초기화.

        Args:
            model_name: 모델 이름 또는 프리셋 ("fast", "accurate").
                        None이면 기본값 사용.
        """
        self._model: "SentenceTransformer" = get_model(model_name)

    def encode(self, text: str) -> list[float]:
        """단일 텍스트 임베딩.

        Args:
            text: 임베딩할 텍스트

        Returns:
            임베딩 벡터 (float 리스트)

        Examples:
            >>> embedder = Embedder()
            >>> vec = embedder.encode("Nginx 설정")
            >>> len(vec)  # 768 (모델에 따라 다름)
            768
        """
        return self._model.encode(text).tolist()

    def encode_batch(
        self, texts: list[str], show_progress: bool = False
    ) -> list[list[float]]:
        """배치 임베딩.

        여러 텍스트를 한 번에 임베딩합니다.
        GPU 사용 시 배치 처리가 더 효율적입니다.

        Args:
            texts: 임베딩할 텍스트 리스트
            show_progress: 진행률 표시 여부

        Returns:
            임베딩 벡터 리스트

        Examples:
            >>> embedder = Embedder()
            >>> vecs = embedder.encode_batch(["텍스트1", "텍스트2"])
            >>> len(vecs)
            2
        """
        embeddings = self._model.encode(texts, show_progress_bar=show_progress)
        return [e.tolist() for e in embeddings]

    def encode_as_tuple(self, text: str) -> tuple[float, ...]:
        """단일 텍스트 임베딩 (hashable tuple 반환).

        캐시 키로 사용하기 위해 tuple로 반환합니다.

        Args:
            text: 임베딩할 텍스트

        Returns:
            임베딩 벡터 (hashable tuple)
        """
        return tuple(self._model.encode(text).tolist())

    @property
    def dimension(self) -> int:
        """임베딩 차원.

        Returns:
            모델의 임베딩 차원 수
        """
        return self._model.get_sentence_embedding_dimension()
