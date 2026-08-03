"""HierarchizationService — 평면 누적 폴더의 서브폴더 계층화 계획/적용.

배경 (0.7.0):
``wiki_health_check`` 가 평면 누적 폴더를 경고해도 이를 소비해 계층을 만드는
주체가 제품 안에 없었다. 이 서비스가 그 실행 주체다.

흐름:
1. ``plan()`` — ``ClassificationService.suggest_subfolders`` (휴리스틱: 시리즈/
   문서유형/태그) 로 초안을 만들고, LLM provider 가 있으면 검증/정제해
   confidence 를 산출한다. LLM 실패 시 휴리스틱 초안에 confidence 0.0
   (자동 적용 불가, 승인 대기).
2. ``apply()`` — 서브폴더 생성 + 파일 이동 + frontmatter(subcategory) 갱신 +
   inbound wikilink 보정 + applied.jsonl 기록. 재인덱싱은 호출자(daemon/CLI)
   책임.

daemon 은 confidence ≥ threshold 면 자동 적용, 미만이면 pending.jsonl 에
``hierarchization`` 항목으로 기록한다 (기존 분류 파이프라인과 동일 정책).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from wiki_search_mcp.core.exceptions import ClassifierError
from wiki_search_mcp.core.models import HierarchizationPlan, SubfolderGroup
from wiki_search_mcp.services.classification_service import ClassificationService
from wiki_search_mcp.services.llm.prompt import (
    HIERARCHIZE_SYSTEM_PROMPT,
    build_hierarchize_prompt,
    parse_hierarchization,
)

if TYPE_CHECKING:
    from wiki_search_mcp.infrastructure.frontmatter.writer import FrontmatterWriter
    from wiki_search_mcp.infrastructure.jsonl.log import JsonlLog

logger = logging.getLogger(__name__)


class HierarchizationService:
    """평면 폴더 계층화의 계획(plan)과 적용(apply)을 담당."""

    def __init__(
        self,
        *,
        classification_service: ClassificationService,
        writer: "FrontmatterWriter",
        applied_log: "JsonlLog",
        pages_path: Path,
        provider: Any | None = None,
        rate_acquire: Callable[[], Awaitable[None]] | None = None,
    ):
        """HierarchizationService.

        Args:
            classification_service: 휴리스틱 서브폴더 제안 소스.
            writer: 파일 이동/frontmatter 갱신 (``move_to``).
            applied_log: applied.jsonl (rollback 호환 기록).
            pages_path: pages 루트.
            provider: ``complete(prompt, system_prompt=...)`` 를 제공하는 LLM
                provider. None 이면 휴리스틱 초안만 반환 (confidence 0.0).
            rate_acquire: LLM 호출 직전 rate-limit 슬롯 획득 함수 (daemon 공유).
        """
        self._suggest = classification_service
        self._writer = writer
        self._applied = applied_log
        self._pages = Path(pages_path)
        self._provider = provider
        self._rate_acquire = rate_acquire

    # ------------------------------------------------------------------- plan
    async def plan(
        self, folder: str, *, min_cluster_size: int = 3
    ) -> HierarchizationPlan:
        """폴더 계층화 계획 생성.

        Args:
            folder: 대상 폴더 상대 경로(pages 기준).
            min_cluster_size: 서브폴더 최소 파일 수.

        Returns:
            HierarchizationPlan. 그룹이 없으면 빈 계획(적용 대상 아님).

        Raises:
            InvalidPathError: 경로 검증 실패.
            RateLimitError: rate-limit 대기 한도 초과 (LLM 검증 시).
        """
        suggestion = self._suggest.suggest_subfolders(
            folder, min_cluster_size=min_cluster_size
        )
        heuristic = HierarchizationPlan(
            folder=suggestion.folder,
            groups=suggestion.groups,
            unclassified=suggestion.unclassified,
            confidence=0.0,
            reasoning=suggestion.reasoning,
            provider="heuristic",
        )
        if not suggestion.groups or self._provider is None:
            return heuristic
        return await self._refine_with_llm(heuristic)

    async def _refine_with_llm(
        self, heuristic: HierarchizationPlan
    ) -> HierarchizationPlan:
        """LLM 으로 휴리스틱 계획을 검증/정제해 confidence 산출.

        LLM 호출/파싱 실패 시 휴리스틱 계획(confidence 0.0)으로 폴백해
        승인 대기로 흐르게 한다. RateLimitError 는 전파(호출자가 재시도 판단).
        """
        all_files: list[str] = sorted(
            {f for g in heuristic.groups for f in g.files}
            | set(heuristic.unclassified)
        )
        # LLM 에는 basename 만 노출 (토큰 절약 + 경로 창작 여지 제거).
        base_of = {f: Path(f).name for f in all_files}
        rel_of = {v: k for k, v in base_of.items()}
        heuristic_groups = [
            {"name": g.name, "files": [base_of[f] for f in g.files]}
            for g in heuristic.groups
        ]
        prompt = build_hierarchize_prompt(
            heuristic.folder, sorted(rel_of), heuristic_groups
        )

        if self._rate_acquire is not None:
            await self._rate_acquire()
        try:
            raw = await self._provider.complete(
                prompt, system_prompt=HIERARCHIZE_SYSTEM_PROMPT
            )
            groups_raw, confidence, reasoning = parse_hierarchization(
                raw=raw, allowed_files=sorted(rel_of)
            )
        except ClassifierError as e:
            logger.warning(
                "hierarchization LLM refine failed for %s (fallback to heuristic): %s",
                heuristic.folder,
                e,
            )
            return heuristic

        stop = ClassificationService._folder_stop_signals(heuristic.folder)
        groups: list[SubfolderGroup] = []
        assigned: set[str] = set()
        for g in groups_raw:
            name = g["name"]
            # 최종 방어선: 폴더 주제 동어반복 그룹명 금지 (프롬프트에도 명시).
            if name.lower() in stop:
                logger.warning(
                    "dropping tautological group %r for %s", name, heuristic.folder
                )
                continue
            files = tuple(rel_of[b] for b in g["files"])
            assigned.update(files)
            groups.append(
                SubfolderGroup(
                    name=name, files=files, signal="LLM 검증 그룹"
                )
            )

        if not groups:
            return heuristic
        unclassified = tuple(f for f in all_files if f not in assigned)
        provider_name = getattr(self._provider, "name", "llm")
        return HierarchizationPlan(
            folder=heuristic.folder,
            groups=tuple(groups),
            unclassified=unclassified,
            confidence=confidence,
            reasoning=reasoning,
            provider=str(provider_name),
        )

    # ------------------------------------------------------------------ apply
    def apply(self, plan: HierarchizationPlan) -> list[dict[str, Any]]:
        """계획을 실행: 서브폴더 생성 + 이동 + frontmatter + 링크보정 + 기록.

        재인덱싱은 하지 않는다 (호출자가 이동 완료 후 1회 수행).

        Args:
            plan: 적용할 계획. confidence 검증은 호출자 책임 (daemon 은
                threshold 비교, CLI 수동 실행은 사용자 승인 자체가 게이트).

        Returns:
            파일별 결과 dict 리스트. ``status``: moved / error.
        """
        folder_parts = Path(plan.folder).parts
        sub_prefix = "/".join(folder_parts[1:])  # 카테고리 기준 상대 경로

        results: list[dict[str, Any]] = []
        for group in plan.groups:
            name = group.name.strip()
            if not name or "/" in name or "\\" in name or name.startswith("."):
                results.append(
                    {"group": group.name, "status": "error", "reason": "invalid_name"}
                )
                continue
            subcategory = f"{sub_prefix}/{name}" if sub_prefix else name
            for rel in group.files:
                target_rel = f"{plan.folder}/{name}/{Path(rel).name}"
                try:
                    record = self._writer.move_to(
                        rel,
                        target_rel,
                        subcategory=subcategory,
                        op="hierarchization",
                    )
                except FileNotFoundError:
                    results.append(
                        {"path": rel, "status": "error", "reason": "file_missing"}
                    )
                    continue
                except OSError as e:
                    results.append(
                        {"path": rel, "status": "error", "reason": str(e)}
                    )
                    continue
                self._applied.append(record.to_dict())
                results.append(
                    {
                        "path": rel,
                        "status": "moved",
                        "path_after": record.path_after,
                        "group": name,
                    }
                )
        moved = sum(1 for r in results if r.get("status") == "moved")
        logger.info(
            "hierarchization applied for %s: %d moved, %d error(s)",
            plan.folder,
            moved,
            len(results) - moved,
        )
        return results
