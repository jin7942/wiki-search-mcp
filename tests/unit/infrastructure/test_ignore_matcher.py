"""IgnoreMatcher 단위 테스트.

dot-prefix 자동 무시, .gitignore 파싱, WIKI_IGNORE 환경변수 검증.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher


@pytest.fixture
def wiki_root(tmp_path: Path) -> Path:
    """임시 wiki 루트 디렉토리."""
    return tmp_path


def test_dot_prefix_directory_ignored(wiki_root: Path):
    """점(.)으로 시작하는 디렉토리는 자동 무시."""
    matcher = IgnoreMatcher.from_wiki(wiki_root)

    assert matcher.should_ignore(wiki_root / ".git" / "config")
    assert matcher.should_ignore(wiki_root / ".obsidian" / "workspace.json")
    assert matcher.should_ignore(wiki_root / ".vectordb" / "data.lance")
    assert matcher.should_ignore(wiki_root / "subdir" / ".cache" / "x.md")


def test_dot_prefix_file_ignored(wiki_root: Path):
    """점(.)으로 시작하는 파일은 자동 무시."""
    matcher = IgnoreMatcher.from_wiki(wiki_root)

    assert matcher.should_ignore(wiki_root / ".DS_Store")
    assert matcher.should_ignore(wiki_root / ".gitignore")
    assert matcher.should_ignore(wiki_root / "notes" / ".hidden.md")


def test_normal_path_not_ignored(wiki_root: Path):
    """일반 경로는 무시되지 않음."""
    matcher = IgnoreMatcher.from_wiki(wiki_root)

    assert not matcher.should_ignore(wiki_root / "notes" / "memo.md")
    assert not matcher.should_ignore(wiki_root / "Projects" / "alpha" / "spec.md")


def test_fallback_patterns_ignored(wiki_root: Path):
    """node_modules, __pycache__ 등 fallback 패턴 무시."""
    matcher = IgnoreMatcher.from_wiki(wiki_root)

    assert matcher.should_ignore(wiki_root / "node_modules" / "lib.js")
    assert matcher.should_ignore(wiki_root / "src" / "__pycache__" / "x.pyc")


def test_gitignore_loaded(wiki_root: Path):
    """wiki 루트의 .gitignore가 자동 로드됨."""
    (wiki_root / ".gitignore").write_text("draft/\n*.bak\n# comment\n", encoding="utf-8")

    matcher = IgnoreMatcher.from_wiki(wiki_root)

    assert matcher.gitignore_loaded
    assert matcher.should_ignore(wiki_root / "draft" / "wip.md")
    assert matcher.should_ignore(wiki_root / "notes" / "old.bak")


def test_gitignore_negation_skipped(wiki_root: Path):
    """negation(!) 패턴은 1차 구현에서 무시 (단순 처리)."""
    (wiki_root / ".gitignore").write_text("tmp/\n!tmp/keep.md\n", encoding="utf-8")

    matcher = IgnoreMatcher.from_wiki(wiki_root)

    # negation은 미지원, tmp 패턴만 적용
    assert matcher.should_ignore(wiki_root / "tmp" / "wip.md")


def test_gitignore_comments_ignored(wiki_root: Path):
    """주석 라인은 패턴으로 처리되지 않음."""
    (wiki_root / ".gitignore").write_text("# This is a comment\n\n*.log\n", encoding="utf-8")

    matcher = IgnoreMatcher.from_wiki(wiki_root)

    assert matcher.should_ignore(wiki_root / "app.log")
    assert not matcher.should_ignore(wiki_root / "comment.md")


def test_no_gitignore(wiki_root: Path):
    """.gitignore 없으면 gitignore_loaded=False."""
    matcher = IgnoreMatcher.from_wiki(wiki_root)

    assert not matcher.gitignore_loaded


def test_env_wiki_ignore(wiki_root: Path, monkeypatch: pytest.MonkeyPatch):
    """WIKI_IGNORE 환경변수 패턴 적용."""
    monkeypatch.setenv("WIKI_IGNORE", "draft,*.tmp,private")

    matcher = IgnoreMatcher.from_wiki(wiki_root)

    assert matcher.should_ignore(wiki_root / "draft" / "wip.md")
    assert matcher.should_ignore(wiki_root / "scratch.tmp")
    assert matcher.should_ignore(wiki_root / "private" / "diary.md")
    assert not matcher.should_ignore(wiki_root / "Notes" / "memo.md")


def test_env_wiki_ignore_empty(wiki_root: Path, monkeypatch: pytest.MonkeyPatch):
    """WIKI_IGNORE 빈 값은 영향 없음."""
    monkeypatch.setenv("WIKI_IGNORE", "")

    matcher = IgnoreMatcher.from_wiki(wiki_root)

    assert not matcher.should_ignore(wiki_root / "Notes" / "memo.md")


def test_env_wiki_ignore_whitespace_handling(
    wiki_root: Path, monkeypatch: pytest.MonkeyPatch
):
    """WIKI_IGNORE 패턴 주변 공백 처리."""
    monkeypatch.setenv("WIKI_IGNORE", " draft , *.bak , ")

    matcher = IgnoreMatcher.from_wiki(wiki_root)

    assert matcher.should_ignore(wiki_root / "draft" / "wip.md")
    assert matcher.should_ignore(wiki_root / "old.bak")


def test_combined_priorities(wiki_root: Path, monkeypatch: pytest.MonkeyPatch):
    """dot-prefix + .gitignore + WIKI_IGNORE 모두 결합 동작."""
    (wiki_root / ".gitignore").write_text("build/\n", encoding="utf-8")
    monkeypatch.setenv("WIKI_IGNORE", "scratch")

    matcher = IgnoreMatcher.from_wiki(wiki_root)

    assert matcher.should_ignore(wiki_root / ".git" / "x")  # dot-prefix
    assert matcher.should_ignore(wiki_root / "build" / "out.md")  # gitignore
    assert matcher.should_ignore(wiki_root / "scratch" / "test.md")  # env
    assert not matcher.should_ignore(wiki_root / "Notes" / "memo.md")


def test_relative_path_handling(wiki_root: Path):
    """절대/상대 경로 모두 처리 가능."""
    matcher = IgnoreMatcher.from_wiki(wiki_root)

    # 절대 경로
    assert matcher.should_ignore(wiki_root / ".git" / "x")
    # 상대 경로
    assert matcher.should_ignore(Path(".obsidian") / "workspace")
