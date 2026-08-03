"""DaemonRunner._structure_pass 테스트 (0.7.0 R2/R4).

health_check 임계 초과 폴더에 대해:
- confidence ≥ threshold → 자동 적용 + 재인덱싱 + hierarchized_count 증가
- confidence < threshold → pending.jsonl 에 ``hierarchization`` 승인 대기 기록
- 파일명 정규화 후보 → pending 에 ``filename_normalization`` 노출 (적용 없음)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki_search_mcp.core.models import (
    FilenameNormalization,
    FilenameRename,
    FolderHealth,
    HealthReport,
    HierarchizationPlan,
    SubfolderGroup,
)


@pytest.fixture(autouse=True)
def _xdg_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _build_runner(wiki: Path, **opt_kw):
    from wiki_search_mcp.infrastructure.daemon.options import DaemonOptions
    from wiki_search_mcp.infrastructure.daemon.runner import DaemonRunner

    opts = DaemonOptions(
        wiki_path=wiki, provider_factory=lambda: MagicMock(), **opt_kw
    )
    with patch(
        "wiki_search_mcp.infrastructure.daemon.runner.WikiIndexer"
    ), patch(
        "wiki_search_mcp.infrastructure.daemon.runner.ServiceContainer"
    ) as fake_container_cls, patch(
        "wiki_search_mcp.infrastructure.daemon.runner.ClassifierService"
    ):
        fake_container = MagicMock()
        fake_container.pages_path = wiki / "pages"
        fake_container_cls.return_value = fake_container
        runner = DaemonRunner(opts)
    runner._pending = MagicMock()
    runner._status = MagicMock()
    runner._container = fake_container
    return runner, fake_container


def _report(folder: str) -> HealthReport:
    return HealthReport(
        needs_hierarchization=(FolderHealth(path=folder, file_count=27),)
    )


def _plan(folder: str, confidence: float) -> HierarchizationPlan:
    return HierarchizationPlan(
        folder=folder,
        groups=(SubfolderGroup(name="회의록", files=(f"{folder}/a.md",)),),
        confidence=confidence,
        provider="fake",
    )


def _no_norm(svc) -> None:
    svc.suggest_filename_normalization.return_value = FilenameNormalization()


def test_high_confidence_auto_applies(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    (wiki / "pages").mkdir(parents=True)
    runner, container = _build_runner(wiki)
    svc = container.classification_service
    svc.health_check.return_value = _report("projects/P")
    _no_norm(svc)

    runner._hierarchizer = MagicMock()
    runner._hierarchizer.plan = AsyncMock(return_value=_plan("projects/P", 0.9))
    runner._hierarchizer.apply.return_value = [
        {"path": "projects/P/a.md", "status": "moved"}
    ]

    asyncio.run(runner._structure_pass())

    runner._hierarchizer.apply.assert_called_once()
    runner._indexer.reindex.assert_called_once_with(full=False)
    assert any(
        c.args[0] == "hierarchized_count"
        for c in runner._status.increment.call_args_list
    )
    runner._pending.append.assert_not_called()


def test_low_confidence_goes_to_pending(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    (wiki / "pages").mkdir(parents=True)
    runner, container = _build_runner(wiki)
    svc = container.classification_service
    svc.health_check.return_value = _report("projects/P")
    _no_norm(svc)

    runner._hierarchizer = MagicMock()
    runner._hierarchizer.plan = AsyncMock(return_value=_plan("projects/P", 0.4))

    asyncio.run(runner._structure_pass())

    runner._hierarchizer.apply.assert_not_called()
    entry = runner._pending.append.call_args.args[0]
    assert entry["path"] == "projects/P"
    assert entry["reason"] == "hierarchization"
    assert entry["confidence"] == 0.4
    assert entry["plan"]["groups"][0]["name"] == "회의록"
    # 쿨다운 등록 — 매 주기 LLM 재계획 방지
    assert "projects/P" in runner._structure_cooldown


def test_auto_hierarchize_disabled_always_pending(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    (wiki / "pages").mkdir(parents=True)
    runner, container = _build_runner(wiki, auto_hierarchize=False)
    svc = container.classification_service
    svc.health_check.return_value = _report("projects/P")
    _no_norm(svc)

    runner._hierarchizer = MagicMock()
    runner._hierarchizer.plan = AsyncMock(return_value=_plan("projects/P", 0.95))

    asyncio.run(runner._structure_pass())

    runner._hierarchizer.apply.assert_not_called()
    assert runner._pending.append.call_args.args[0]["reason"] == "hierarchization"


def test_filename_normalization_exposed_as_pending(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    (wiki / "pages").mkdir(parents=True)
    runner, container = _build_runner(wiki)
    svc = container.classification_service
    svc.health_check.return_value = HealthReport()
    svc.suggest_filename_normalization.return_value = FilenameNormalization(
        candidates=(
            FilenameRename(
                current="projects/P/26.05.11 회의.md",
                suggested="projects/P/2026-05-11 회의.md",
            ),
        )
    )

    runner._hierarchizer = MagicMock()

    asyncio.run(runner._structure_pass())

    entry = runner._pending.append.call_args.args[0]
    assert entry["reason"] == "filename_normalization"
    assert entry["count"] == 1
