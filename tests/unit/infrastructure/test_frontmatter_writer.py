"""FrontmatterWriter 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_search_mcp.core.models import ClassificationDecision
from wiki_search_mcp.core.utils import parse_frontmatter
from wiki_search_mcp.infrastructure.frontmatter.writer import (
    FrontmatterWriter,
    _decide_target_path,
    _merge_tags,
)


def _make_decision(category: str = "infra", tags=("nginx", "ssl"), confidence: float = 0.85) -> ClassificationDecision:
    return ClassificationDecision(
        path="x.md",
        category=category,
        tags=tuple(tags),
        confidence=confidence,
        reasoning="test",
        provider="test-provider",
        raw_response="",
    )


def test_merge_tags_dedup_case_insensitive() -> None:
    assert _merge_tags(["Nginx", "ssl"], ["nginx", "TLS"]) == ["Nginx", "ssl", "TLS"]


def test_merge_tags_strips_and_skips_empty() -> None:
    assert _merge_tags([" a "], ["", None, "b"]) == ["a", "b"]


def test_decide_target_path_keeps_when_already_in_category() -> None:
    assert _decide_target_path("infra/x.md", "infra") == "infra/x.md"


def test_decide_target_path_moves_into_category() -> None:
    assert _decide_target_path("inbox/x.md", "infra") == "infra/x.md"


def test_apply_writes_frontmatter_and_moves(tmp_path: Path) -> None:
    pages = tmp_path
    (pages / "inbox").mkdir()
    (pages / "inbox" / "x.md").write_text("# Heading\nbody text", encoding="utf-8")

    writer = FrontmatterWriter(pages)
    record = writer.apply("inbox/x.md", _make_decision("infra", ("nginx",), 0.9))

    assert record.path_before == "inbox/x.md"
    assert record.path_after == "infra/x.md"
    assert (pages / "infra" / "x.md").exists()
    assert not (pages / "inbox" / "x.md").exists()

    new = (pages / "infra" / "x.md").read_text(encoding="utf-8")
    meta, body = parse_frontmatter(new)
    assert meta["category"] == "infra"
    assert meta["tags"] == ["nginx"]
    assert meta["confidence_score"] == 90
    assert meta["state"] == "draft"
    assert body.startswith("# Heading")


def test_apply_preserves_existing_category(tmp_path: Path) -> None:
    """사용자 값이 우선: 이미 category가 있으면 덮어쓰지 않는다."""
    pages = tmp_path
    (pages / "notes").mkdir()
    (pages / "notes" / "x.md").write_text(
        "---\ncategory: notes\ntags: [user]\n---\n\nbody\n", encoding="utf-8"
    )

    writer = FrontmatterWriter(pages)
    record = writer.apply("notes/x.md", _make_decision("infra", ("nginx",), 0.95))

    # 이동 안 함 (이미 notes 카테고리에 있음 — but decision은 infra이지만 사용자 값이 우선)
    new_meta = record.frontmatter_after
    assert new_meta["category"] == "notes"   # 사용자 값 유지
    assert "user" in new_meta["tags"]
    assert "nginx" in new_meta["tags"]
    # 파일은 notes/에 유지됨 (사용자 category=notes 기준 _decide_target_path)
    assert (pages / "notes" / "x.md").exists()


def test_apply_collision_avoidance(tmp_path: Path) -> None:
    pages = tmp_path
    (pages / "inbox").mkdir()
    (pages / "infra").mkdir()
    (pages / "inbox" / "x.md").write_text("body", encoding="utf-8")
    (pages / "infra" / "x.md").write_text("# pre-existing\nold", encoding="utf-8")

    writer = FrontmatterWriter(pages)
    record = writer.apply("inbox/x.md", _make_decision("infra", ("nginx",), 0.9))

    # 충돌 회피: x-1.md 같은 이름
    assert record.path_after.startswith("infra/x-")
    assert record.path_after.endswith(".md")
    assert (pages / record.path_after).exists()
    # 원본 inbox/x.md는 삭제됨
    assert not (pages / "inbox" / "x.md").exists()


def test_apply_no_move_option(tmp_path: Path) -> None:
    pages = tmp_path
    (pages / "inbox").mkdir()
    (pages / "inbox" / "x.md").write_text("body", encoding="utf-8")

    writer = FrontmatterWriter(pages)
    record = writer.apply(
        "inbox/x.md", _make_decision("infra", (), 0.9), move_into_category=False
    )
    assert record.path_after == "inbox/x.md"
    assert (pages / "inbox" / "x.md").exists()


def test_restore_reverses_frontmatter(tmp_path: Path) -> None:
    pages = tmp_path
    (pages / "infra").mkdir()
    (pages / "infra" / "x.md").write_text(
        "---\ncategory: infra\ntags: [nginx]\n---\n\nbody\n", encoding="utf-8"
    )

    writer = FrontmatterWriter(pages)
    writer.restore("infra/x.md", "inbox/x.md", {})
    # 원래 위치로 복원, frontmatter 제거
    assert not (pages / "infra" / "x.md").exists()
    assert (pages / "inbox" / "x.md").exists()
    restored = (pages / "inbox" / "x.md").read_text(encoding="utf-8")
    assert "category:" not in restored
    assert "body" in restored
