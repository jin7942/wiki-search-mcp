"""ClassificationService.suggest_subfolders 테스트 (보고서 Gap #1/#3).

평면 프로젝트 폴더의 서브폴더 계층화 제안. frontmatter 태그 + 본문 키워드를
공통 신호로 그룹핑하고, min_cluster_size 이상 묶일 때만 서브폴더로 제안한다.
read-only: 실제 폴더 생성/이동은 하지 않음(반환만 검증).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiki_search_mcp.core.exceptions import InvalidPathError
from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher
from wiki_search_mcp.services.classification_service import ClassificationService


@pytest.fixture
def wiki_path(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def matcher(wiki_path: Path) -> IgnoreMatcher:
    return IgnoreMatcher.from_wiki(wiki_path)


def _make_service(wiki_path: Path, matcher: IgnoreMatcher) -> ClassificationService:
    vector = MagicMock()
    vector.exists.return_value = False
    return ClassificationService(
        pages_path=wiki_path,
        vector_repository=vector,
        document_service=MagicMock(),
        category_service=MagicMock(),
        ignore_matcher=matcher,
    )


def _write(wiki_path: Path, rel: str, tags: list[str], body: str = "내용") -> None:
    p = wiki_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = "tags: [" + ", ".join(tags) + "]" if tags else ""
    p.write_text(f"---\n{fm}\n---\n\n{body}", encoding="utf-8")


def test_groups_by_common_tag(wiki_path: Path, matcher: IgnoreMatcher):
    """같은 태그를 가진 파일이 min_cluster_size 이상이면 서브폴더 그룹."""
    _write(wiki_path, "projects/KT/a.md", ["vpn", "network"])
    _write(wiki_path, "projects/KT/b.md", ["vpn"])
    _write(wiki_path, "projects/KT/c.md", ["vpn", "infra"])
    _write(wiki_path, "projects/KT/d.md", ["meeting"])

    svc = _make_service(wiki_path, matcher)
    r = svc.suggest_subfolders("projects/KT", min_cluster_size=3)

    assert r.folder == "projects/KT"
    assert r.file_count == 4
    assert len(r.groups) == 1
    g = r.groups[0]
    assert g.name == "vpn"
    assert set(g.files) == {
        "projects/KT/a.md",
        "projects/KT/b.md",
        "projects/KT/c.md",
    }
    # meeting 은 1개뿐 → 미분류
    assert r.unclassified == ("projects/KT/d.md",)


def test_no_group_when_below_threshold(wiki_path: Path, matcher: IgnoreMatcher):
    """임계 이상 묶이는 공통 신호가 없으면 그룹 0개, 전부 미분류."""
    _write(wiki_path, "projects/X/a.md", ["alpha"])
    _write(wiki_path, "projects/X/b.md", ["beta"])
    _write(wiki_path, "projects/X/c.md", ["gamma"])
    _write(wiki_path, "projects/X/d.md", ["delta"])

    svc = _make_service(wiki_path, matcher)
    r = svc.suggest_subfolders("projects/X", min_cluster_size=3)

    assert r.groups == ()
    assert len(r.unclassified) == 4
    assert "공통 태그/키워드 없음" in r.reasoning


def test_below_min_files_returns_empty(wiki_path: Path, matcher: IgnoreMatcher):
    """폴더 파일 수가 임계 미만이면 평면 유지 권장(그룹 없음)."""
    _write(wiki_path, "projects/Small/a.md", ["x"])
    _write(wiki_path, "projects/Small/b.md", ["x"])

    svc = _make_service(wiki_path, matcher)
    r = svc.suggest_subfolders("projects/Small", min_cluster_size=3)

    assert r.file_count == 2
    assert r.groups == ()
    assert "평면 유지 권장" in r.reasoning


def test_missing_folder_returns_empty(wiki_path: Path, matcher: IgnoreMatcher):
    """존재하지 않는 폴더는 빈 제안."""
    svc = _make_service(wiki_path, matcher)
    r = svc.suggest_subfolders("projects/Ghost", min_cluster_size=3)

    assert r.file_count == 0
    assert r.groups == ()
    assert "존재하지 않음" in r.reasoning


def test_greedy_no_duplicate_assignment(wiki_path: Path, matcher: IgnoreMatcher):
    """한 파일이 여러 후보 태그를 가져도 한 그룹에만 선점된다(중복 금지)."""
    # 'common' 태그는 5개 전부, 'sub' 태그는 그중 3개
    for name in ["a", "b", "c", "d", "e"]:
        tags = ["common"]
        if name in ("a", "b", "c"):
            tags.append("sub")
        _write(wiki_path, f"projects/P/{name}.md", tags)

    svc = _make_service(wiki_path, matcher)
    r = svc.suggest_subfolders("projects/P", min_cluster_size=3)

    # common(5) 이 가장 커서 먼저 5개 전부 선점 → sub 는 남은 파일 0개라 그룹 못 됨
    assert len(r.groups) == 1
    assert r.groups[0].name == "common"
    assert len(r.groups[0].files) == 5
    # 모든 파일이 한 그룹에만, 중복 없음
    all_files = [f for g in r.groups for f in g.files]
    assert len(all_files) == len(set(all_files)) == 5
    assert r.unclassified == ()


def test_groups_sorted_by_size_desc(wiki_path: Path, matcher: IgnoreMatcher):
    """그룹은 크기 내림차순 정렬."""
    # big: 4개, small: 3개 (서로 다른 파일)
    for name in ["a", "b", "c", "d"]:
        _write(wiki_path, f"projects/Q/{name}.md", ["big"])
    for name in ["e", "f", "g"]:
        _write(wiki_path, f"projects/Q/{name}.md", ["small"])

    svc = _make_service(wiki_path, matcher)
    r = svc.suggest_subfolders("projects/Q", min_cluster_size=3)

    assert [g.name for g in r.groups] == ["big", "small"]
    assert len(r.groups[0].files) == 4
    assert len(r.groups[1].files) == 3


def test_subdirectories_ignored(wiki_path: Path, matcher: IgnoreMatcher):
    """직계 .md만 대상, 하위 폴더 파일은 제외."""
    _write(wiki_path, "projects/R/a.md", ["t"])
    _write(wiki_path, "projects/R/b.md", ["t"])
    _write(wiki_path, "projects/R/c.md", ["t"])
    _write(wiki_path, "projects/R/sub/deep.md", ["t"])  # 하위 폴더

    svc = _make_service(wiki_path, matcher)
    r = svc.suggest_subfolders("projects/R", min_cluster_size=3)

    assert r.file_count == 3  # deep.md 제외
    all_files = [f for g in r.groups for f in g.files] + list(r.unclassified)
    assert "projects/R/sub/deep.md" not in all_files


def test_path_traversal_rejected(wiki_path: Path, matcher: IgnoreMatcher):
    """경로 탈출 시도는 거부."""
    svc = _make_service(wiki_path, matcher)
    with pytest.raises(InvalidPathError):
        svc.suggest_subfolders("../../etc", min_cluster_size=3)


def test_to_dict_serialization(wiki_path: Path, matcher: IgnoreMatcher):
    """SubfolderSuggestion.to_dict() 직렬화."""
    _write(wiki_path, "projects/S/a.md", ["k"])
    _write(wiki_path, "projects/S/b.md", ["k"])
    _write(wiki_path, "projects/S/c.md", ["k"])

    svc = _make_service(wiki_path, matcher)
    d = svc.suggest_subfolders("projects/S", min_cluster_size=3).to_dict()

    assert d["folder"] == "projects/S"
    assert d["file_count"] == 3
    assert isinstance(d["groups"], list)
    assert d["groups"][0]["name"] == "k"
    assert isinstance(d["groups"][0]["files"], list)
    assert "reasoning" in d
