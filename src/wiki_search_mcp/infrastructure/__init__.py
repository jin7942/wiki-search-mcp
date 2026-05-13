"""Infrastructure layer.

외부 시스템(DB, 모델, 파일 시스템)과의 통합을 담당합니다.

Subpackages:
    embedding: 임베딩 모델 관리
    storage: 벡터/키워드/그래프 저장소
    cache: 쿼리 캐시
    indexing: 문서 인덱싱
    watcher: 파일 변경 감시
    daemon: 자동 분류 백그라운드 데몬 (v0.2.0)
    frontmatter: 원자적 frontmatter writer (v0.2.0)
    jsonl: 감사 로그 (v0.2.0)

이 ``__init__``은 무거운 의존성(sentence_transformers / torch)을 즉시 import하지 않습니다.
``WikiIndexer`` / ``WikiWatcher``는 lazy attribute로 노출되어, 실제 접근 시점에만 로드됩니다.
``--version`` / ``--help`` / ``daemon status`` 같은 가벼운 CLI 명령이 ML 의존성 로드 비용 없이
즉시 실행되도록 하기 위함입니다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from wiki_search_mcp.infrastructure.indexing import WikiIndexer
    from wiki_search_mcp.infrastructure.watcher import WikiWatcher

__all__ = ["WikiIndexer", "WikiWatcher"]


def __getattr__(name: str) -> Any:
    """PEP 562 lazy import — 호환성 유지 + 무거운 모듈 지연 로드."""
    if name == "WikiIndexer":
        from wiki_search_mcp.infrastructure.indexing import WikiIndexer

        return WikiIndexer
    if name == "WikiWatcher":
        from wiki_search_mcp.infrastructure.watcher import WikiWatcher

        return WikiWatcher
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
