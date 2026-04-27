"""Infrastructure layer.

외부 시스템(DB, 모델, 파일 시스템)과의 통합을 담당합니다.

Subpackages:
    embedding: 임베딩 모델 관리
    storage: 벡터/키워드/그래프 저장소
    cache: 쿼리 캐시
    indexing: 문서 인덱싱
    watcher: 파일 변경 감시
"""

from wiki_search_mcp.infrastructure.indexing import WikiIndexer
from wiki_search_mcp.infrastructure.watcher import WikiWatcher

__all__ = [
    "WikiIndexer",
    "WikiWatcher",
]
