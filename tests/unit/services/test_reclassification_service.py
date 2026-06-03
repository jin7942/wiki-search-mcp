"""ReclassificationService 회귀 테스트 (v0.5.0, 옛 평탄 파일 재배치).

핵심 보장:
- 평탄 파일 + 일치하는 서브폴더 후보 → 서브폴더로 이동.
- 이미 서브폴더 안에 있는 파일은 후보가 아님 (요요/무한루프 방지의 1차 방어선).
- subcategory=null (화이트리스트 미일치) → 평탄 유지, applied 미기록.
- 목적지 == 현재 위치 → already_placed 스킵 (2차 방어선).
- 서브폴더 없는 카테고리의 평탄 파일은 LLM 호출조차 안 함.
- draft/locked → 가드로 skipped.
- dry-run 은 파일을 옮기지 않는다.
- 생성한 AppliedRecord 는 rollback 으로 되돌릴 수 있다.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiki_search_mcp.core.models import (
    ClassificationDecision,
    ClassificationSuggestion,
)
from wiki_search_mcp.infrastructure.frontmatter.writer import FrontmatterWriter
from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher
from wiki_search_mcp.infrastructure.jsonl.log import JsonlLog
from wiki_search_mcp.services.category_service import CategoryService
from wiki_search_mcp.services.classifier_service import ClassifierService
from wiki_search_mcp.services.reclassification_service import ReclassificationService


class _ScriptedProvider:
    """경로별로 미리 정한 decision 을 반환하는 가짜 provider.

    ``scripts``: {rel_path: (subcategory|None, confidence)}. 기본은 (None, 0.9).
    """

    name = "fake"

    def __init__(self, scripts: dict[str, tuple[str | None, float]] | None = None):
        self._scripts = scripts or {}
        self.calls: list[str] = []

    async def classify(self, req):  # type: ignore[no-untyped-def]
        self.calls.append(req.path)
        sub, conf = self._scripts.get(req.path, (None, 0.9))
        # category 는 평탄 파일의 첫 컴포넌트를 그대로 둔다 (writer 가 기존 값 우선).
        category = req.path.split("/", 1)[0]
        return ClassificationDecision(
            path=req.path,
            category=category,
            subcategory=sub,
            tags=(),
            confidence=conf,
            reasoning="r",
            provider="fake",
            raw_response="",
        )

    async def healthcheck(self) -> None:
        return


def _write_md(pages: Path, rel: str, category: str, body: str = "x" * 300) -> Path:
    p = pages / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\ncategory: {category}\n---\n{body}\n", encoding="utf-8")
    return p


def _make_service(
    pages: Path, provider: _ScriptedProvider, applied: JsonlLog
) -> ReclassificationService:
    ignore = IgnoreMatcher.from_wiki(pages.parent)
    categories = CategoryService(pages_path=pages, ignore_matcher=ignore)
    # suggest_classification 은 휴리스틱 힌트 생성용이라 재분류 동작과 무관.
    # 실제 의존성(vector/document)을 끌어오지 않도록 stub 한다.
    suggest = MagicMock()
    suggest.suggest_classification.side_effect = lambda rel: ClassificationSuggestion.of(
        path=rel,
        category_candidates=[rel.split("/", 1)[0]],
        tag_candidates=(),
        similar_paths=(),
        reasoning="",
    )
    classifier = ClassifierService(
        classification_service=suggest,
        category_service=categories,
        provider=provider,
        pages_path=pages,
    )
    writer = FrontmatterWriter(pages)
    return ReclassificationService(
        classifier=classifier,
        category_service=categories,
        writer=writer,
        applied_log=applied,
        pages_path=pages,
        ignore_matcher=ignore,
    )


@pytest.fixture
def pages(tmp_path: Path) -> Path:
    p = tmp_path / "wiki" / "pages"
    p.mkdir(parents=True)
    # 두 개 이상의 카테고리 폴더가 있어야 folder 모드로 인식됨 (threshold=2).
    (p / "projects").mkdir()
    (p / "personal").mkdir()
    # projects 에 서브폴더 후보 하나 (사용자가 미리 만든 것).
    (p / "projects" / "KT").mkdir()
    return p


@pytest.mark.asyncio
async def test_flat_file_with_subcategory_is_moved(pages: Path, tmp_path: Path) -> None:
    _write_md(pages, "projects/vpn.md", "projects")
    provider = _ScriptedProvider({"projects/vpn.md": ("KT", 0.95)})
    applied = JsonlLog(tmp_path / "applied.jsonl")
    svc = _make_service(pages, provider, applied)

    results = await svc.reclassify(dry_run=False)

    assert any(r["status"] == "moved" for r in results)
    assert not (pages / "projects" / "vpn.md").exists()
    assert (pages / "projects" / "KT" / "vpn.md").exists()
    # applied.jsonl 에 정상 스키마로 기록 (rollback 호환).
    rows = applied.tail(10)
    assert rows and rows[-1]["path_after"] == "projects/KT/vpn.md"


@pytest.mark.asyncio
async def test_already_nested_file_is_never_a_candidate(
    pages: Path, tmp_path: Path
) -> None:
    # 이미 서브폴더 안에 있는 파일 — 후보가 되면 안 됨 (요요 방지 1차 방어선).
    _write_md(pages, "projects/KT/already.md", "projects")
    provider = _ScriptedProvider({"projects/KT/already.md": ("KT", 0.99)})
    applied = JsonlLog(tmp_path / "applied.jsonl")
    svc = _make_service(pages, provider, applied)

    results = await svc.reclassify(dry_run=False)

    assert results == []  # 후보 0건
    assert provider.calls == []  # LLM 호출 안 함
    assert (pages / "projects" / "KT" / "already.md").exists()


@pytest.mark.asyncio
async def test_subcategory_null_keeps_flat(pages: Path, tmp_path: Path) -> None:
    _write_md(pages, "projects/misc.md", "projects")
    provider = _ScriptedProvider({"projects/misc.md": (None, 0.9)})
    applied = JsonlLog(tmp_path / "applied.jsonl")
    svc = _make_service(pages, provider, applied)

    results = await svc.reclassify(dry_run=False)

    assert [r["status"] for r in results] == ["kept_flat"]
    assert (pages / "projects" / "misc.md").exists()  # 그대로
    assert applied.tail(10) == []  # 미기록


@pytest.mark.asyncio
async def test_low_confidence_keeps_flat(pages: Path, tmp_path: Path) -> None:
    _write_md(pages, "projects/maybe.md", "projects")
    provider = _ScriptedProvider({"projects/maybe.md": ("KT", 0.40)})
    applied = JsonlLog(tmp_path / "applied.jsonl")
    svc = _make_service(pages, provider, applied)

    results = await svc.reclassify(dry_run=False, confidence_threshold=0.70)

    assert [r["status"] for r in results] == ["low_confidence"]
    assert (pages / "projects" / "maybe.md").exists()


@pytest.mark.asyncio
async def test_category_without_subfolders_skipped(pages: Path, tmp_path: Path) -> None:
    # personal 에는 서브폴더 후보가 없음 → 후보에서 제외, LLM 호출 안 함.
    _write_md(pages, "personal/diary.md", "personal")
    provider = _ScriptedProvider({"personal/diary.md": ("anything", 0.99)})
    applied = JsonlLog(tmp_path / "applied.jsonl")
    svc = _make_service(pages, provider, applied)

    results = await svc.reclassify(dry_run=False)

    assert results == []
    assert provider.calls == []


@pytest.mark.asyncio
async def test_dry_run_does_not_move(pages: Path, tmp_path: Path) -> None:
    _write_md(pages, "projects/vpn.md", "projects")
    provider = _ScriptedProvider({"projects/vpn.md": ("KT", 0.95)})
    applied = JsonlLog(tmp_path / "applied.jsonl")
    svc = _make_service(pages, provider, applied)

    results = await svc.reclassify(dry_run=True)

    assert [r["status"] for r in results] == ["would_move"]
    assert results[0]["path_after"] == "projects/KT/vpn.md"
    assert (pages / "projects" / "vpn.md").exists()  # 안 옮김
    assert applied.tail(10) == []  # 미기록


@pytest.mark.asyncio
async def test_locked_file_skipped(pages: Path, tmp_path: Path) -> None:
    p = pages / "projects" / "wip.md"
    p.write_text("---\ncategory: projects\nlocked: true\n---\n" + "x" * 300, encoding="utf-8")
    provider = _ScriptedProvider({"projects/wip.md": ("KT", 0.99)})
    applied = JsonlLog(tmp_path / "applied.jsonl")
    svc = _make_service(pages, provider, applied)

    results = await svc.reclassify(dry_run=False)

    assert [r["status"] for r in results] == ["skipped"]
    assert results[0]["reason"] == "user_locked"
    assert (pages / "projects" / "wip.md").exists()


@pytest.mark.asyncio
async def test_category_filter(pages: Path, tmp_path: Path) -> None:
    (pages / "domain").mkdir()
    (pages / "domain" / "sub").mkdir()
    _write_md(pages, "projects/a.md", "projects")
    _write_md(pages, "domain/b.md", "domain")
    provider = _ScriptedProvider(
        {"projects/a.md": ("KT", 0.95), "domain/b.md": ("sub", 0.95)}
    )
    applied = JsonlLog(tmp_path / "applied.jsonl")
    svc = _make_service(pages, provider, applied)

    results = await svc.reclassify(dry_run=True, category_filter="projects")

    assert [r["path"] for r in results] == ["projects/a.md"]
    assert provider.calls == ["projects/a.md"]


@pytest.mark.asyncio
async def test_rollback_restores_reclassified_move(pages: Path, tmp_path: Path) -> None:
    from wiki_search_mcp.services.rollback_service import RollbackService

    _write_md(pages, "projects/vpn.md", "projects")
    provider = _ScriptedProvider({"projects/vpn.md": ("KT", 0.95)})
    applied = JsonlLog(tmp_path / "applied.jsonl")
    svc = _make_service(pages, provider, applied)

    await svc.reclassify(dry_run=False)
    assert (pages / "projects" / "KT" / "vpn.md").exists()

    rb = RollbackService(applied_log=applied, pages_path=pages)
    rb_results = rb.rollback_last(1)

    assert rb_results[0]["status"] == "restored"
    assert (pages / "projects" / "vpn.md").exists()
    assert not (pages / "projects" / "KT" / "vpn.md").exists()
