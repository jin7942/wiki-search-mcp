"""Zero-Config 워크플로우 통합 테스트.

신규 도입된 자동 분류 흐름을 end-to-end로 검증합니다.
- 폴더 구조 자동 감지
- 빈 디렉토리 → AI 제안 폴백
- .gitignore 활용
- WIKI_IGNORE 환경변수
- 각 신규 핸들러의 정상 응답
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wiki_search_mcp.adapters.mcp.container import ServiceContainer
from wiki_search_mcp.adapters.mcp.handlers import (
    handle_wiki_get_categories,
    handle_wiki_pending,
    handle_wiki_suggest_categories,
)
from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher
from wiki_search_mcp.infrastructure.indexing import WikiIndexer


@pytest.fixture
def folder_workspace(tmp_path: Path) -> Path:
    """폴더 구조가 있는 워크스페이스."""
    (tmp_path / "Notes").mkdir()
    (tmp_path / "Notes" / "memo.md").write_text(
        "---\ntitle: Memo\ncategory: Notes\n---\n# Memo\nbody",
        encoding="utf-8",
    )
    (tmp_path / "Projects").mkdir()
    (tmp_path / "Projects" / "alpha.md").write_text(
        "---\ntitle: Alpha\ncategory: Projects\n---\n# Alpha\nbody",
        encoding="utf-8",
    )
    # 미분류 (frontmatter 없음)
    (tmp_path / "Notes" / "draft.md").write_text("# Draft\nincomplete", encoding="utf-8")
    return tmp_path


@pytest.fixture
def empty_workspace(tmp_path: Path) -> Path:
    """폴더 없이 평탄한 .md 1개만 있는 워크스페이스."""
    (tmp_path / "single.md").write_text("# Single\nlonely note", encoding="utf-8")
    return tmp_path


def test_get_categories_folder_mode(folder_workspace: Path):
    """폴더 ≥ 2개 → mode='folder'."""
    container = ServiceContainer(str(folder_workspace))
    result = handle_wiki_get_categories(container)
    data = json.loads(result)

    assert data["mode"] == "folder"
    assert "Notes" in data["categories"]
    assert "Projects" in data["categories"]


def test_get_categories_empty_mode(empty_workspace: Path):
    """폴더 없음 → mode='empty'."""
    container = ServiceContainer(str(empty_workspace))
    result = handle_wiki_get_categories(container)
    data = json.loads(result)

    assert data["mode"] == "empty"
    assert data["categories"] == []


def test_pending_returns_unindexed_files(folder_workspace: Path):
    """인덱싱 전엔 모든 .md 파일이 not_indexed로 잡힘."""
    container = ServiceContainer(str(folder_workspace))
    result = handle_wiki_pending(container, limit=20)
    data = json.loads(result)

    paths = [item["path"] for item in data["items"]]
    # 인덱스가 없으면 vector_repository.exists()가 False라 디스크 스캔만 진행
    # 단, find_pending에서 exists 체크 후 to_arrow_list 호출하지 않으므로
    # 신규 파일이 모두 not_indexed로 잡혀야 함
    assert any("draft.md" in p for p in paths)


def test_gitignore_excludes_files(tmp_path: Path):
    """.gitignore 패턴이 인덱싱에서 자동 제외됨."""
    # .gitignore 작성
    (tmp_path / ".gitignore").write_text("excluded/\n*.bak\n", encoding="utf-8")

    # 일반 파일
    (tmp_path / "Notes").mkdir()
    (tmp_path / "Notes" / "ok.md").write_text("# OK", encoding="utf-8")
    # 무시 대상
    (tmp_path / "excluded").mkdir()
    (tmp_path / "excluded" / "secret.md").write_text("# Secret", encoding="utf-8")
    (tmp_path / "old.bak").write_text("# Old backup", encoding="utf-8")

    matcher = IgnoreMatcher.from_wiki(tmp_path)
    assert matcher.should_ignore(tmp_path / "excluded" / "secret.md")
    assert matcher.should_ignore(tmp_path / "old.bak")
    assert not matcher.should_ignore(tmp_path / "Notes" / "ok.md")


def test_extra_patterns_excludes_pattern(tmp_path: Path):
    """extra_patterns 인자로 무시 패턴 적용 (CLI --ignore에 해당)."""
    (tmp_path / "Notes").mkdir()
    (tmp_path / "Notes" / "ok.md").write_text("# OK", encoding="utf-8")
    (tmp_path / "scratch").mkdir()
    (tmp_path / "scratch" / "tmp.md").write_text("# Tmp", encoding="utf-8")

    matcher = IgnoreMatcher.from_wiki(tmp_path, extra_patterns=("scratch",))
    assert matcher.should_ignore(tmp_path / "scratch" / "tmp.md")
    assert not matcher.should_ignore(tmp_path / "Notes" / "ok.md")


def test_dot_prefix_dirs_not_in_categories(tmp_path: Path):
    """dot-prefix 디렉토리는 카테고리에 포함되지 않음."""
    (tmp_path / "Notes").mkdir()
    (tmp_path / "Projects").mkdir()
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".vectordb").mkdir()
    (tmp_path / ".git").mkdir()

    container = ServiceContainer(str(tmp_path))
    result = handle_wiki_get_categories(container)
    data = json.loads(result)

    assert ".obsidian" not in data["categories"]
    assert ".vectordb" not in data["categories"]
    assert ".git" not in data["categories"]
    assert sorted(data["categories"]) == ["Notes", "Projects"]


def test_suggest_categories_empty_index_returns_empty_list(empty_workspace: Path):
    """인덱스가 비어있으면 suggestions 빈 목록 반환."""
    container = ServiceContainer(str(empty_workspace))
    result = handle_wiki_suggest_categories(container, top_k=5)
    data = json.loads(result)

    assert "suggestions" in data
    assert data["suggestions"] == []


def test_indexer_uses_ignore_matcher(tmp_path: Path):
    """WikiIndexer가 IgnoreMatcher를 통해 무시 패턴 적용."""
    (tmp_path / ".gitignore").write_text("draft/\n", encoding="utf-8")
    (tmp_path / "Notes").mkdir()
    (tmp_path / "Notes" / "ok.md").write_text(
        "---\ntitle: OK\ncategory: Notes\n---\n# OK\nbody",
        encoding="utf-8",
    )
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "wip.md").write_text(
        "---\ntitle: WIP\ncategory: draft\n---\n# WIP\nbody",
        encoding="utf-8",
    )

    indexer = WikiIndexer(str(tmp_path))
    # IgnoreMatcher가 wiki_path 기준으로 만들어졌는지 확인
    assert indexer.ignore_matcher.gitignore_loaded
    assert indexer.ignore_matcher.should_ignore(tmp_path / "draft" / "wip.md")
    assert not indexer.ignore_matcher.should_ignore(tmp_path / "Notes" / "ok.md")
