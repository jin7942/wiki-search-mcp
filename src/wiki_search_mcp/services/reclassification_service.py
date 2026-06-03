"""ReclassificationService — 옛 평탄 배치 파일을 서브폴더로 재배치.

배경:
daemon 의 자동 분류는 inbox(staging) 신규 파일만 대상으로 한다. 이미 카테고리
루트에 평탄하게(``<category>/<basename>``) 자리잡은 옛 파일은 분류 큐에 다시
오르지 않으므로, 0.4.0 의 서브폴더 라우팅 기능이 적용되지 않는다.

이 서비스는 사용자가 명시적으로 실행하는 **일회성 배치**다. 평탄 파일 중
"그 카테고리에 서브폴더 후보가 실제로 존재하는" 것만 골라 LLM 에 재분류시키고,
LLM 이 화이트리스트에 맞는 subcategory 를 산출하면 ``<category>/<subcategory>/``
로 이동한다. 새 서브폴더는 만들지 않는다 (분류기 프롬프트가 금지).

기존 ``ClassifierService.classify()`` 와 ``FrontmatterWriter.apply()`` 를 그대로
재사용하므로, draft/locked/too_short 가드와 서브폴더 화이트리스트 검증, applied.jsonl
기록(rollback 호환)이 자동으로 적용된다.

요요/무한루프 방지:
- ``_collect_flat_candidates`` 가 ``len(parts) != 2`` 로 이미 서브폴더 안에 있는
  파일을 후보에서 제외 → 옮긴 직후 재방문 불가 (1차 방어선).
- ``_decide_target_path`` 가 목적지 == 현재 위치면 이동 안 함 (2차 방어선).
- 일회성 배치라 daemon 의 ``_periodic_rescan`` 처럼 영구 재큐잉되지 않는다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from wiki_search_mcp.core.config import is_staging_folder
from wiki_search_mcp.core.exceptions import ClassifierError, DocumentNotFoundError
from wiki_search_mcp.infrastructure.frontmatter.writer import (
    FrontmatterWriter,
    _decide_target_path,
)
from wiki_search_mcp.infrastructure.jsonl.log import JsonlLog
from wiki_search_mcp.services.classifier_service import ClassifierSkipped

if TYPE_CHECKING:
    from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher
    from wiki_search_mcp.services.category_service import CategoryService
    from wiki_search_mcp.services.classifier_service import ClassifierService

logger = logging.getLogger(__name__)


class ReclassificationService:
    """옛 평탄 파일을 서브폴더로 재배치하는 일회성 배치 오케스트레이터."""

    def __init__(
        self,
        *,
        classifier: "ClassifierService",
        category_service: "CategoryService",
        writer: FrontmatterWriter,
        applied_log: JsonlLog,
        pages_path: Path,
        ignore_matcher: "IgnoreMatcher",
    ):
        self._classifier = classifier
        self._categories = category_service
        self._writer = writer
        self._applied = applied_log
        self._pages = Path(pages_path)
        self._ignore = ignore_matcher

    # --------------------------------------------------------------- 대상 선정
    def _collect_flat_candidates(self, category_filter: str | None) -> list[str]:
        """재분류 대상이 될 평탄 파일 상대경로 목록.

        세 조건을 모두 만족해야 후보:
        1. 첫 컴포넌트가 활성 카테고리이고 staging 폴더가 아니다.
        2. 평탄 배치다 — ``parts == [category, basename]`` (서브폴더 안이면 제외).
        3. 그 카테고리에 서브폴더 후보가 실제로 존재한다 (없으면 LLM 이 어차피
           null 만 낼 것이므로 LLM 호출 비용 낭비를 막는다).
        """
        subfolders = self._categories.list_subfolders()
        listing = self._categories.list_categories()
        active = set(listing.categories)

        candidates: list[str] = []
        if not self._pages.exists():
            return candidates

        for md in self._pages.rglob("*.md"):
            if self._ignore.should_ignore(md):
                continue
            try:
                rel = md.relative_to(self._pages)
            except ValueError:
                continue
            parts = rel.parts
            # 조건2: 평탄 배치만 (카테고리 루트 바로 아래). 이미 서브폴더 안이면
            # parts 가 3개 이상이라 제외 → 요요 차단의 정적 방어선.
            if len(parts) != 2:
                continue
            first = parts[0]
            # 조건1: 활성 카테고리 + staging 제외
            if first not in active or is_staging_folder(first):
                continue
            # 조건3: 그 카테고리에 서브폴더 후보 존재
            if first not in subfolders:
                continue
            if category_filter and first != category_filter:
                continue
            candidates.append(rel.as_posix())

        candidates.sort()
        return candidates

    # ----------------------------------------------------------------- 실행
    async def reclassify(
        self,
        *,
        dry_run: bool = False,
        limit: int = 100,
        category_filter: str | None = None,
        confidence_threshold: float = 0.70,
    ) -> list[dict[str, Any]]:
        """평탄 파일을 재분류해 서브폴더로 이동.

        Args:
            dry_run: True 면 실제 이동/기록 없이 목적지만 계산해 반환.
            limit: 처리할 파일 최대 수 (LLM 비용 상한).
            category_filter: 특정 카테고리만 대상.
            confidence_threshold: 이 값 미만이면 이동 안 함 (평탄 유지).

        Returns:
            파일별 결과 dict 리스트. ``status`` 값:
            moved / would_move / kept_flat / already_placed / low_confidence /
            skipped / error.
        """
        targets = self._collect_flat_candidates(category_filter)
        results: list[dict[str, Any]] = []

        for rel in targets[:limit]:
            full = self._pages / rel
            try:
                mtime_before = full.stat().st_mtime
            except OSError:
                continue

            # 가드: draft/locked/too_short 는 classify() 내부에서 처리됨.
            try:
                decision = await self._classifier.classify(rel)
            except ClassifierSkipped as e:
                results.append({"path": rel, "status": "skipped", "reason": e.reason})
                continue
            except DocumentNotFoundError:
                continue
            except ClassifierError as e:
                results.append(
                    {"path": rel, "status": "error", "reason": str(e)}
                )
                continue

            # subcategory 가 없으면 (화이트리스트 미일치) 이동하지 않고 평탄 유지.
            if not decision.subcategory:
                results.append({"path": rel, "status": "kept_flat"})
                continue

            if decision.confidence < confidence_threshold:
                results.append(
                    {
                        "path": rel,
                        "status": "low_confidence",
                        "confidence": decision.confidence,
                        "subcategory": decision.subcategory,
                    }
                )
                continue

            # 요요 2차 방어선: 목적지가 현재 위치와 같으면 이동 안 함.
            target = _decide_target_path(rel, decision.category, decision.subcategory)
            if target == rel:
                results.append({"path": rel, "status": "already_placed"})
                continue

            if dry_run:
                results.append(
                    {
                        "path": rel,
                        "status": "would_move",
                        "path_after": target,
                        "subcategory": decision.subcategory,
                        "confidence": decision.confidence,
                    }
                )
                continue

            # 분류 중 사용자가 파일을 수정했으면 적용하지 않음.
            try:
                if full.stat().st_mtime != mtime_before:
                    results.append(
                        {
                            "path": rel,
                            "status": "skipped",
                            "reason": "file_changed_during_classify",
                        }
                    )
                    continue
            except OSError:
                continue

            try:
                record = self._writer.apply(rel, decision, move_into_category=True)
            except (OSError, FileNotFoundError) as e:
                results.append({"path": rel, "status": "error", "reason": str(e)})
                continue

            self._applied.append(record.to_dict())
            results.append(
                {
                    "path": rel,
                    "status": "moved",
                    "path_after": record.path_after,
                    "subcategory": decision.subcategory,
                }
            )
            logger.info("reclassified %s -> %s", rel, record.path_after)

        return results
