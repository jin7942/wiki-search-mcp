"""Storage infrastructure.

데이터 저장소 구현체들을 제공합니다.

Modules:
    vector_store: LanceDB 벡터 저장소
    bm25_store: BM25 키워드 인덱스
    graph_store: wikilink 그래프 저장소
    meta_store: 메타데이터 저장소
"""

# Lazy imports to avoid import errors when dependencies are missing


def __getattr__(name: str):
    """Lazy import to avoid import errors when dependencies are missing."""
    if name == "LanceVectorStore":
        from .vector_store import LanceVectorStore

        return LanceVectorStore
    if name == "BM25IndexStore":
        from .bm25_store import BM25IndexStore

        return BM25IndexStore
    if name == "JsonGraphStore":
        from .graph_store import JsonGraphStore

        return JsonGraphStore
    if name == "JsonMetaStore":
        from .meta_store import JsonMetaStore

        return JsonMetaStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["LanceVectorStore", "BM25IndexStore", "JsonGraphStore", "JsonMetaStore"]
