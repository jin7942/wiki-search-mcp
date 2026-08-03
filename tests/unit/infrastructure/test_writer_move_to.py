"""FrontmatterWriter.move_to / decide_target_path 중첩 subcategory 테스트 (0.7.0).

- ``move_to``: rename/계층화용 명시적 이동. 본문 보존 + wikilink 보정 +
  AppliedRecord(rollback 호환).
- ``decide_target_path``: 중첩 subcategory(``KT/인수인계``) 경로 계산과
  '제자리' 판정.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_search_mcp.core.utils import parse_frontmatter
from wiki_search_mcp.infrastructure.frontmatter.writer import (
    FrontmatterWriter,
    decide_target_path,
)


@pytest.fixture
def pages(tmp_path: Path) -> Path:
    return tmp_path


def _write(pages: Path, rel: str, text: str) -> None:
    p = pages / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# decide_target_path — 중첩 subcategory (R1)
# ---------------------------------------------------------------------------


def test_decide_target_path_nested_subcategory() -> None:
    assert (
        decide_target_path("inbox/a.md", "projects", "KT/인수인계")
        == "projects/KT/인수인계/a.md"
    )


def test_decide_target_path_nested_already_in_place() -> None:
    rel = "projects/KT/인수인계/a.md"
    assert decide_target_path(rel, "projects", "KT/인수인계") == rel


def test_decide_target_path_single_level_unchanged() -> None:
    # 기존 1-depth 동작 보존
    assert decide_target_path("inbox/a.md", "projects", "KT") == "projects/KT/a.md"
    assert (
        decide_target_path("projects/KT/a.md", "projects", "KT")
        == "projects/KT/a.md"
    )


# ---------------------------------------------------------------------------
# move_to (R4 rename / R2 계층화 이동)
# ---------------------------------------------------------------------------


def test_move_to_renames_and_rewrites_wikilinks(pages: Path) -> None:
    _write(pages, "projects/P/26.05.11 회의.md", "---\ntags: [a]\n---\n\n본문 내용")
    _write(pages, "projects/P/ref.md", "링크: [[26.05.11 회의]] 참조")

    writer = FrontmatterWriter(pages)
    record = writer.move_to(
        "projects/P/26.05.11 회의.md",
        "projects/P/2026-05-11 회의.md",
        op="filename_normalization",
    )

    assert not (pages / "projects/P/26.05.11 회의.md").exists()
    new_file = pages / "projects/P/2026-05-11 회의.md"
    assert new_file.exists()
    meta, body = parse_frontmatter(new_file.read_text(encoding="utf-8"))
    assert meta["tags"] == ["a"]  # frontmatter 보존
    assert "본문 내용" in body  # 본문 보존
    # inbound wikilink 보정
    ref = (pages / "projects/P/ref.md").read_text(encoding="utf-8")
    assert "[[projects/P/2026-05-11 회의]]" in ref
    # AppliedRecord — rollback 호환
    assert record.path_before == "projects/P/26.05.11 회의.md"
    assert record.path_after == "projects/P/2026-05-11 회의.md"
    assert record.decision["type"] == "filename_normalization"


def test_move_to_sets_subcategory(pages: Path) -> None:
    _write(pages, "projects/P/a.md", "---\nsubcategory: old\n---\n\nx")
    writer = FrontmatterWriter(pages, rewrite_inbound_links=False)
    writer.move_to("projects/P/a.md", "projects/P/회의록/a.md", subcategory="P/회의록")

    meta, _ = parse_frontmatter(
        (pages / "projects/P/회의록/a.md").read_text(encoding="utf-8")
    )
    assert meta["subcategory"] == "P/회의록"


def test_move_to_collision_suffix(pages: Path) -> None:
    _write(pages, "projects/P/a.md", "x")
    _write(pages, "projects/P/sub/a.md", "occupied")
    writer = FrontmatterWriter(pages, rewrite_inbound_links=False)
    record = writer.move_to("projects/P/a.md", "projects/P/sub/a.md")
    assert record.path_after == "projects/P/sub/a-1.md"
    assert (pages / "projects/P/sub/a-1.md").exists()


def test_move_to_missing_source_raises(pages: Path) -> None:
    writer = FrontmatterWriter(pages)
    with pytest.raises(FileNotFoundError):
        writer.move_to("projects/P/ghost.md", "projects/P/x.md")
