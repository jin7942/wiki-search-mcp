"""CategoryService.list_subfolders v0.4.0 회귀 테스트.

분류기가 평탄 배치 대신 적절한 프로젝트 서브폴더로 라우팅하려면 카테고리별
1-depth 서브폴더 트리를 LLM 에 힌트로 줘야 한다. 본 테스트는 list_subfolders 가:

- 각 카테고리의 1-depth 디렉토리만 반환 (재귀 X)
- staging / ignore 패턴 폴더는 제외
- 서브폴더 없는 카테고리는 결과 키에서 빠짐
- 결과는 카테고리/서브폴더 모두 사전순 정렬
"""

from __future__ import annotations

from pathlib import Path

from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher
from wiki_search_mcp.services.category_service import CategoryService


def _service(pages: Path) -> CategoryService:
    return CategoryService(pages, IgnoreMatcher.from_wiki(pages))


def test_list_subfolders_basic(tmp_path: Path) -> None:
    pages = tmp_path
    # 카테고리 3개 (CATEGORY_FOLDER_THRESHOLD 보장 위해 충분히)
    for cat in ("projects", "personal", "infra"):
        (pages / cat).mkdir()
    (pages / "projects" / "myproj").mkdir()
    (pages / "projects" / "kbs").mkdir()
    (pages / "personal" / "budget-app").mkdir()
    # infra 는 서브폴더 없음

    subs = _service(pages).list_subfolders()
    assert subs == {
        "projects": ("kbs", "myproj"),  # 사전순
        "personal": ("budget-app",),
    }
    assert "infra" not in subs


def test_list_subfolders_excludes_staging(tmp_path: Path) -> None:
    """카테고리 안에 inbox/staging 같은 폴더가 있어도 서브카테고리로 제안하지 않는다."""
    pages = tmp_path
    for cat in ("projects", "personal", "infra"):
        (pages / cat).mkdir()
    (pages / "projects" / "inbox").mkdir()   # staging 변형 — 제외 대상
    (pages / "projects" / "real").mkdir()

    subs = _service(pages).list_subfolders()
    assert subs.get("projects") == ("real",)


def test_list_subfolders_ignores_files(tmp_path: Path) -> None:
    pages = tmp_path
    for cat in ("projects", "personal", "infra"):
        (pages / cat).mkdir()
    (pages / "projects" / "note.md").write_text("x", encoding="utf-8")  # 파일은 제외
    (pages / "projects" / "real").mkdir()

    subs = _service(pages).list_subfolders()
    assert subs.get("projects") == ("real",)


def test_list_subfolders_does_not_recurse(tmp_path: Path) -> None:
    pages = tmp_path
    for cat in ("projects", "personal", "infra"):
        (pages / cat).mkdir()
    (pages / "projects" / "myproj").mkdir()
    (pages / "projects" / "myproj" / "deep").mkdir()  # 2-depth — 노출 안 됨

    subs = _service(pages).list_subfolders()
    assert subs.get("projects") == ("myproj",)
