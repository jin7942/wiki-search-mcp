"""Domain models.

불변 데이터 클래스(frozen=True)로 정의된 도메인 모델입니다.

패턴 적용:
- VO (Value Object): 값으로 비교, 불변 (Confidence, ValidationIssue)
- Entity: 식별자로 비교 (Document - path가 ID)
- Aggregate Root: 관련 엔티티 그룹 관리 (ValidationReport)
- Factory Method: of(), from_dict(), create() 정적 팩토리
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


# =============================================================================
# Value Objects (불변, 값으로 비교)
# =============================================================================


@dataclass(frozen=True)
class Confidence:
    """신뢰도 VO.

    Attributes:
        level: 신뢰도 레벨 ("high", "medium", "low")
        score: 신뢰도 점수 (0-100)
        factors: 신뢰도 결정 요인 (불변 튜플)
    """

    level: str
    score: int
    factors: tuple[tuple[str, Any], ...] = ()

    @classmethod
    def of(
        cls,
        level: str,
        score: int,
        factors: dict[str, Any] | None = None,
    ) -> Confidence:
        """팩토리 메서드: 신뢰도 생성."""
        factor_tuple = tuple(factors.items()) if factors else ()
        return cls(level=level, score=score, factors=factor_tuple)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Confidence:
        """팩토리 메서드: dict에서 생성."""
        return cls.of(
            level=data.get("level", "low"),
            score=data.get("score", 0),
            factors=data.get("factors"),
        )

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환."""
        return {
            "level": self.level,
            "score": self.score,
            "factors": dict(self.factors) if self.factors else {},
        }


@dataclass(frozen=True)
class ValidationIssue:
    """검증 이슈 VO.

    Attributes:
        path: 문제가 발생한 문서 경로
        type: 이슈 유형 ("missing_field", "broken_link", "low_confidence")
        message: 이슈 설명
    """

    path: str
    type: str
    message: str

    @classmethod
    def of(cls, path: str, issue_type: str, message: str) -> ValidationIssue:
        """팩토리 메서드: 검증 이슈 생성."""
        return cls(path=path, type=issue_type, message=message)

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환."""
        return {"path": self.path, "type": self.type, "message": self.message}


# =============================================================================
# Entities (식별자로 비교, path가 ID)
# =============================================================================


@dataclass(frozen=True)
class Document:
    """문서 엔티티.

    Attributes:
        path: 문서 경로 (ID)
        title: 문서 제목
        category: 카테고리
        tags: 태그 목록 (불변 튜플)
        summary: 요약
        state: 상태 ("draft", "review", "stable", "deprecated", "archived")
        confidence: 신뢰도 정보
        created: 생성 일시 (ISO 형식)
        updated: 수정 일시 (ISO 형식)
    """

    path: str
    title: str
    category: str
    tags: tuple[str, ...]
    summary: str
    state: str
    confidence: Confidence
    created: str = ""
    updated: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Document:
        """팩토리 메서드: dict에서 Document 생성."""
        return cls(
            path=data["path"],
            title=data.get("title", ""),
            category=data.get("category", "uncategorized"),
            tags=tuple(data.get("tags", [])),
            summary=data.get("summary", ""),
            state=data.get("state", "stable"),
            confidence=Confidence.from_dict(
                {
                    "level": data.get("confidence_level", "low"),
                    "score": data.get("confidence_score", 0),
                }
            ),
            created=data.get("created", ""),
            updated=data.get("updated", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환."""
        return {
            "path": self.path,
            "title": self.title,
            "category": self.category,
            "tags": list(self.tags),
            "summary": self.summary,
            "state": self.state,
            "confidence": self.confidence.to_dict(),
            "created": self.created,
            "updated": self.updated,
        }


# =============================================================================
# Search DTOs
# =============================================================================


@dataclass(frozen=True)
class SearchResult:
    """검색 결과 VO.

    Attributes:
        document: 검색된 문서
        similarity: 유사도 점수 (0.0 ~ 1.0)
        related: 관련 문서 경로 목록
        warning: 경고 메시지 (deprecated 등)
    """

    document: Document
    similarity: float
    related: tuple[str, ...] = ()
    warning: str | None = None

    @classmethod
    def of(
        cls,
        document: Document,
        similarity: float,
        related: list[str] | None = None,
        warning: str | None = None,
    ) -> SearchResult:
        """팩토리 메서드: 검색 결과 생성."""
        return cls(
            document=document,
            similarity=similarity,
            related=tuple(related or []),
            warning=warning,
        )

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환 (기존 API 호환)."""
        result = self.document.to_dict()
        result["similarity"] = self.similarity
        result["related"] = list(self.related)
        if self.warning:
            result["warning"] = self.warning
        return result


@dataclass(frozen=True)
class SearchFilters:
    """검색 필터 VO.

    Attributes:
        include_states: 포함할 상태 목록
        category: 카테고리 필터
        tags: 태그 필터 (OR 조건)
        confidence_min: 최소 신뢰도 점수
    """

    include_states: tuple[str, ...] = ("draft", "review", "stable", "deprecated")
    category: str | None = None
    tags: tuple[str, ...] | None = None
    confidence_min: int = 0

    @classmethod
    def of(
        cls,
        include_states: list[str] | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        confidence_min: int = 0,
    ) -> SearchFilters:
        """팩토리 메서드: 검색 필터 생성."""
        states = tuple(include_states) if include_states else cls.include_states
        return cls(
            include_states=states,
            category=category,
            tags=tuple(tags) if tags else None,
            confidence_min=confidence_min,
        )


@dataclass(frozen=True)
class SearchResponse:
    """검색 응답 VO.

    Attributes:
        results: 검색 결과 목록
        total_pages: 전체 페이지 수
        query: 검색 쿼리
        mode: 검색 모드 ("hybrid", "vector", "keyword")
        error: 에러 메시지 (있을 경우)
    """

    results: tuple[SearchResult, ...]
    total_pages: int
    query: str
    mode: str
    error: str | None = None

    @classmethod
    def of(
        cls,
        results: list[SearchResult],
        total_pages: int,
        query: str,
        mode: str,
        error: str | None = None,
    ) -> SearchResponse:
        """팩토리 메서드: 검색 응답 생성."""
        return cls(
            results=tuple(results),
            total_pages=total_pages,
            query=query,
            mode=mode,
            error=error,
        )

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환 (기존 API 호환)."""
        result: dict[str, Any] = {
            "results": [r.to_dict() for r in self.results],
            "total_pages": self.total_pages,
            "query": self.query,
            "mode": self.mode,
        }
        if self.error:
            result["error"] = self.error
        return result


# =============================================================================
# Aggregate Roots
# =============================================================================


@dataclass(frozen=True)
class ValidationReport:
    """검증 리포트 (Aggregate Root).

    Attributes:
        status: 상태 ("valid", "warning", "error")
        total: 전체 문서 수
        issues: 발견된 이슈 목록
        stats: 이슈 유형별 통계
        summary: 문서 품질 요약
    """

    status: str
    total: int
    issues: tuple[ValidationIssue, ...]
    stats: tuple[tuple[str, int], ...]
    summary: tuple[tuple[str, int], ...]

    @classmethod
    def create(
        cls,
        status: str,
        total: int,
        issues: list[ValidationIssue],
        stats: dict[str, int],
        summary: dict[str, int],
    ) -> ValidationReport:
        """팩토리 메서드: 검증 리포트 생성."""
        return cls(
            status=status,
            total=total,
            issues=tuple(issues),
            stats=tuple(stats.items()),
            summary=tuple(summary.items()),
        )

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환 (기존 API 호환)."""
        return {
            "status": self.status,
            "total": self.total,
            "issues": [i.to_dict() for i in self.issues],
            "stats": dict(self.stats),
            "summary": dict(self.summary),
        }


@dataclass(frozen=True)
class WikiStats:
    """Wiki 통계 VO.

    Attributes:
        total_pages: 전체 페이지 수
        by_category: 카테고리별 문서 수
        by_state: 상태별 문서 수
        by_confidence: 신뢰도별 문서 수
        last_indexed: 마지막 인덱싱 시간
    """

    total_pages: int
    by_category: tuple[tuple[str, int], ...]
    by_state: tuple[tuple[str, int], ...]
    by_confidence: tuple[tuple[str, int], ...]
    last_indexed: str | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WikiStats:
        """팩토리 메서드: dict에서 생성."""
        return cls(
            total_pages=data.get("total_pages", 0),
            by_category=tuple(data.get("by_category", {}).items()),
            by_state=tuple(data.get("by_state", {}).items()),
            by_confidence=tuple(data.get("by_confidence", {}).items()),
            last_indexed=data.get("last_indexed"),
        )

    @classmethod
    def create(
        cls,
        total_pages: int,
        by_category: dict[str, int],
        by_state: dict[str, int],
        by_confidence: dict[str, int],
        last_indexed: str | None,
    ) -> WikiStats:
        """팩토리 메서드: 통계 생성."""
        return cls(
            total_pages=total_pages,
            by_category=tuple(by_category.items()),
            by_state=tuple(by_state.items()),
            by_confidence=tuple(by_confidence.items()),
            last_indexed=last_indexed,
        )

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환 (기존 API 호환)."""
        return {
            "total_pages": self.total_pages,
            "by_category": dict(self.by_category),
            "by_state": dict(self.by_state),
            "by_confidence": dict(self.by_confidence),
            "last_indexed": self.last_indexed,
        }


# =============================================================================
# 자동 분류 / 카테고리
# =============================================================================


CategoryMode = Literal["folder", "empty"]


@dataclass(frozen=True)
class CategoryListing:
    """현재 wiki에서 사용 가능한 카테고리 목록.

    Attributes:
        mode: 'folder'는 디렉토리 자동 감지, 'empty'는 카테고리 없음 (AI 폴백 신호)
        categories: 감지된 카테고리 이름 (정렬됨)
        detected_at: ISO 8601 감지 시각
    """

    mode: CategoryMode
    categories: tuple[str, ...]
    detected_at: str

    @classmethod
    def of(
        cls, mode: CategoryMode, categories: list[str] | tuple[str, ...], detected_at: str
    ) -> CategoryListing:
        """팩토리 메서드."""
        return cls(mode=mode, categories=tuple(categories), detected_at=detected_at)

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환."""
        return {
            "mode": self.mode,
            "categories": list(self.categories),
            "detected_at": self.detected_at,
        }


PendingReason = Literal["no_frontmatter", "no_category", "not_indexed"]


@dataclass(frozen=True)
class PendingItem:
    """미분류 / 정리 대기 파일.

    Attributes:
        path: wiki 루트 기준 상대 경로
        reason: 분류 대기 사유
        mtime: 파일 수정 시각 (ISO 8601, 옵션)
    """

    path: str
    reason: PendingReason
    mtime: str | None = None

    @classmethod
    def of(cls, path: str, reason: PendingReason, mtime: str | None = None) -> PendingItem:
        """팩토리 메서드."""
        return cls(path=path, reason=reason, mtime=mtime)

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환."""
        return {"path": self.path, "reason": self.reason, "mtime": self.mtime}


@dataclass(frozen=True)
class ClassificationSuggestion:
    """단일 파일에 대한 분류 추천.

    Attributes:
        path: 대상 파일 상대 경로
        category_candidates: 추천 카테고리 (점수 내림차순)
        tag_candidates: 추천 태그 (빈도 내림차순)
        similar_paths: 유사 문서 경로 (참고용)
        reasoning: 추천 근거 설명 (사람이 읽기 위함)
    """

    path: str
    category_candidates: tuple[str, ...] = ()
    tag_candidates: tuple[str, ...] = ()
    similar_paths: tuple[str, ...] = ()
    reasoning: str = ""

    @classmethod
    def of(
        cls,
        path: str,
        category_candidates: list[str] | tuple[str, ...] = (),
        tag_candidates: list[str] | tuple[str, ...] = (),
        similar_paths: list[str] | tuple[str, ...] = (),
        reasoning: str = "",
    ) -> ClassificationSuggestion:
        """팩토리 메서드."""
        return cls(
            path=path,
            category_candidates=tuple(category_candidates),
            tag_candidates=tuple(tag_candidates),
            similar_paths=tuple(similar_paths),
            reasoning=reasoning,
        )

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환."""
        return {
            "path": self.path,
            "category_candidates": list(self.category_candidates),
            "tag_candidates": list(self.tag_candidates),
            "similar_paths": list(self.similar_paths),
            "reasoning": self.reasoning,
        }
