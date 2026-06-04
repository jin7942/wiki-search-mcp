"""ClassificationService 단위 테스트.

미분류 파일 감지, 분류 추천, 임베딩 재사용 검증.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiki_search_mcp.core.exceptions import DocumentNotFoundError
from wiki_search_mcp.core.models import CategoryListing, Document
from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher
from wiki_search_mcp.services.category_service import CategoryService
from wiki_search_mcp.services.classification_service import ClassificationService


@pytest.fixture
def wiki_path(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def matcher(wiki_path: Path) -> IgnoreMatcher:
    return IgnoreMatcher.from_wiki(wiki_path)


def _make_classification_service(
    wiki_path: Path,
    matcher: IgnoreMatcher,
    *,
    indexed_docs: list[dict] | None = None,
    similar_docs: list[Document] | None = None,
    listing: CategoryListing | None = None,
) -> ClassificationService:
    vector = MagicMock()
    if indexed_docs is None:
        vector.exists.return_value = False
        vector.to_arrow_list.return_value = []
    else:
        vector.exists.return_value = True
        vector.to_arrow_list.return_value = indexed_docs
        vector.find_by_path.side_effect = lambda p: next(
            (d for d in indexed_docs if d.get("path") == p), None
        )

    document_service = MagicMock()
    document_service.get_similar.return_value = similar_docs or []

    if listing is None:
        category_service = CategoryService(wiki_path, matcher, vector_repository=vector)
    else:
        category_service = MagicMock()
        category_service.list_categories.return_value = listing

    return ClassificationService(
        pages_path=wiki_path,
        vector_repository=vector,
        document_service=document_service,
        category_service=category_service,
        ignore_matcher=matcher,
    )


def test_pending_finds_uncategorized_indexed_doc(wiki_path: Path, matcher: IgnoreMatcher):
    """인덱스에 있지만 category가 비어있으면 pending."""
    indexed = [
        {"path": "Notes/a.md", "category": "", "tags": ["x"], "title": "A"},
        {"path": "Notes/b.md", "category": "Notes", "tags": ["y"], "title": "B"},
    ]
    svc = _make_classification_service(wiki_path, matcher, indexed_docs=indexed)
    pending = svc.find_pending()

    paths = [p.path for p in pending]
    assert "Notes/a.md" in paths
    assert "Notes/b.md" not in paths


def test_pending_finds_uncategorized_label(wiki_path: Path, matcher: IgnoreMatcher):
    """category='uncategorized'도 pending으로 잡힘."""
    indexed = [
        {"path": "x.md", "category": "uncategorized", "tags": ["foo"], "title": "X"},
    ]
    svc = _make_classification_service(wiki_path, matcher, indexed_docs=indexed)
    pending = svc.find_pending()
    assert len(pending) == 1
    assert pending[0].reason == "no_category"


def test_pending_no_frontmatter_when_tags_empty(wiki_path: Path, matcher: IgnoreMatcher):
    """카테고리 + 태그 모두 비면 no_frontmatter."""
    indexed = [
        {"path": "x.md", "category": "", "tags": [], "title": "X"},
    ]
    svc = _make_classification_service(wiki_path, matcher, indexed_docs=indexed)
    pending = svc.find_pending()
    assert pending[0].reason == "no_frontmatter"


def test_pending_finds_new_disk_files(wiki_path: Path, matcher: IgnoreMatcher):
    """인덱스에 없는 디스크 파일은 not_indexed로 잡힘."""
    (wiki_path / "Notes").mkdir()
    (wiki_path / "Notes" / "new.md").write_text("# Hello", encoding="utf-8")

    indexed: list[dict] = []  # 인덱스 비어있음

    svc = _make_classification_service(wiki_path, matcher, indexed_docs=indexed)
    # to_arrow_list() 호출 시 빈 배열이지만 exists()=True여야 인덱스 set 비교 진행
    # 위 헬퍼는 indexed=[]이면 exists=False로 설정하므로 명시적으로 재설정
    svc._vector.exists.return_value = True
    svc._vector.to_arrow_list.return_value = []

    pending = svc.find_pending()
    paths = [p.path for p in pending]
    assert "Notes/new.md" in paths
    assert pending[0].reason == "not_indexed"


def test_pending_skips_dot_directories(wiki_path: Path, matcher: IgnoreMatcher):
    """dot-prefix 디렉토리의 파일은 pending에 포함되지 않음."""
    (wiki_path / ".obsidian").mkdir()
    (wiki_path / ".obsidian" / "config.md").write_text("ignored", encoding="utf-8")
    (wiki_path / "Notes").mkdir()
    (wiki_path / "Notes" / "ok.md").write_text("# Ok", encoding="utf-8")

    svc = _make_classification_service(wiki_path, matcher, indexed_docs=[])
    svc._vector.exists.return_value = True
    svc._vector.to_arrow_list.return_value = []

    pending = svc.find_pending()
    paths = [p.path for p in pending]
    assert "Notes/ok.md" in paths
    assert not any(".obsidian" in p for p in paths)


def test_pending_caches_result(wiki_path: Path, matcher: IgnoreMatcher):
    """find_pending은 60초 TTL로 캐싱됨."""
    fake_time = [1000.0]

    def clock() -> float:
        return fake_time[0]

    indexed = [
        {"path": "x.md", "category": "", "tags": [], "title": "X"},
    ]
    vector = MagicMock()
    vector.exists.return_value = True
    vector.to_arrow_list.return_value = indexed

    document_service = MagicMock()
    document_service.get_similar.return_value = []
    category_service = CategoryService(wiki_path, matcher, vector_repository=vector)

    svc = ClassificationService(
        pages_path=wiki_path,
        vector_repository=vector,
        document_service=document_service,
        category_service=category_service,
        ignore_matcher=matcher,
        clock=clock,
    )

    pending1 = svc.find_pending()
    call_count_1 = vector.to_arrow_list.call_count

    fake_time[0] = 1010.0  # +10초
    pending2 = svc.find_pending()
    call_count_2 = vector.to_arrow_list.call_count

    assert pending1 == pending2
    # 캐시 hit이어야 함 (vector 추가 호출 없음)
    assert call_count_1 == call_count_2


def test_pending_invalidate_clears_cache(wiki_path: Path, matcher: IgnoreMatcher):
    """invalidate 후 다시 조회하면 재계산."""
    indexed = [{"path": "x.md", "category": "", "tags": [], "title": "X"}]
    svc = _make_classification_service(wiki_path, matcher, indexed_docs=indexed)

    svc.find_pending()
    initial_calls = svc._vector.to_arrow_list.call_count

    svc.invalidate()
    svc.find_pending()
    after_invalidate_calls = svc._vector.to_arrow_list.call_count

    assert after_invalidate_calls > initial_calls


def test_pending_limit_respected(wiki_path: Path, matcher: IgnoreMatcher):
    """limit 인자가 결과 개수를 제한."""
    indexed = [
        {"path": f"file{i}.md", "category": "", "tags": [], "title": f"F{i}"}
        for i in range(10)
    ]
    svc = _make_classification_service(wiki_path, matcher, indexed_docs=indexed)
    pending = svc.find_pending(limit=3)
    assert len(pending) == 3


def test_suggest_classification_returns_categories(wiki_path: Path, matcher: IgnoreMatcher):
    """폴더 기반 카테고리가 후보에 포함됨."""
    (wiki_path / "infra").mkdir()
    (wiki_path / "infra" / "nginx.md").write_text(
        "# Nginx\n`nginx` `ssl` 설정 가이드입니다.", encoding="utf-8"
    )
    (wiki_path / "dev").mkdir()
    (wiki_path / "dev" / "py.md").write_text("# Python", encoding="utf-8")

    listing = CategoryListing.of(
        mode="folder", categories=["infra", "dev"], detected_at="2026-04-27T00:00:00+00:00"
    )
    svc = _make_classification_service(
        wiki_path, matcher, indexed_docs=[], listing=listing
    )

    suggestion = svc.suggest_classification("infra/nginx.md")

    assert suggestion.path == "infra/nginx.md"
    # 첫 컴포넌트 'infra'가 카테고리 후보 1순위
    assert "infra" in suggestion.category_candidates
    assert suggestion.category_candidates[0] == "infra"


def test_suggest_classification_extracts_tags(wiki_path: Path, matcher: IgnoreMatcher):
    """본문에서 태그 후보가 추출됨."""
    (wiki_path / "infra").mkdir()
    (wiki_path / "infra" / "nginx.md").write_text(
        "# Nginx 설정\n`nginx` 웹서버 `ssl` 인증서 설정 가이드입니다.",
        encoding="utf-8",
    )

    listing = CategoryListing.of(
        mode="folder", categories=["infra"], detected_at="now"
    )
    svc = _make_classification_service(
        wiki_path, matcher, indexed_docs=[], listing=listing
    )

    suggestion = svc.suggest_classification("infra/nginx.md")

    assert len(suggestion.tag_candidates) > 0


def test_suggest_classification_uses_similar_for_voting(
    wiki_path: Path, matcher: IgnoreMatcher
):
    """유사 문서의 카테고리가 후보 투표에 반영."""
    (wiki_path / "target.md").write_text("# Target\n임의 본문", encoding="utf-8")

    similar = [
        Document.from_dict(
            {"path": "infra/a.md", "category": "infra", "title": "A"}
        ),
        Document.from_dict(
            {"path": "infra/b.md", "category": "infra", "title": "B"}
        ),
        Document.from_dict({"path": "dev/c.md", "category": "dev", "title": "C"}),
    ]
    listing = CategoryListing.of(
        mode="folder", categories=["infra", "dev"], detected_at="now"
    )

    svc = _make_classification_service(
        wiki_path, matcher, indexed_docs=[], similar_docs=similar, listing=listing
    )

    suggestion = svc.suggest_classification("target.md")

    # 'target.md'는 첫 컴포넌트가 카테고리가 아니므로 투표 결과가 1순위
    assert "infra" in suggestion.category_candidates


def test_suggest_classification_calls_get_similar_once(
    wiki_path: Path, matcher: IgnoreMatcher
):
    """유사 문서 조회는 1번만 (카테고리 투표 + 유사경로 표시 공유).

    과거엔 _compute_category_candidates 와 _compute_similar_paths 가 각각
    get_similar 를 호출해 동일 검색을 2번 수행했다.
    """
    (wiki_path / "target.md").write_text("# T\n본문", encoding="utf-8")
    similar = [
        Document.from_dict({"path": "infra/a.md", "category": "infra", "title": "A"}),
    ]
    listing = CategoryListing.of(
        mode="folder", categories=["infra"], detected_at="now"
    )
    svc = _make_classification_service(
        wiki_path, matcher, indexed_docs=[], similar_docs=similar, listing=listing
    )

    suggestion = svc.suggest_classification("target.md")

    # 동작 보존: 카테고리 투표 + 유사경로 둘 다 반영
    assert "infra" in suggestion.category_candidates
    assert "infra/a.md" in suggestion.similar_paths
    # 검색은 1회만
    assert svc._document_service.get_similar.call_count == 1


def test_suggest_classification_raises_on_missing(wiki_path: Path, matcher: IgnoreMatcher):
    """파일이 디스크/인덱스 모두 없으면 예외."""
    svc = _make_classification_service(wiki_path, matcher, indexed_docs=[])
    with pytest.raises(DocumentNotFoundError):
        svc.suggest_classification("missing.md")


def test_suggest_classification_includes_reasoning(
    wiki_path: Path, matcher: IgnoreMatcher
):
    """reasoning에 카테고리/태그 정보 포함."""
    (wiki_path / "Notes").mkdir()
    (wiki_path / "Notes" / "memo.md").write_text(
        "# Memo\nimportant `python` content here.", encoding="utf-8"
    )

    listing = CategoryListing.of(
        mode="folder", categories=["Notes", "Projects"], detected_at="now"
    )
    svc = _make_classification_service(
        wiki_path, matcher, indexed_docs=[], listing=listing
    )

    suggestion = svc.suggest_classification("Notes/memo.md")
    assert suggestion.reasoning  # 비어있지 않음


def test_to_dict_serialization(wiki_path: Path, matcher: IgnoreMatcher):
    """ClassificationSuggestion.to_dict()가 모든 필드 포함."""
    (wiki_path / "Notes").mkdir()
    (wiki_path / "Notes" / "x.md").write_text("# X", encoding="utf-8")

    listing = CategoryListing.of(
        mode="folder", categories=["Notes", "Projects"], detected_at="now"
    )
    svc = _make_classification_service(
        wiki_path, matcher, indexed_docs=[], listing=listing
    )

    suggestion = svc.suggest_classification("Notes/x.md")
    d = suggestion.to_dict()
    assert "path" in d
    assert "category_candidates" in d
    assert "tag_candidates" in d
    assert "similar_paths" in d
    assert "reasoning" in d


# =============================================================================
# v0.2.5: inbox staging 폴더의 .md는 frontmatter 상태와 무관하게 항상 pending
# =============================================================================


def test_pending_includes_staging_files_with_category(wiki_path: Path, matcher: IgnoreMatcher):
    """inbox/foo.md가 인덱스에 category='infra'로 들어가 있어도 pending에 잡혀야 한다.

    이게 없으면 daemon이 inbox에 떨어진 파일을 다시 분류·이동하지 못해
    파일이 staging에 영원히 머무는 silent stuck이 발생.
    """
    indexed = [
        {"path": "inbox/foo.md", "category": "infra", "tags": ["x"], "title": "F"},
        {"path": "infra/normal.md", "category": "infra", "tags": ["y"], "title": "N"},
    ]
    svc = _make_classification_service(wiki_path, matcher, indexed_docs=indexed)
    pending = svc.find_pending()

    by_path = {p.path: p for p in pending}
    assert "inbox/foo.md" in by_path
    assert by_path["inbox/foo.md"].reason == "in_staging"
    # 일반 카테고리 폴더의 파일은 분류 완료로 간주
    assert "infra/normal.md" not in by_path


def test_pending_includes_staging_variant_folders(wiki_path: Path, matcher: IgnoreMatcher):
    """inbox 변형 폴더(0.Inbox, _inbox 등)도 동일하게 in_staging으로 잡혀야 한다."""
    indexed = [
        {"path": "0.Inbox/a.md", "category": "devops", "tags": [], "title": "A"},
        {"path": "_inbox/b.md", "category": "infra", "tags": ["t"], "title": "B"},
        {"path": "Inbox/c.md", "category": "", "tags": [], "title": "C"},
    ]
    svc = _make_classification_service(wiki_path, matcher, indexed_docs=indexed)
    pending = svc.find_pending()

    by_path = {p.path: p for p in pending}
    assert by_path["0.Inbox/a.md"].reason == "in_staging"
    assert by_path["_inbox/b.md"].reason == "in_staging"
    assert by_path["Inbox/c.md"].reason == "in_staging"


def test_pending_includes_staging_disk_files(wiki_path: Path, matcher: IgnoreMatcher):
    """인덱스에 없고 디스크에만 있는 inbox/*.md도 in_staging으로 노출."""
    (wiki_path / "inbox").mkdir()
    (wiki_path / "inbox" / "new.md").write_text("# new", encoding="utf-8")
    (wiki_path / "infra").mkdir()
    (wiki_path / "infra" / "fresh.md").write_text("# fresh", encoding="utf-8")

    # 인덱스에는 아무것도 없음 → 디스크 차집합 루프가 작동
    svc = _make_classification_service(wiki_path, matcher, indexed_docs=[])
    pending = svc.find_pending()

    by_path = {p.path: p for p in pending}
    assert by_path["inbox/new.md"].reason == "in_staging"
    assert by_path["infra/fresh.md"].reason == "not_indexed"
