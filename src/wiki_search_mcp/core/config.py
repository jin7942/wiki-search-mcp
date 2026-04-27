from __future__ import annotations

"""공통 설정 상수.

여러 모듈에서 공유하는 설정값과 상수를 정의합니다.
매직 넘버를 이름 있는 상수로 관리하여 유지보수성을 높입니다.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================================
# 임베딩 모델 설정
# ============================================================================

EMBEDDING_MODELS: dict[str, str] = {
    "fast": "sentence-transformers/all-MiniLM-L6-v2",
    "accurate": "jhgan/ko-sroberta-multitask",
}
"""임베딩 모델 프리셋.

- fast: 영어 최적화, 빠른 속도
- accurate: 한국어 최적화, 높은 정확도
"""

DEFAULT_EMBEDDING_MODEL: str = "accurate"
"""기본 임베딩 모델 프리셋."""


# ============================================================================
# 검색 설정
# ============================================================================

RRF_K: int = 60
"""Reciprocal Rank Fusion 상수.

RRF 점수 계산: score = weight / (rank + k)
k가 클수록 순위 차이에 따른 점수 차이가 작아집니다.
60은 RRF 논문에서 권장하는 표준 값입니다.
"""

SEARCH_MULTIPLIER: int = 3
"""검색 결과 확장 배수.

필터링 전 더 많은 결과를 가져오기 위한 배수.
top_k * SEARCH_MULTIPLIER 개의 결과를 가져온 후 필터링합니다.
"""


# ============================================================================
# 품질 검사 임계값 (wiki_validate)
# ============================================================================

MAX_DOCS_LIMIT: int = 10000
"""validate()에서 조회하는 최대 문서 수."""

NO_FRONTMATTER_FIELD_THRESHOLD: int = 5
"""이 값 이상의 필드가 누락되면 no_frontmatter로 분류."""

PARTIAL_WARNING_RATIO: float = 0.1
"""partial 문서가 전체의 10% 초과 시 warning 상태."""

NO_FRONTMATTER_ERROR_RATIO: float = 0.3
"""no_frontmatter 문서가 전체의 30% 초과 시 error 상태."""


# ============================================================================
# 기타 설정
# ============================================================================

DEFAULT_PREVIEW_SIZE: int = 500
"""get_document()의 기본 미리보기 크기 (문자 수)."""

DEFAULT_TOP_K: int = 5
"""검색 결과 기본 반환 개수."""

MAX_RELATED_DOCS: int = 3
"""그래프 확장에서 반환하는 최대 관련 문서 수."""

MAX_GRAPH_DEPTH: int = 2
"""그래프 탐색 최대 깊이 (hop 수)."""


# ============================================================================
# 자동 분류 / pending 캐시
# ============================================================================

CATEGORY_FOLDER_THRESHOLD: int = 2
"""폴더 자동 감지 모드 진입 최소 디렉토리 수."""

LISTING_TTL_SECONDS: float = 60.0
"""CategoryService/ClassificationService 캐시 TTL."""


# ============================================================================
# Wiki 런타임 설정
# ============================================================================


@dataclass(frozen=True)
class WikiConfig:
    """Wiki 런타임 설정.

    설정 파일을 사용하지 않습니다. 환경 변수와 인자로만 결정됩니다.

    - WIKI_EMBEDDING_MODEL 환경 변수 또는 ``embedding_model`` 인자로 모델 선택
    - 무시 패턴은 ``IgnoreMatcher``가 dot-prefix + .gitignore + WIKI_IGNORE로 처리

    Attributes:
        embedding_model: 사용할 임베딩 모델 프리셋 ("fast" / "accurate") 또는 모델명
    """

    embedding_model: str = DEFAULT_EMBEDDING_MODEL

    @classmethod
    def load(cls, wiki_path: Path | None = None) -> "WikiConfig":
        """런타임 설정 로드.

        ``wiki_path``는 향후 확장 호환성을 위해 받지만 현재는 사용하지 않습니다.
        환경 변수 ``WIKI_EMBEDDING_MODEL``이 있으면 그 값을, 없으면 기본값을 사용합니다.

        Args:
            wiki_path: wiki 루트 경로 (호환성용, 사용되지 않음)

        Returns:
            WikiConfig 인스턴스
        """
        del wiki_path  # 호환성을 위해 받지만 사용하지 않음
        model = os.getenv("WIKI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip()
        if not model:
            model = DEFAULT_EMBEDDING_MODEL
        return cls(embedding_model=model)
