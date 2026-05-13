"""RollbackService 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_search_mcp.core.models import ClassificationDecision
from wiki_search_mcp.infrastructure.frontmatter.writer import FrontmatterWriter
from wiki_search_mcp.infrastructure.jsonl.log import JsonlLog
from wiki_search_mcp.services.rollback_service import RollbackService


def _apply(pages: Path, src: str, body: str, category: str = "infra") -> Path:
    """헬퍼: 파일 생성 + 분류 적용."""
    full = pages / src
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(body, encoding="utf-8")
    decision = ClassificationDecision(
        path=src,
        category=category,
        tags=("nginx",),
        confidence=0.9,
        reasoning="r",
        provider="test",
        raw_response="",
    )
    record = FrontmatterWriter(pages).apply(src, decision)
    return pages / record.path_after


def test_rollback_restores_original(tmp_path: Path) -> None:
    pages = tmp_path / "wiki"
    pages.mkdir()
    state_path = tmp_path / "applied.jsonl"
    applied = JsonlLog(state_path)

    target = _apply(pages, "inbox/x.md", "# Hello\nbody", category="infra")
    applied.append(
        {
            "path_before": "inbox/x.md",
            "path_after": "infra/x.md",
            "frontmatter_before": {},
            "frontmatter_after": {"category": "infra"},
            "decision": {},
            "applied_at": "now",
            "sha256_before": "",
        }
    )
    assert target.exists()
    assert not (pages / "inbox" / "x.md").exists()

    svc = RollbackService(applied_log=applied, pages_path=pages)
    results = svc.rollback_last(1)
    assert results[0]["status"] == "restored"
    assert (pages / "inbox" / "x.md").exists()
    assert not target.exists()


def test_dry_run_does_not_modify(tmp_path: Path) -> None:
    pages = tmp_path / "wiki"
    pages.mkdir()
    applied = JsonlLog(tmp_path / "applied.jsonl")
    target = _apply(pages, "inbox/x.md", "body")
    applied.append(
        {
            "path_before": "inbox/x.md",
            "path_after": "infra/x.md",
            "frontmatter_before": {},
            "frontmatter_after": {"category": "infra"},
            "decision": {},
            "applied_at": "now",
            "sha256_before": "",
        }
    )
    svc = RollbackService(applied_log=applied, pages_path=pages)
    results = svc.rollback_last(1, dry_run=True)
    assert results[0]["status"] == "would_restore"
    assert target.exists()
    assert not (pages / "inbox" / "x.md").exists()


def test_rollback_skips_missing_file(tmp_path: Path) -> None:
    pages = tmp_path / "wiki"
    pages.mkdir()
    applied = JsonlLog(tmp_path / "applied.jsonl")
    applied.append(
        {
            "path_before": "inbox/x.md",
            "path_after": "infra/missing.md",
            "frontmatter_before": {},
            "frontmatter_after": {},
            "decision": {},
            "applied_at": "now",
            "sha256_before": "",
        }
    )
    svc = RollbackService(applied_log=applied, pages_path=pages)
    results = svc.rollback_last(1)
    assert results[0]["status"] == "skipped"
    assert results[0]["reason"] == "file_missing"
