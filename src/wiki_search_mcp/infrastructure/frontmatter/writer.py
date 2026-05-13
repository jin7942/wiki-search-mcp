"""Atomic frontmatter writer.

Daemon이 자동 분류 결과를 .md 파일에 반영할 때 사용합니다.

원칙:
- **사용자 값 우선**: 사용자가 이미 작성한 frontmatter 필드는 절대 덮어쓰지 않는다.
  ``category`` / ``tags``는 머지 (사용자 값 보존 + 모자란 만큼만 보강).
- **원자적 쓰기**: 같은 디렉토리에 ``.tmp`` 파일 생성 → fsync → ``os.replace``.
  중간에 프로세스가 죽어도 원본은 그대로 유지된다.
- **카테고리 폴더 이동**: ``move_into_category=True``면 첫 path 컴포넌트가 카테고리와
  다를 때 ``<category>/<basename>``으로 이동. 같은 이름이 이미 있으면 ``-1`` 접미사.
- **본문 무수정**: ``body`` 영역은 파일에서 읽은 바이트를 그대로 재기록한다.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wiki_search_mcp.core.models import AppliedRecord, ClassificationDecision
from wiki_search_mcp.core.types import FrontmatterDict
from wiki_search_mcp.core.utils import parse_frontmatter, render_frontmatter

logger = logging.getLogger(__name__)


def _utc_iso_now() -> str:
    """현재 UTC 시각을 ISO 8601 문자열로 반환."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _merge_tags(existing: list[str], suggested: list[str]) -> list[str]:
    """기존 + 추천 태그를 대소문자 무시 dedup, 사용자 순서 보존."""
    seen: set[str] = set()
    out: list[str] = []
    for t in [*existing, *suggested]:
        if not isinstance(t, str):
            continue
        norm = t.strip()
        if not norm:
            continue
        key = norm.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    return out


def _atomic_write(target: Path, content: str) -> None:
    """tmp → fsync → replace 패턴으로 원자적 쓰기."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fp:
            fp.write(content)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, target)
    except Exception:
        # 실패 시 tmp 정리. 원본은 건드리지 않았으므로 안전.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _decide_target_path(rel_path: str, category: str) -> str:
    """카테고리 폴더로 이동할 새 상대 경로 결정.

    - 첫 컴포넌트가 이미 ``category``이면 그대로 유지.
    - 아니면 ``<category>/<basename>``로 이동.
    - 동일 basename이 대상에 이미 있으면 호출자가 직접 충돌 회피 (여기서는 경로만 계산).
    """
    parts = Path(rel_path).parts
    basename = Path(rel_path).name
    if parts and parts[0] == category:
        return rel_path
    return str(Path(category) / basename)


def _avoid_collision(pages: Path, rel: str) -> str:
    """대상 경로에 파일이 이미 있으면 ``-1``, ``-2`` 접미사를 붙여 회피."""
    target = pages / rel
    if not target.exists():
        return rel
    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    for i in range(1, 100):
        candidate = parent / f"{stem}-{i}{suffix}"
        if not candidate.exists():
            return str(candidate.relative_to(pages))
    raise OSError(f"too many collisions for {rel}")


class FrontmatterWriter:
    """frontmatter 적용 + 파일 이동을 원자적으로 수행."""

    def __init__(self, pages_path: Path):
        self._pages = Path(pages_path)

    def apply(
        self,
        rel_path: str,
        decision: ClassificationDecision,
        *,
        move_into_category: bool = True,
    ) -> AppliedRecord:
        """분류 결정을 파일에 반영하고 AppliedRecord를 반환.

        Args:
            rel_path: pages 기준 상대 경로
            decision: LLM 분류 결과
            move_into_category: True면 카테고리 폴더로 이동

        Returns:
            적용 내역을 담은 AppliedRecord (audit/rollback용)

        Raises:
            FileNotFoundError: 대상 파일이 없을 때
            OSError: 쓰기 실패 (디스크 가득 / 권한 / 충돌)
        """
        source = self._pages / rel_path
        content = source.read_text(encoding="utf-8")
        meta_before, body = parse_frontmatter(content)
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()

        meta_after: FrontmatterDict = dict(meta_before)

        # 사용자 값 우선: 이미 category 있으면 그대로
        if not meta_after.get("category"):
            meta_after["category"] = decision.category

        existing_tags = list(meta_after.get("tags") or [])
        merged_tags = _merge_tags(existing_tags, list(decision.tags))
        if merged_tags != existing_tags:
            meta_after["tags"] = merged_tags

        meta_after.setdefault("confidence_score", int(decision.confidence * 100))
        meta_after.setdefault("state", "draft")
        meta_after["updated"] = _utc_iso_now()
        meta_after.setdefault("created", meta_after["updated"])

        new_content = render_frontmatter(meta_after, body)

        target_rel = rel_path
        if move_into_category:
            tentative = _decide_target_path(rel_path, str(meta_after["category"]))
            if tentative != rel_path:
                target_rel = _avoid_collision(self._pages, tentative)

        target = self._pages / target_rel
        _atomic_write(target, new_content)
        if target_rel != rel_path:
            # 원본 위치에서 삭제 (atomic rename은 cross-dir에선 보장 안 되므로 명시적으로 처리)
            try:
                source.unlink()
            except FileNotFoundError:
                pass

        logger.info(
            "frontmatter applied: %s -> %s (category=%s, confidence=%.2f)",
            rel_path,
            target_rel,
            meta_after.get("category"),
            decision.confidence,
        )

        return AppliedRecord(
            path_before=rel_path,
            path_after=target_rel,
            frontmatter_before=dict(meta_before),
            frontmatter_after=dict(meta_after),
            decision=decision.to_dict(),
            applied_at=meta_after["updated"],
            sha256_before=sha,
        )

    def restore(
        self,
        record_path_after: str,
        record_path_before: str,
        frontmatter_before: dict[str, Any],
    ) -> None:
        """rollback: applied된 파일을 원상복구.

        Args:
            record_path_after: 현재 위치 (변경 후 경로)
            record_path_before: 원래 위치
            frontmatter_before: 원래 frontmatter (없으면 ``{}``)
        """
        cur = self._pages / record_path_after
        if not cur.exists():
            raise FileNotFoundError(f"applied file missing: {record_path_after}")
        content = cur.read_text(encoding="utf-8")
        _, body = parse_frontmatter(content)
        restored = render_frontmatter(frontmatter_before, body) if frontmatter_before else body.rstrip("\n") + "\n"
        target = self._pages / record_path_before
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, restored)
        if target != cur:
            try:
                cur.unlink()
            except FileNotFoundError:
                pass
