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
        categories: 감지된 카테고리 이름 (정렬됨). staging 폴더는 제외됨.
        detected_at: ISO 8601 감지 시각
        staging_folders: inbox 변형 폴더(``is_staging_folder`` 매치) 이름. 정렬됨.
            카테고리가 아니라 자동 분류 대상 영역. Claude에게 "여기 던지면 자동 분류"
            대상임을 알리는 용도.
    """

    mode: CategoryMode
    categories: tuple[str, ...]
    detected_at: str
    staging_folders: tuple[str, ...] = ()

    @classmethod
    def of(
        cls,
        mode: CategoryMode,
        categories: list[str] | tuple[str, ...],
        detected_at: str,
        staging_folders: list[str] | tuple[str, ...] | None = None,
    ) -> CategoryListing:
        """팩토리 메서드."""
        return cls(
            mode=mode,
            categories=tuple(categories),
            detected_at=detected_at,
            staging_folders=tuple(staging_folders) if staging_folders else (),
        )

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환."""
        return {
            "mode": self.mode,
            "categories": list(self.categories),
            "detected_at": self.detected_at,
            "staging_folders": list(self.staging_folders),
        }


PendingReason = Literal["no_frontmatter", "no_category", "not_indexed", "in_staging"]


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


@dataclass(frozen=True)
class SubfolderGroup:
    """평면 프로젝트 폴더 내에서 묶을 수 있는 한 서브폴더 후보.

    Attributes:
        name: 제안 서브폴더 이름(공통 태그/키워드 유래).
        files: 이 그룹에 속하는 상대 경로 목록(폴더 기준이 아닌 pages 기준).
        signal: 그룹을 형성한 공통 신호(태그/키워드 등, 사람이 읽기 위함).
    """

    name: str
    files: tuple[str, ...]
    signal: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "files": list(self.files), "signal": self.signal}


@dataclass(frozen=True)
class SubfolderSuggestion:
    """한 프로젝트(또는 카테고리) 폴더의 서브폴더 계층화 제안.

    MCP read-only 원칙을 따라 제안만 반환한다. 실제 파일 이동/폴더 생성은
    Claude(또는 사용자)가 일반 도구로 수행한다.

    Attributes:
        folder: 대상 폴더 상대 경로(pages 기준).
        file_count: 폴더 직계 .md 파일 수.
        groups: 제안된 서브폴더 그룹들(크기 내림차순).
        unclassified: 어느 그룹에도 들지 못한 파일들(상대 경로).
        reasoning: 제안 근거(사람이 읽기 위함).
    """

    folder: str
    file_count: int
    groups: tuple[SubfolderGroup, ...] = ()
    unclassified: tuple[str, ...] = ()
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "folder": self.folder,
            "file_count": self.file_count,
            "groups": [g.to_dict() for g in self.groups],
            "unclassified": list(self.unclassified),
            "reasoning": self.reasoning,
        }


@dataclass(frozen=True)
class HierarchizationPlan:
    """한 폴더에 대한 계층화 실행 계획.

    ``SubfolderSuggestion`` (휴리스틱 제안)을 LLM 이 검증/정제한 결과로,
    confidence 가 임계 이상이면 daemon 이 자동 적용하고 미만이면 pending
    큐에 승인 대기로 기록된다 (기존 분류 파이프라인과 동일 정책).

    Attributes:
        folder: 대상 폴더 상대 경로(pages 기준).
        groups: 확정 그룹들 — ``name`` 이 생성될 서브폴더 이름.
        unclassified: 이동하지 않고 평면에 남길 파일들.
        confidence: 0.0-1.0. LLM 검증 실패/미사용 시 0.0 (자동 적용 안 됨).
        reasoning: 계획 근거.
        provider: 검증에 사용한 provider 식별자 (휴리스틱 단독이면 "heuristic").
    """

    folder: str
    groups: tuple[SubfolderGroup, ...] = ()
    unclassified: tuple[str, ...] = ()
    confidence: float = 0.0
    reasoning: str = ""
    provider: str = "heuristic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "folder": self.folder,
            "groups": [g.to_dict() for g in self.groups],
            "unclassified": list(self.unclassified),
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "provider": self.provider,
        }


@dataclass(frozen=True)
class FolderHealth:
    """평면 누적으로 계층화가 권장되는 폴더 한 건.

    Attributes:
        path: 폴더 상대 경로(pages 기준).
        file_count: 폴더 직계 .md 파일 수.
        has_subfolders: 이미 서브폴더가 있는지 여부.
    """

    path: str
    file_count: int
    has_subfolders: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "file_count": self.file_count,
            "has_subfolders": self.has_subfolders,
        }


@dataclass(frozen=True)
class HealthReport:
    """Wiki 구조 건강 진단(read-only).

    Attributes:
        needs_hierarchization: 평면 누적으로 서브폴더 분할이 권장되는 폴더들
            (file_count 내림차순).
        empty_folders: 파일이 0개인 폴더들의 상대 경로.
        reasoning: 진단 요약(사람이 읽기 위함).
    """

    needs_hierarchization: tuple[FolderHealth, ...] = ()
    empty_folders: tuple[str, ...] = ()
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "needs_hierarchization": [
                f.to_dict() for f in self.needs_hierarchization
            ],
            "empty_folders": list(self.empty_folders),
            "reasoning": self.reasoning,
        }


@dataclass(frozen=True)
class FilenameRename:
    """파일명 정규화 제안 한 건(날짜 포맷 표준화).

    Attributes:
        current: 현재 상대 경로.
        suggested: 제안 상대 경로(같은 폴더 내, 표준 날짜 포맷).
        reason: 제안 근거(감지된 날짜 패턴 등).
    """

    current: str
    suggested: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "suggested": self.suggested,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FilenameNormalization:
    """파일명 정규화 제안 모음(read-only).

    Attributes:
        candidates: 정규화 제안 목록.
        reasoning: 요약.
    """

    candidates: tuple[FilenameRename, ...] = ()
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "reasoning": self.reasoning,
        }


# =============================================================================
# v0.2.0: Daemon 자동 분류 모델
# =============================================================================


@dataclass(frozen=True)
class ClassificationDecision:
    """LLM이 산출한 분류 결정.

    Attributes:
        path: 대상 파일 상대 경로
        category: 결정된 카테고리
        subcategory: 결정된 서브카테고리(예: 프로젝트명). None 이면 1-depth.
            제공된 경우 파일은 ``<category>/<subcategory>/<basename>`` 으로 이동한다.
        tags: 결정된 태그 (최대 5개 권장)
        confidence: 0.0-1.0. ``daemon.confidence_threshold`` 이상이면 자동 적용
        reasoning: LLM의 설명 (디버깅/로그용, 250자 내외 권장)
        provider: 호출한 provider 식별자 (예: ``"claude-code:haiku"``)
        raw_response: LLM 원본 응답 텍스트 (디버깅용, 200자 truncate)
    """

    path: str
    category: str
    tags: tuple[str, ...]
    confidence: float
    reasoning: str
    provider: str
    raw_response: str = ""
    subcategory: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "category": self.category,
            "subcategory": self.subcategory,
            "tags": list(self.tags),
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "provider": self.provider,
            "raw_response": self.raw_response,
        }


@dataclass(frozen=True)
class AppliedRecord:
    """daemon이 적용한 자동 분류의 audit/rollback 레코드.

    Attributes:
        path_before: 적용 전 wiki 상대 경로
        path_after: 적용 후 (카테고리 폴더 이동 발생 시 다름)
        frontmatter_before: 적용 전 frontmatter dict (없으면 ``{}``)
        frontmatter_after: 적용 후 frontmatter dict
        decision: ClassificationDecision.to_dict() 결과
        applied_at: ISO 8601 UTC 타임스탬프
        sha256_before: 적용 전 본문 전체의 SHA-256 (충돌 감지/검증용)
    """

    path_before: str
    path_after: str
    frontmatter_before: dict[str, Any]
    frontmatter_after: dict[str, Any]
    decision: dict[str, Any]
    applied_at: str
    sha256_before: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_before": self.path_before,
            "path_after": self.path_after,
            "frontmatter_before": dict(self.frontmatter_before),
            "frontmatter_after": dict(self.frontmatter_after),
            "decision": dict(self.decision),
            "applied_at": self.applied_at,
            "sha256_before": self.sha256_before,
        }
