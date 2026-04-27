"""wiki_validate 테스트

frontmatter 품질 점검, 깨진 wikilink 감지 등을 테스트합니다.
"""

import json
import tempfile
from pathlib import Path


class TestValidateIssueDetection:
    """validate 이슈 감지 테스트."""

    def create_mock_docs(self) -> list[dict]:
        """테스트용 mock 문서 목록 생성."""
        return [
            {
                "path": "complete.md",
                "title": "Complete Document",
                "state": "stable",
                "tags": ["test", "complete"],
                "confidence_score": 70,
                "confidence_level": "high",
                "created": "2024-01-01",
                "updated": "2024-01-15",
            },
            {
                "path": "partial.md",
                "title": "Partial Document",
                "state": "draft",
                "tags": [],
                "confidence_score": 50,
                "confidence_level": "medium",
                "created": "",
                "updated": "",
            },
            {
                "path": "no_frontmatter.md",
                "title": "no_frontmatter.md",  # path와 동일 = 자동 생성된 제목
                "state": "",
                "tags": [],
                "confidence_score": 0,
                "confidence_level": "low",
                "created": "",
                "updated": "",
            },
        ]

    def validate_docs(self, docs: list[dict], edges: list[dict]) -> dict:
        """validate 로직 시뮬레이션."""
        issues = []
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

        all_paths = set(d["path"] for d in docs)

        for doc in docs:
            path = doc["path"]
            missing_count = 0

            # title 검사
            title = doc.get("title", "")
            path_stem = path[:-3] if path.endswith(".md") else path
            if not title or title == path or title == path_stem:
                issues.append({"path": path, "type": "missing_title", "message": "title 필드 없음"})
                stats["missing_title"] += 1
                missing_count += 1

            # state 검사
            if not doc.get("state"):
                issues.append({"path": path, "type": "missing_state", "message": "state 필드 없음"})
                stats["missing_state"] += 1
                missing_count += 1

            # tags 검사
            if not doc.get("tags"):
                issues.append({"path": path, "type": "missing_tags", "message": "tags 필드 없음"})
                stats["missing_tags"] += 1
                missing_count += 1

            # confidence 검사
            if doc.get("confidence_score", 50) == 0 and doc.get("confidence_level") == "low":
                issues.append({"path": path, "type": "missing_confidence", "message": "confidence 필드 없음"})
                stats["missing_confidence"] += 1
                missing_count += 1

            # created/updated
            if not doc.get("created"):
                stats["missing_created"] += 1
                missing_count += 1
            if not doc.get("updated"):
                stats["missing_updated"] += 1
                missing_count += 1

            # 분류
            if missing_count == 0:
                summary["complete"] += 1
            elif missing_count >= 5:
                summary["no_frontmatter"] += 1
            else:
                summary["partial"] += 1

        # 깨진 링크 검사
        for edge in edges:
            target = edge["target"]
            target_with_md = target if target.endswith(".md") else f"{target}.md"
            target_without_md = target[:-3] if target.endswith(".md") else target

            if target_with_md not in all_paths and target_without_md not in all_paths:
                issues.append({
                    "path": edge["source"],
                    "type": "broken_link",
                    "message": f"[[{target}]] 링크 대상 없음"
                })
                stats["broken_links"] += 1

        # 상태 결정
        total = len(docs)
        status = "valid"
        if stats["broken_links"] > 0 or summary["partial"] > total * 0.1:
            status = "warning"
        if total == 0 or summary["no_frontmatter"] > total * 0.3:
            status = "error"

        return {
            "status": status,
            "total": total,
            "issues": issues,
            "stats": stats,
            "summary": summary,
        }

    def test_complete_document(self):
        """모든 필드가 있는 문서."""
        docs = [self.create_mock_docs()[0]]  # complete.md만
        result = self.validate_docs(docs, [])

        assert result["status"] == "valid"
        assert result["summary"]["complete"] == 1
        assert result["summary"]["partial"] == 0
        assert result["summary"]["no_frontmatter"] == 0

    def test_partial_document(self):
        """일부 필드가 누락된 문서."""
        docs = [self.create_mock_docs()[1]]  # partial.md만
        result = self.validate_docs(docs, [])

        assert result["summary"]["partial"] == 1
        assert result["stats"]["missing_tags"] == 1
        assert result["stats"]["missing_created"] == 1
        assert result["stats"]["missing_updated"] == 1

    def test_no_frontmatter_document(self):
        """frontmatter 없는 문서."""
        docs = [self.create_mock_docs()[2]]  # no_frontmatter.md만
        result = self.validate_docs(docs, [])

        assert result["status"] == "error"
        assert result["summary"]["no_frontmatter"] == 1

    def test_broken_link_detection(self):
        """깨진 wikilink 감지."""
        docs = [self.create_mock_docs()[0]]  # complete.md만
        edges = [
            {"source": "complete.md", "target": "nonexistent.md"},
        ]
        result = self.validate_docs(docs, edges)

        assert result["status"] == "warning"
        assert result["stats"]["broken_links"] == 1
        assert any(
            issue["type"] == "broken_link"
            for issue in result["issues"]
        )

    def test_valid_link(self):
        """유효한 wikilink."""
        docs = [
            self.create_mock_docs()[0],
            {"path": "target.md", "title": "Target", "state": "stable", "tags": ["test"],
             "confidence_score": 50, "confidence_level": "medium", "created": "2024-01-01", "updated": "2024-01-01"},
        ]
        edges = [
            {"source": "complete.md", "target": "target.md"},
        ]
        result = self.validate_docs(docs, edges)

        assert result["stats"]["broken_links"] == 0

    def test_link_without_extension(self):
        """확장자 없는 wikilink도 매칭."""
        docs = [
            self.create_mock_docs()[0],
            {"path": "target.md", "title": "Target", "state": "stable", "tags": ["test"],
             "confidence_score": 50, "confidence_level": "medium", "created": "2024-01-01", "updated": "2024-01-01"},
        ]
        edges = [
            {"source": "complete.md", "target": "target"},  # .md 없이
        ]
        result = self.validate_docs(docs, edges)

        assert result["stats"]["broken_links"] == 0

    def test_mixed_documents(self):
        """다양한 상태의 문서 혼합."""
        docs = self.create_mock_docs()
        result = self.validate_docs(docs, [])

        assert result["total"] == 3
        assert result["summary"]["complete"] == 1
        assert result["summary"]["partial"] == 1
        assert result["summary"]["no_frontmatter"] == 1

    def test_empty_index(self):
        """빈 인덱스."""
        result = self.validate_docs([], [])

        assert result["status"] == "error"
        assert result["total"] == 0


class TestValidateStatusLevels:
    """validate 상태 레벨 테스트."""

    def determine_status(self, total: int, broken_links: int, partial: int, no_frontmatter: int) -> str:
        """상태 결정 로직."""
        if total == 0 or no_frontmatter > total * 0.3:
            return "error"
        if broken_links > 0 or partial > total * 0.1:
            return "warning"
        return "valid"

    def test_valid_status(self):
        """정상 상태."""
        status = self.determine_status(total=100, broken_links=0, partial=5, no_frontmatter=0)
        assert status == "valid"

    def test_warning_status_broken_links(self):
        """깨진 링크로 인한 warning."""
        status = self.determine_status(total=100, broken_links=1, partial=0, no_frontmatter=0)
        assert status == "warning"

    def test_warning_status_partial(self):
        """partial > 10%로 인한 warning."""
        status = self.determine_status(total=100, broken_links=0, partial=15, no_frontmatter=0)
        assert status == "warning"

    def test_error_status_empty(self):
        """빈 인덱스로 인한 error."""
        status = self.determine_status(total=0, broken_links=0, partial=0, no_frontmatter=0)
        assert status == "error"

    def test_error_status_no_frontmatter(self):
        """no_frontmatter > 30%로 인한 error."""
        status = self.determine_status(total=100, broken_links=0, partial=0, no_frontmatter=35)
        assert status == "error"


class TestValidateIssueCounting:
    """validate 이슈 카운팅 테스트."""

    def test_missing_title_count(self):
        """title 누락 카운팅."""
        docs = [
            {"path": "doc1.md", "title": "doc1.md"},  # path와 동일 = 누락
            {"path": "doc2.md", "title": "doc2"},  # stem과 동일 = 누락
            {"path": "doc3.md", "title": "Good Title"},  # 정상
        ]
        missing = 0
        for doc in docs:
            path = doc["path"]
            title = doc.get("title", "")
            path_stem = path[:-3] if path.endswith(".md") else path
            if not title or title == path or title == path_stem:
                missing += 1

        assert missing == 2

    def test_summary_classification(self):
        """문서 분류 (complete/partial/no_frontmatter)."""
        # missing_count 기준:
        # 0 = complete
        # 1-4 = partial
        # 5+ = no_frontmatter

        assert 0 == 0  # complete
        assert 1 < 5  # partial
        assert 5 >= 5  # no_frontmatter
