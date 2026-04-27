"""Domain type definitions.

타입 안정성을 위한 TypedDict 정의입니다.
dict[str, Any] 대신 구조화된 타입을 사용합니다.

사용 예:
    from wiki_search_mcp.core.types import FrontmatterDict, ConfidenceDict

    def parse_frontmatter(content: str) -> tuple[FrontmatterDict, str]:
        ...
"""

from __future__ import annotations

from typing import TypedDict


class ConfidenceFactorsDict(TypedDict, total=False):
    """Confidence 계산에 사용된 factor들.

    Attributes:
        tested: 테스트 여부
        production: 프로덕션 검증 여부
        sources: 출처 수준 ("primary" | "secondary")
        freshness: 최신성 ("current" | "recent")
    """

    tested: bool
    production: bool
    sources: str
    freshness: str


class ConfidenceDict(TypedDict):
    """4-Factor Confidence 점수.

    Attributes:
        level: 신뢰도 수준 ("high" | "medium" | "low")
        score: 점수 (0-100)
        factors: 계산에 사용된 factor들
    """

    level: str  # "high" | "medium" | "low"
    score: int  # 0-100
    factors: ConfidenceFactorsDict


class ConfidenceInputDict(TypedDict, total=False):
    """Frontmatter에서 읽어온 confidence 원본 데이터.

    Attributes:
        tested: 테스트 여부
        production: 프로덕션 검증 여부
        sources: 출처 수준
        freshness: 최신성
    """

    tested: bool
    production: bool
    sources: str
    freshness: str


class FrontmatterDict(TypedDict, total=False):
    """Markdown frontmatter 데이터.

    모든 필드가 선택적입니다.

    Attributes:
        title: 문서 제목
        state: 문서 상태 ("stable" | "draft" | "deprecated")
        tags: 태그 목록
        category: 카테고리
        confidence: 신뢰도 정보
        created: 생성일 (ISO 형식)
        updated: 수정일 (ISO 형식)
    """

    title: str
    state: str
    tags: list[str]
    category: str
    confidence: ConfidenceInputDict | str  # dict 또는 레거시 문자열
    created: str
    updated: str


class SearchResultDict(TypedDict):
    """검색 결과 항목.

    Attributes:
        path: 문서 경로
        title: 문서 제목
        score: 유사도 점수
        category: 카테고리
        tags: 태그 목록
        summary: 요약
    """

    path: str
    title: str
    score: float
    category: str
    tags: list[str]
    summary: str


class GraphNodeDict(TypedDict):
    """그래프 노드 데이터.

    Attributes:
        id: 노드 ID (경로)
        title: 문서 제목
        category: 카테고리
    """

    id: str
    title: str
    category: str


class GraphEdgeDict(TypedDict):
    """그래프 엣지 데이터.

    Attributes:
        source: 출발 노드 ID
        target: 도착 노드 ID
    """

    source: str
    target: str


class DocumentRecordDict(TypedDict):
    """LanceDB에 저장되는 문서 레코드.

    Attributes:
        id: 문서 ID (경로)
        path: 문서 경로
        title: 제목
        category: 카테고리
        tags: 태그 목록
        state: 상태
        confidence_level: 신뢰도 수준
        confidence_score: 신뢰도 점수
        summary: 요약
        created: 생성일
        updated: 수정일
        vector: 임베딩 벡터
    """

    id: str
    path: str
    title: str
    category: str
    tags: list[str]
    state: str
    confidence_level: str
    confidence_score: int
    summary: str
    created: str
    updated: str
    vector: list[float]
