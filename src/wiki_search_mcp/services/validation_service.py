"""Validation service.

Wiki 검증 유스케이스를 담당합니다.
frontmatter 필수 필드 누락, 깨진 wikilink 등을 감지합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from wiki_search_mcp.core.config import (
    MAX_DOCS_LIMIT,
    NO_FRONTMATTER_ERROR_RATIO,
    NO_FRONTMATTER_FIELD_THRESHOLD,
    PARTIAL_WARNING_RATIO,
)
from wiki_search_mcp.core.models import ValidationIssue, ValidationReport
from wiki_search_mcp.core.utils import normalize_document_path

if TYPE_CHECKING:
    from wiki_search_mcp.core.protocols import GraphRepository, VectorRepository


@dataclass(frozen=True)
class _FieldRule:
    """문서 frontmatter 필드 검증 규칙(선언적).

    규칙을 메서드 본문에 흩뿌리는 대신 한 테이블에 모아, 새 규칙 추가 시
    테이블에 한 줄만 더하면 되도록 한다.

    Attributes:
        issue_type: 누락 시 기록할 issue type(예: "missing_title"). stats 키와
            일치해야 통계에 집계된다. ``None`` 이면 issue 를 만들지 않고
            누락 카운트만 올린다(created/updated 처럼 통계 전용).
        message: issue 메시지.
        is_missing: doc 을 받아 "누락이면 True" 를 반환하는 술어.
    """

    issue_type: str | None
    message: str
    is_missing: Callable[[dict[str, Any]], bool]


def _title_missing(doc: dict[str, Any]) -> bool:
    """title 이 없거나 path/파일명과 동일하면 누락으로 간주."""
    path = doc["path"]
    title = doc.get("title", "")
    path_stem = path[:-3] if path.endswith(".md") else path
    return not title or title == path or title == path_stem


def _confidence_missing(doc: dict[str, Any]) -> bool:
    """confidence 점수 0 + 레벨 low 면 frontmatter 미작성으로 본다."""
    return (
        doc.get("confidence_score", 50) == 0
        and doc.get("confidence_level", "medium") == "low"
    )


# 필드 검증 규칙 테이블. 순서대로 평가하며, 새 규칙은 여기에 한 줄 추가하면 된다.
_FIELD_RULES: tuple[_FieldRule, ...] = (
    _FieldRule("missing_title", "title 필드 없음", _title_missing),
    _FieldRule("missing_state", "state 필드 없음", lambda d: not d.get("state", "")),
    _FieldRule("missing_tags", "tags 필드 없음", lambda d: not d.get("tags", [])),
    _FieldRule("missing_confidence", "confidence 필드 없음", _confidence_missing),
    # created/updated 는 통계(누락 카운트)에만 반영하고 issue 는 만들지 않는다.
    _FieldRule(None, "", lambda d: not d.get("created", "")),
    _FieldRule(None, "", lambda d: not d.get("updated", "")),
)


class ValidationService:
    """Wiki 검증 유스케이스 담당."""

    def __init__(
        self,
        vector_repository: "VectorRepository",
        graph_repository: "GraphRepository",
    ):
        """ValidationService 초기화.

        Args:
            vector_repository: 벡터 저장소
            graph_repository: 그래프 저장소
        """
        self._vector = vector_repository
        self._graph = graph_repository

    def validate(self) -> ValidationReport:
        """Wiki 인덱스 품질 검사.

        Returns:
            ValidationReport 객체
        """
        issues: list[ValidationIssue] = []
        stats = {
            "missing_title": 0,
            "missing_state": 0,
            "missing_tags": 0,
            "missing_confidence": 0,
            "missing_created": 0,
            "missing_updated": 0,
            "broken_links": 0,
        }
        summary = {"complete": 0, "partial": 0, "no_frontmatter": 0}

        if not self._vector.exists():
            return ValidationReport.create(
                status="error",
                total=0,
                issues=[
                    ValidationIssue.of(
                        "",
                        "no_index",
                        (
                            "Index not built yet. The server is auto-indexing in "
                            "the background; retry shortly. If this persists, run "
                            "`wiki-search-mcp index <wiki-path> --full` once."
                        ),
                    )
                ],
                stats=stats,
                summary=summary,
            )

        all_docs = self._vector.find_all(MAX_DOCS_LIMIT)
        all_paths = set(d["path"] for d in all_docs)

        for doc in all_docs:
            doc_issues, missing_count = self._check_document(doc)
            issues.extend(doc_issues)

            # 필드별 통계 업데이트
            for issue in doc_issues:
                if issue.type in stats:
                    stats[issue.type] += 1

            # 요약 분류
            if missing_count == 0:
                summary["complete"] += 1
            elif missing_count >= NO_FRONTMATTER_FIELD_THRESHOLD:
                summary["no_frontmatter"] += 1
            else:
                summary["partial"] += 1

        # 깨진 wikilink 검사
        broken_link_issues = self._check_broken_links(all_paths)
        issues.extend(broken_link_issues)
        stats["broken_links"] = len(broken_link_issues)

        # 상태 결정
        total = len(all_docs)
        status = self._determine_status(stats, summary, total)

        return ValidationReport.create(
            status=status,
            total=total,
            issues=issues,
            stats=stats,
            summary=summary,
        )

    def _check_document(
        self, doc: dict[str, Any]
    ) -> tuple[list[ValidationIssue], int]:
        """단일 문서 검사.

        Returns:
            (이슈 리스트, 누락 필드 수)
        """
        issues: list[ValidationIssue] = []
        path = doc["path"]
        missing_count = 0

        # 선언적 규칙 테이블 순회. issue_type 이 None 인 규칙(created/updated)은
        # 통계 누락 카운트만 올리고 issue 는 만들지 않는다.
        for rule in _FIELD_RULES:
            if rule.is_missing(doc):
                missing_count += 1
                if rule.issue_type is not None:
                    issues.append(
                        ValidationIssue.of(path, rule.issue_type, rule.message)
                    )

        return issues, missing_count

    def _check_broken_links(
        self, all_paths: set[str]
    ) -> list[ValidationIssue]:
        """깨진 wikilink 검사."""
        issues: list[ValidationIssue] = []

        for edge in self._graph.get_edges():
            target = edge["target"]
            target_with_md, target_without_md = normalize_document_path(target)

            if target_with_md not in all_paths and target_without_md not in all_paths:
                issues.append(
                    ValidationIssue.of(
                        edge["source"],
                        "broken_link",
                        f"[[{target}]] 링크 대상 없음",
                    )
                )

        return issues

    def _determine_status(
        self, stats: dict[str, int], summary: dict[str, int], total: int
    ) -> str:
        """검증 상태 결정."""
        if total == 0:
            return "error"

        if summary["no_frontmatter"] > total * NO_FRONTMATTER_ERROR_RATIO:
            return "error"

        if stats["broken_links"] > 0 or summary["partial"] > total * PARTIAL_WARNING_RATIO:
            return "warning"

        return "valid"
