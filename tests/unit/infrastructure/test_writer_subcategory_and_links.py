"""FrontmatterWriter v0.4.0 회귀 테스트.

다루는 기능:
- ``ClassificationDecision.subcategory`` 가 있으면 파일은
  ``<category>/<subcategory>/<basename>`` 으로 이동하고 frontmatter 에도 기록된다.
- 파일 이동 시 다른 파일 본문의 ``[[옛 경로]]`` / ``[[옛 stem]]`` wikilink 가
  새 경로로 자동 보정된다 (rewrite_inbound_links=True 기본값).
- ``rewrite_inbound_links=False`` 면 보정하지 않는다.
- vault 안에 동일 basename 이 둘 이상이면 basename-only 링크는 모호하므로 치환하지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from wiki_search_mcp.core.models import ClassificationDecision
from wiki_search_mcp.infrastructure.frontmatter.writer import FrontmatterWriter


def _decision(category: str, subcategory: str | None = None) -> ClassificationDecision:
    return ClassificationDecision(
        path="inbox/foo.md",
        category=category,
        subcategory=subcategory,
        tags=(),
        confidence=0.9,
        reasoning="r",
        provider="fake",
        raw_response="",
    )


def test_subcategory_moves_into_nested_folder(tmp_path: Path) -> None:
    pages = tmp_path
    (pages / "inbox").mkdir()
    (pages / "projects" / "myproj").mkdir(parents=True)
    (pages / "inbox" / "foo.md").write_text(
        "---\ntitle: foo\n---\n본문", encoding="utf-8"
    )

    writer = FrontmatterWriter(pages, rewrite_inbound_links=False)
    record = writer.apply("inbox/foo.md", _decision("projects", "myproj"))

    assert record.path_after == "projects/myproj/foo.md"
    assert (pages / "projects" / "myproj" / "foo.md").exists()
    assert not (pages / "inbox" / "foo.md").exists()
    # frontmatter 에도 subcategory 기록
    moved = (pages / "projects" / "myproj" / "foo.md").read_text(encoding="utf-8")
    assert "subcategory: myproj" in moved


def test_no_subcategory_keeps_flat_behavior(tmp_path: Path) -> None:
    pages = tmp_path
    (pages / "inbox").mkdir()
    (pages / "projects").mkdir()
    (pages / "inbox" / "foo.md").write_text(
        "---\n---\n본문", encoding="utf-8"
    )

    writer = FrontmatterWriter(pages, rewrite_inbound_links=False)
    record = writer.apply("inbox/foo.md", _decision("projects", None))

    assert record.path_after == "projects/foo.md"


def test_inbound_wikilink_rewrite_with_full_path(tmp_path: Path) -> None:
    """[[inbox/foo]] / [[inbox/foo.md]] 형태의 링크는 새 경로로 보정된다."""
    pages = tmp_path
    (pages / "inbox").mkdir()
    (pages / "infra").mkdir()
    (pages / "inbox" / "foo.md").write_text("---\n---\n본문", encoding="utf-8")
    other = pages / "infra" / "other.md"
    other.write_text(
        "참고1: [[inbox/foo]]\n참고2: [[inbox/foo.md]]\n", encoding="utf-8"
    )

    writer = FrontmatterWriter(pages, rewrite_inbound_links=True)
    writer.apply("inbox/foo.md", _decision("infra", None))

    text = other.read_text(encoding="utf-8")
    assert "[[infra/foo]]" in text
    assert "[[inbox/foo]]" not in text
    assert "[[inbox/foo.md]]" not in text


def test_inbound_wikilink_rewrite_with_basename_only_when_unique(tmp_path: Path) -> None:
    """vault 전역 unique 한 basename 은 ``[[foo]]`` 도 보정된다."""
    pages = tmp_path
    (pages / "inbox").mkdir()
    (pages / "infra").mkdir()
    (pages / "inbox" / "foo.md").write_text("---\n---\n본문", encoding="utf-8")
    other = pages / "infra" / "other.md"
    other.write_text("참고: [[foo]] / [[foo|레이블]]", encoding="utf-8")

    writer = FrontmatterWriter(pages, rewrite_inbound_links=True)
    writer.apply("inbox/foo.md", _decision("infra", None))

    text = other.read_text(encoding="utf-8")
    assert "[[infra/foo]]" in text
    assert "[[infra/foo|레이블]]" in text


def test_inbound_wikilink_skips_basename_when_ambiguous(tmp_path: Path) -> None:
    """동일 basename 이 vault 에 둘 이상 있으면 basename-only 링크는 치환 안 함."""
    pages = tmp_path
    (pages / "inbox").mkdir()
    (pages / "infra").mkdir()
    (pages / "archive").mkdir()
    (pages / "inbox" / "foo.md").write_text("---\n---\n본문", encoding="utf-8")
    # 같은 basename 의 다른 파일 — 모호함을 만든다
    (pages / "archive" / "foo.md").write_text("아카이브", encoding="utf-8")
    other = pages / "infra" / "other.md"
    other.write_text(
        "전체경로: [[inbox/foo]]\n베이스네임: [[foo]]\n", encoding="utf-8"
    )

    writer = FrontmatterWriter(pages, rewrite_inbound_links=True)
    writer.apply("inbox/foo.md", _decision("infra", None))

    text = other.read_text(encoding="utf-8")
    # 전체 경로 매칭은 안전 → 치환됨
    assert "[[infra/foo]]" in text
    # basename-only 는 모호 → 원형 보존
    assert "[[foo]]" in text


def test_inbound_rewrite_preserves_anchor(tmp_path: Path) -> None:
    """[[inbox/foo#섹션]] 의 ``#섹션`` 은 보존되어야 한다."""
    pages = tmp_path
    (pages / "inbox").mkdir()
    (pages / "infra").mkdir()
    (pages / "inbox" / "foo.md").write_text("---\n---\n본문", encoding="utf-8")
    other = pages / "infra" / "other.md"
    other.write_text("참고: [[inbox/foo#섹션]]", encoding="utf-8")

    writer = FrontmatterWriter(pages, rewrite_inbound_links=True)
    writer.apply("inbox/foo.md", _decision("infra", None))

    text = other.read_text(encoding="utf-8")
    assert "[[infra/foo#섹션]]" in text


def test_rewrite_inbound_links_can_be_disabled(tmp_path: Path) -> None:
    pages = tmp_path
    (pages / "inbox").mkdir()
    (pages / "infra").mkdir()
    (pages / "inbox" / "foo.md").write_text("---\n---\n본문", encoding="utf-8")
    other = pages / "infra" / "other.md"
    other.write_text("[[inbox/foo]]", encoding="utf-8")

    writer = FrontmatterWriter(pages, rewrite_inbound_links=False)
    writer.apply("inbox/foo.md", _decision("infra", None))

    text = other.read_text(encoding="utf-8")
    # 보정 비활성 시 옛 링크 유지 (사용자 결정에 따른 trade-off)
    assert "[[inbox/foo]]" in text


def test_moved_file_itself_is_not_rewritten(tmp_path: Path) -> None:
    """옮긴 파일 자신의 본문 wikilink 는 건드리지 않는다 (자기참조 회귀 방지)."""
    pages = tmp_path
    (pages / "inbox").mkdir()
    (pages / "infra").mkdir()
    (pages / "inbox" / "foo.md").write_text(
        "---\n---\n본인은 [[inbox/foo]] 를 가리킬 일 없음", encoding="utf-8"
    )

    writer = FrontmatterWriter(pages, rewrite_inbound_links=True)
    writer.apply("inbox/foo.md", _decision("infra", None))

    moved = (pages / "infra" / "foo.md").read_text(encoding="utf-8")
    # 옮긴 파일 본문은 그대로 보존 (자기 참조였든 아니든 손대지 않음).
    assert "[[inbox/foo]]" in moved
