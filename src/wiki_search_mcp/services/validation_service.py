"""Validation service.

Wiki 검증 유스케이스를 담당합니다.
frontmatter 필수 필드 누락, 깨진 wikilink 등을 감지합니다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
                        "", "no_index", "Index not found. Run wiki_reindex() first."
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

        # title 검사 (path와 동일하면 누락으로 간주)
        title = doc.get("title", "")
        path_stem = path[:-3] if path.endswith(".md") else path
        if not title or title == path or title == path_stem:
            issues.append(
                ValidationIssue.of(path, "missing_title", "title 필드 없음")
            )
            missing_count += 1

        # state 검사
        state = doc.get("state", "")
        if not state:
            issues.append(
                ValidationIssue.of(path, "missing_state", "state 필드 없음")
            )
            missing_count += 1

        # tags 검사
        tags = doc.get("tags", [])
        if not tags:
            issues.append(
                ValidationIssue.of(path, "missing_tags", "tags 필드 없음")
            )
            missing_count += 1

        # confidence 검사
        confidence_score = doc.get("confidence_score", 50)
        confidence_level = doc.get("confidence_level", "medium")
        if confidence_score == 0 and confidence_level == "low":
            issues.append(
                ValidationIssue.of(path, "missing_confidence", "confidence 필드 없음")
            )
            missing_count += 1

        # created/updated 검사 (통계용, 이슈는 생성 안 함)
        if not doc.get("created", ""):
            missing_count += 1
        if not doc.get("updated", ""):
            missing_count += 1

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
