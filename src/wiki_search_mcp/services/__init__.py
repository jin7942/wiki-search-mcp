"""Application services layer.

유스케이스를 구현하는 서비스들입니다.
각 서비스는 단일 책임을 가지며, Protocol 기반으로 Repository를 주입받습니다.

Services:
    SearchService: 검색 유스케이스
    DocumentService: 문서 CRUD 유스케이스
    GraphService: 그래프 연산 유스케이스
    ValidationService: Wiki 검증 유스케이스
    StatsService: 통계 유스케이스
    AutoTagger: 자동 태그 추출
    QueryExpander: 쿼리 확장 (동의어)
    CategoryService: 카테고리 자동 감지
    ClassificationService: 미분류 파일 감지 + 분류 추천
"""

# Lazy imports to avoid import errors when dependencies are missing


def __getattr__(name: str):
    """Lazy import to avoid circular imports and missing dependencies."""
    if name == "SearchService":
        from .search_service import SearchService

        return SearchService
    if name == "DocumentService":
        from .document_service import DocumentService

        return DocumentService
    if name == "GraphService":
        from .graph_service import GraphService

        return GraphService
    if name == "ValidationService":
        from .validation_service import ValidationService

        return ValidationService
    if name == "StatsService":
        from .stats_service import StatsService

        return StatsService
    if name == "AutoTagger":
        from .tagger_service import AutoTagger

        return AutoTagger
    if name == "QueryExpander":
        from .expander_service import QueryExpander

        return QueryExpander
    if name == "CategoryService":
        from .category_service import CategoryService

        return CategoryService
    if name == "ClassificationService":
        from .classification_service import ClassificationService

        return ClassificationService
    if name == "HierarchizationService":
        from .hierarchization_service import HierarchizationService

        return HierarchizationService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "SearchService",
    "DocumentService",
    "GraphService",
    "ValidationService",
    "StatsService",
    "AutoTagger",
    "QueryExpander",
    "CategoryService",
    "ClassificationService",
    "HierarchizationService",
]
