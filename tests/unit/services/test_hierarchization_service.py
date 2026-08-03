"""HierarchizationService 테스트 (0.7.0 R2).

요청서 수용 기준 2: 계층화 적용 시 서브폴더 생성 + 파일 이동 + frontmatter
갱신 + applied.jsonl 기록(rollback 호환)이 일관되게 수행된다.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiki_search_mcp.core.exceptions import ClassifierError
from wiki_search_mcp.core.utils import parse_frontmatter
from wiki_search_mcp.infrastructure.frontmatter.writer import FrontmatterWriter
from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher
from wiki_search_mcp.infrastructure.jsonl.log import JsonlLog
from wiki_search_mcp.services.classification_service import ClassificationService
from wiki_search_mcp.services.hierarchization_service import HierarchizationService


@pytest.fixture
def wiki_path(tmp_path: Path) -> Path:
    return tmp_path


def _classification_service(wiki_path: Path) -> ClassificationService:
    vector = MagicMock()
    vector.exists.return_value = False
    return ClassificationService(
        pages_path=wiki_path,
        vector_repository=vector,
        document_service=MagicMock(),
        category_service=MagicMock(),
        ignore_matcher=IgnoreMatcher.from_wiki(wiki_path),
    )


def _write(wiki_path: Path, rel: str, body: str = "내용") -> None:
    p = wiki_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\ntags: [x]\n---\n\n{body}", encoding="utf-8")


def _service(
    wiki_path: Path,
    *,
    provider=None,
    rate_acquire=None,
) -> HierarchizationService:
    return HierarchizationService(
        classification_service=_classification_service(wiki_path),
        writer=FrontmatterWriter(wiki_path),
        applied_log=JsonlLog(wiki_path / ".state" / "applied.jsonl"),
        pages_path=wiki_path,
        provider=provider,
        rate_acquire=rate_acquire,
    )


def _seed_meetings(wiki_path: Path, folder: str) -> list[str]:
    names = ["2026-05-19 회의.md", "2026-05-20 회의.md", "2026-05-21 회의.md"]
    for n in names:
        _write(wiki_path, f"{folder}/{n}")
    return [f"{folder}/{n}" for n in names]


class _FakeProvider:
    """complete() 가 준비된 JSON 을 반환하는 가짜 provider."""

    name = "fake"

    def __init__(self, response: str):
        self._response = response
        self.calls = 0

    async def complete(self, prompt: str, *, system_prompt: str) -> str:
        self.calls += 1
        return self._response


def test_plan_heuristic_only_without_provider(wiki_path: Path) -> None:
    """provider 없으면 휴리스틱 계획 (confidence 0.0 — 자동 적용 불가)."""
    _seed_meetings(wiki_path, "projects/P")
    plan = asyncio.run(_service(wiki_path).plan("projects/P"))

    assert plan.provider == "heuristic"
    assert plan.confidence == 0.0
    assert [g.name for g in plan.groups] == ["회의록"]


def test_plan_llm_refines_confidence_and_names(wiki_path: Path) -> None:
    """LLM 응답의 그룹/confidence 를 채택하고 basename→상대경로 복원."""
    rels = _seed_meetings(wiki_path, "projects/P")
    response = json.dumps(
        {
            "groups": [
                {
                    "name": "회의",
                    "files": [Path(r).name for r in rels]
                    + ["없는파일.md"],  # 창작 파일은 무시돼야 함
                }
            ],
            "confidence": 0.85,
            "reasoning": "회의록 묶음",
        },
        ensure_ascii=False,
    )
    provider = _FakeProvider(response)
    acquired = []

    async def rate_acquire() -> None:
        acquired.append(1)

    plan = asyncio.run(
        _service(wiki_path, provider=provider, rate_acquire=rate_acquire).plan(
            "projects/P"
        )
    )

    assert provider.calls == 1
    assert acquired == [1]  # LLM 호출 전 rate 슬롯 1회 획득
    assert plan.confidence == 0.85
    assert plan.provider == "fake"
    assert len(plan.groups) == 1
    assert set(plan.groups[0].files) == set(rels)


def test_plan_llm_tautology_group_dropped(wiki_path: Path) -> None:
    """LLM 이 폴더 주제 동어반복 그룹명을 내면 버리고 휴리스틱으로 폴백."""
    rels = _seed_meetings(wiki_path, "projects/KT_ITPARK")
    response = json.dumps(
        {
            "groups": [{"name": "kt", "files": [Path(r).name for r in rels]}],
            "confidence": 0.9,
            "reasoning": "x",
        }
    )
    plan = asyncio.run(
        _service(wiki_path, provider=_FakeProvider(response)).plan(
            "projects/KT_ITPARK"
        )
    )
    # 유효 그룹이 없으므로 휴리스틱 계획 폴백 (confidence 0.0)
    assert plan.confidence == 0.0
    assert all(g.name.lower() != "kt" for g in plan.groups)


def test_plan_llm_failure_falls_back_to_heuristic(wiki_path: Path) -> None:
    """LLM 호출 실패 시 휴리스틱 계획 (승인 대기 흐름)."""

    class _Failing:
        name = "fail"

        async def complete(self, prompt: str, *, system_prompt: str) -> str:
            raise ClassifierError.of("boom", code="SDK_ERROR")

    _seed_meetings(wiki_path, "projects/P")
    plan = asyncio.run(_service(wiki_path, provider=_Failing()).plan("projects/P"))
    assert plan.provider == "heuristic"
    assert plan.confidence == 0.0
    assert plan.groups  # 휴리스틱 그룹은 유지


def test_apply_moves_files_and_records(wiki_path: Path) -> None:
    """apply: 서브폴더 생성 + 이동 + subcategory 갱신 + applied.jsonl 기록."""
    rels = _seed_meetings(wiki_path, "projects/P")
    svc = _service(wiki_path)
    plan = asyncio.run(svc.plan("projects/P"))

    results = svc.apply(plan)

    assert all(r["status"] == "moved" for r in results)
    for rel in rels:
        assert not (wiki_path / rel).exists()
        new_path = wiki_path / "projects/P/회의록" / Path(rel).name
        assert new_path.exists()
        meta, _ = parse_frontmatter(new_path.read_text(encoding="utf-8"))
        assert meta["subcategory"] == "P/회의록"

    # applied.jsonl — rollback 호환 필드 존재
    lines = (
        (wiki_path / ".state" / "applied.jsonl")
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()
    )
    assert len(lines) == 3
    rec = json.loads(lines[0])
    assert rec["path_before"] in rels
    assert rec["path_after"].startswith("projects/P/회의록/")
    assert rec["decision"]["type"] == "hierarchization"
    assert "frontmatter_before" in rec


def test_apply_category_root_folder(wiki_path: Path) -> None:
    """카테고리 루트 폴더(devops 등)는 subcategory 가 그룹명 자체."""
    _seed_meetings(wiki_path, "devops")
    svc = _service(wiki_path)
    plan = asyncio.run(svc.plan("devops"))
    results = svc.apply(plan)

    assert all(r["status"] == "moved" for r in results)
    moved = wiki_path / "devops/회의록/2026-05-19 회의.md"
    meta, _ = parse_frontmatter(moved.read_text(encoding="utf-8"))
    assert meta["subcategory"] == "회의록"


def test_apply_rejects_invalid_group_name(wiki_path: Path) -> None:
    """경로 구분자가 든 그룹명은 적용하지 않는다."""
    from wiki_search_mcp.core.models import HierarchizationPlan, SubfolderGroup

    _write(wiki_path, "projects/P/a.md")
    svc = _service(wiki_path)
    plan = HierarchizationPlan(
        folder="projects/P",
        groups=(SubfolderGroup(name="../evil", files=("projects/P/a.md",)),),
    )
    results = svc.apply(plan)
    assert results == [
        {"group": "../evil", "status": "error", "reason": "invalid_name"}
    ]
    assert (wiki_path / "projects/P/a.md").exists()
