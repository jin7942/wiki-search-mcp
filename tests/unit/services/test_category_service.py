"""CategoryService 단위 테스트.

폴더 자동 감지, 캐싱, AI 제안 폴백 검증.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiki_search_mcp.core.models import CategoryListing
from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher
from wiki_search_mcp.services.category_service import CategoryService


@pytest.fixture
def wiki_path(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def matcher(wiki_path: Path) -> IgnoreMatcher:
    return IgnoreMatcher.from_wiki(wiki_path)


def _make_dirs(root: Path, names: list[str]) -> None:
    for name in names:
        (root / name).mkdir(parents=True, exist_ok=True)


def test_folder_mode_when_two_or_more_dirs(wiki_path: Path, matcher: IgnoreMatcher):
    """디렉토리 ≥ 2개면 folder mode."""
    _make_dirs(wiki_path, ["Notes", "Projects"])

    svc = CategoryService(wiki_path, matcher)
    listing = svc.list_categories()

    assert listing.mode == "folder"
    assert listing.categories == ("Notes", "Projects")
    assert listing.detected_at  # ISO timestamp


def test_empty_mode_when_one_dir(wiki_path: Path, matcher: IgnoreMatcher):
    """디렉토리가 1개뿐이면 empty mode (AI 폴백 신호)."""
    _make_dirs(wiki_path, ["OnlyOne"])

    svc = CategoryService(wiki_path, matcher)
    listing = svc.list_categories()

    assert listing.mode == "empty"
    assert listing.categories == ()


def test_empty_mode_when_no_dirs(wiki_path: Path, matcher: IgnoreMatcher):
    """디렉토리가 없으면 empty mode."""
    svc = CategoryService(wiki_path, matcher)
    listing = svc.list_categories()

    assert listing.mode == "empty"
    assert listing.categories == ()


def test_dot_dirs_excluded_from_categories(wiki_path: Path, matcher: IgnoreMatcher):
    """점(.)으로 시작하는 디렉토리는 카테고리에서 제외."""
    _make_dirs(wiki_path, ["Notes", "Projects", ".obsidian", ".vectordb"])

    svc = CategoryService(wiki_path, matcher)
    listing = svc.list_categories()

    assert listing.mode == "folder"
    assert listing.categories == ("Notes", "Projects")


def test_files_not_treated_as_categories(wiki_path: Path, matcher: IgnoreMatcher):
    """파일은 카테고리로 인식하지 않음."""
    _make_dirs(wiki_path, ["Notes", "Projects"])
    (wiki_path / "README.md").write_text("hello", encoding="utf-8")
    (wiki_path / "index.md").write_text("hello", encoding="utf-8")

    svc = CategoryService(wiki_path, matcher)
    listing = svc.list_categories()

    assert listing.mode == "folder"
    assert listing.categories == ("Notes", "Projects")


def test_ttl_caching(wiki_path: Path, matcher: IgnoreMatcher):
    """캐시 TTL 내에서는 재감지하지 않음."""
    _make_dirs(wiki_path, ["A", "B"])

    fake_time = [1000.0]

    def clock() -> float:
        return fake_time[0]

    svc = CategoryService(wiki_path, matcher, clock=clock)
    listing1 = svc.list_categories()
    assert listing1.mode == "folder"

    # 디렉토리 추가 + 시간 약간만 진행
    _make_dirs(wiki_path, ["C"])
    fake_time[0] = 1010.0  # +10초

    listing2 = svc.list_categories()
    # 캐시된 결과 반환되어야 함
    assert listing2.categories == ("A", "B")


def test_ttl_expires_and_redetects(wiki_path: Path, matcher: IgnoreMatcher):
    """TTL 만료 후 재감지."""
    _make_dirs(wiki_path, ["A", "B"])

    fake_time = [1000.0]

    def clock() -> float:
        return fake_time[0]

    svc = CategoryService(wiki_path, matcher, clock=clock)
    listing1 = svc.list_categories()
    assert listing1.categories == ("A", "B")

    _make_dirs(wiki_path, ["C"])
    fake_time[0] = 1100.0  # +100초 (TTL 60초 초과)

    listing2 = svc.list_categories()
    assert listing2.categories == ("A", "B", "C")


def test_force_refresh_bypasses_cache(wiki_path: Path, matcher: IgnoreMatcher):
    """force_refresh=True이면 캐시 무시."""
    _make_dirs(wiki_path, ["A", "B"])

    svc = CategoryService(wiki_path, matcher)
    listing1 = svc.list_categories()
    assert listing1.categories == ("A", "B")

    _make_dirs(wiki_path, ["C"])
    listing2 = svc.list_categories(force_refresh=True)
    assert listing2.categories == ("A", "B", "C")


def test_invalidate(wiki_path: Path, matcher: IgnoreMatcher):
    """invalidate 후 재감지."""
    _make_dirs(wiki_path, ["A", "B"])

    svc = CategoryService(wiki_path, matcher)
    listing1 = svc.list_categories()
    assert listing1.categories == ("A", "B")

    _make_dirs(wiki_path, ["C"])
    svc.invalidate()
    listing2 = svc.list_categories()
    assert listing2.categories == ("A", "B", "C")


def test_suggest_categories_from_index(wiki_path: Path, matcher: IgnoreMatcher):
    """인덱스 기반 카테고리 빈도 후보 반환."""
    vector = MagicMock()
    vector.exists.return_value = True
    vector.to_arrow_list.return_value = [
        {"category": "infra", "title": "nginx setup", "summary": "nginx 설정 가이드"},
        {"category": "infra", "title": "ssl", "summary": "SSL 인증서"},
        {"category": "infra", "title": "ssh", "summary": "ssh tunnel"},
        {"category": "dev", "title": "python tip", "summary": "파이썬 활용"},
        {"category": "dev", "title": "react", "summary": "리액트 컴포넌트"},
        {"category": "uncategorized", "title": "misc", "summary": "잡다한 메모"},
    ]

    svc = CategoryService(wiki_path, matcher, vector_repository=vector)
    suggestions = svc.suggest_categories(top_k=5)

    names = [s["name"] for s in suggestions]
    assert "infra" in names
    assert "dev" in names
    # uncategorized는 카테고리 후보에서 제외
    assert "uncategorized" not in names

    # infra가 더 많으므로 우선
    assert suggestions[0]["name"] == "infra"
    assert suggestions[0]["doc_count"] == 3


def test_suggest_categories_empty_index(wiki_path: Path, matcher: IgnoreMatcher):
    """인덱스가 없으면 빈 목록."""
    vector = MagicMock()
    vector.exists.return_value = False

    svc = CategoryService(wiki_path, matcher, vector_repository=vector)
    suggestions = svc.suggest_categories(top_k=5)

    assert suggestions == []


def test_suggest_categories_no_vector(wiki_path: Path, matcher: IgnoreMatcher):
    """vector_repository=None이면 빈 목록."""
    svc = CategoryService(wiki_path, matcher, vector_repository=None)
    suggestions = svc.suggest_categories(top_k=5)

    assert suggestions == []


def test_pages_path_does_not_exist(tmp_path: Path, matcher: IgnoreMatcher):
    """pages_path가 없는 경우 empty mode."""
    nonexistent = tmp_path / "missing"
    svc = CategoryService(nonexistent, matcher)
    listing = svc.list_categories()
    assert listing.mode == "empty"


def test_returns_category_listing_type(wiki_path: Path, matcher: IgnoreMatcher):
    """반환 타입은 CategoryListing 인스턴스."""
    svc = CategoryService(wiki_path, matcher)
    listing = svc.list_categories()
    assert isinstance(listing, CategoryListing)
