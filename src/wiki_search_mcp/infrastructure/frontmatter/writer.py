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
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wiki_search_mcp.core.config import is_staging_folder
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


def decide_target_path(
    rel_path: str, category: str, subcategory: str | None = None
) -> str:
    """카테고리(+서브카테고리) 폴더로 이동할 새 상대 경로 결정 (public).

    순수 함수다. writer 내부뿐 아니라 ReclassificationService 도 재배치 경로
    계산에 재사용하므로 public API 로 노출한다.

    - ``subcategory`` 가 주어지면 목적지는 ``<category>/<subcategory>/<basename>``.
    - 그렇지 않고 첫 컴포넌트가 이미 ``category`` 면 원경로 유지.
    - 그 외엔 ``<category>/<basename>``.
    - 동일 basename이 대상에 이미 있으면 호출자가 직접 충돌 회피 (여기서는 경로만 계산).
    """
    basename = Path(rel_path).name
    parts = Path(rel_path).parts

    sub = (subcategory or "").strip()
    if sub:
        # 이미 같은 <category>/<subcategory>/ 안에 있으면 그대로 유지.
        if len(parts) >= 2 and parts[0] == category and parts[1] == sub:
            return rel_path
        return str(Path(category) / sub / basename)

    if parts and parts[0] == category:
        return rel_path
    return str(Path(category) / basename)


# 하위호환 별칭(기존 테스트/내부 호출이 _decide_target_path 사용).
_decide_target_path = decide_target_path


_WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+?)\]\]")


def _wikilink_targets_for(old_rel: str) -> set[str]:
    """``old_rel`` 을 참조했을 가능성이 있는 wikilink 표기 후보들.

    옵시디언/Logseq 관행 상 wikilink 는 다음 형태 중 하나로 자주 쓰인다:
    - 전체 상대 경로 (``[[projects/foo/bar.md]]``)
    - 경로(확장자 생략) (``[[projects/foo/bar]]``)
    - basename 만 (``[[bar.md]]`` 또는 ``[[bar]]``) — vault 전역 고유라는 옵시디언 기본 가정

    경로 표기는 곧바로 새 경로로 갈아끼우면 되고, basename-only 표기는 vault 안에
    동일 basename 의 다른 파일이 없을 때만 안전하게 치환한다 (호출자가 충돌 검사).
    """
    candidates: set[str] = set()
    candidates.add(old_rel)
    if old_rel.endswith(".md"):
        candidates.add(old_rel[:-3])
    stem = Path(old_rel).stem
    candidates.add(stem)
    candidates.add(f"{stem}.md")
    return candidates


def _split_link_and_label(inside: str) -> tuple[str, str | None]:
    """``[[link|label]]`` 의 link / label 분리. label 없으면 ``(link, None)``."""
    if "|" in inside:
        link, label = inside.split("|", 1)
        return link.strip(), label
    return inside.strip(), None


def _split_link_and_anchor(link: str) -> tuple[str, str]:
    """``link#heading`` 의 본체 / ``#heading`` (또는 ``""``) 분리."""
    if "#" in link:
        head, anchor = link.split("#", 1)
        return head, f"#{anchor}"
    return link, ""


def _has_basename_duplicate(pages: Path, basename: str) -> bool:
    """vault 안에 동일 basename(.md) 파일이 2개 이상 있는지.

    True 면 basename-only wikilink 가 어느 파일을 가리키는지 모호하므로 치환하지 않는다.
    """
    target_name = basename if basename.endswith(".md") else f"{basename}.md"
    seen = 0
    for p in pages.rglob(target_name):
        seen += 1
        if seen >= 2:
            return True
    return False


def _rewrite_inbound_wikilinks(pages: Path, old_rel: str, new_rel: str) -> int:
    """``[[old_rel]]`` / ``[[old_stem]]`` 등을 ``[[new_rel(.md 제외)]]`` 로 치환.

    Args:
        pages: pages 루트
        old_rel: 옮기기 전 상대 경로 (예: ``inbox/foo.md``)
        new_rel: 옮긴 후 상대 경로 (예: ``projects/myproj/foo.md``)

    Returns:
        본문이 실제로 갱신된 파일 수.

    안전 정책:
    - 옮긴 파일 자신은 건드리지 않는다.
    - basename 만 쓰인 링크는 vault 안 동일 basename 이 유일할 때만 치환.
    - 본문에 변화가 없으면 파일을 다시 쓰지 않는다 (mtime 보존 + watchdog 폭주 회피).
    """
    if old_rel == new_rel:
        return 0

    old_candidates = _wikilink_targets_for(old_rel)
    # 새 링크는 ``.md`` 없이 정규화 — Obsidian 관행과 호환.
    new_link_norm = new_rel[:-3] if new_rel.endswith(".md") else new_rel

    old_basename = Path(old_rel).name
    basename_safe = not _has_basename_duplicate(pages, old_basename)

    rewritten = 0
    for md in pages.rglob("*.md"):
        try:
            rel = md.relative_to(pages)
        except ValueError:
            continue
        rel_str = str(rel).replace("\\", "/")
        if rel_str == new_rel or rel_str == old_rel:
            continue

        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        def _sub(m: re.Match[str]) -> str:
            inside = m.group(1)
            link, label = _split_link_and_label(inside)
            head, anchor = _split_link_and_anchor(link)
            head_norm = head.strip()
            if head_norm not in old_candidates:
                return m.group(0)
            # basename-only 인 링크는 vault 전역 unique 일 때만 치환.
            if head_norm in {Path(old_rel).stem, Path(old_rel).name} and not basename_safe:
                return m.group(0)
            new_inside = f"{new_link_norm}{anchor}"
            if label is not None:
                new_inside = f"{new_inside}|{label}"
            return f"[[{new_inside}]]"

        new_text = _WIKILINK_RE.sub(_sub, text)
        if new_text != text:
            try:
                _atomic_write(md, new_text)
                rewritten += 1
            except OSError as e:
                logger.warning("inbound rewrite write failed for %s: %s", rel_str, e)
    return rewritten


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

    def __init__(self, pages_path: Path, *, rewrite_inbound_links: bool = True):
        """FrontmatterWriter.

        Args:
            pages_path: pages 루트 경로.
            rewrite_inbound_links: 파일을 카테고리 폴더로 이동시킬 때, 다른 파일
                본문에 박힌 ``[[옛 경로]]`` / ``[[옛 stem]]`` 형태의 wikilink 를
                새 위치로 일괄 보정한다. 비활성하면 분류기가 옮긴 파일을 가리키던
                기존 링크가 모두 깨진 상태로 누적되어, ``wiki_get_backlinks`` /
                ``find_orphans`` 의 신호 대비 노이즈를 키운다.
        """
        self._pages = Path(pages_path)
        self._rewrite_inbound = bool(rewrite_inbound_links)

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

        # 카테고리 결정.
        # 사용자 값 우선이 원칙이나, inbox(staging)는 카테고리가 아니라 임시
        # 영역이다(instructions.py 명세). 파일이 staging 폴더 안에 있거나
        # category 값 자체가 staging 표식(inbox/_inbox/0.Inbox …)이면 사용자
        # 의도가 아니라 미분류 상태이므로 분류 결과로 덮어쓴다. 이 처리가 없으면
        # category: inbox 가 박힌 파일이 decide_target_path 에서 '제자리'로
        # 판정돼 inbox 에 영구히 갇힌다.
        first_part = Path(rel_path).parts[0] if Path(rel_path).parts else ""
        existing_category = meta_after.get("category")
        is_staging = is_staging_folder(first_part) or (
            isinstance(existing_category, str)
            and is_staging_folder(existing_category.strip())
        )
        if is_staging or not existing_category:
            meta_after["category"] = decision.category

        # subcategory 도 사용자 값 우선 (의도적으로 비웠을 수 있으므로 key 존재 여부로 판단).
        if decision.subcategory and "subcategory" not in meta_after:
            meta_after["subcategory"] = decision.subcategory

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
            sub = meta_after.get("subcategory")
            sub_str = str(sub).strip() if isinstance(sub, str) and sub else None
            tentative = _decide_target_path(
                rel_path, str(meta_after["category"]), sub_str
            )
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
            # inbound wikilink 보정 — 옮긴 파일을 가리키던 다른 파일의 [[옛 경로]] /
            # [[옛 stem]] 링크를 새 경로로 치환. 실패해도 본 작업은 성공 처리.
            if self._rewrite_inbound:
                try:
                    rewritten = _rewrite_inbound_wikilinks(
                        self._pages, rel_path, target_rel
                    )
                    if rewritten:
                        logger.info(
                            "rewrote inbound wikilinks in %d file(s) for %s -> %s",
                            rewritten,
                            rel_path,
                            target_rel,
                        )
                except Exception:
                    logger.exception(
                        "rewrite_inbound_wikilinks failed for %s -> %s (continuing)",
                        rel_path,
                        target_rel,
                    )

        logger.info(
            "frontmatter applied: %s -> %s (category=%s, subcategory=%s, confidence=%.2f)",
            rel_path,
            target_rel,
            meta_after.get("category"),
            meta_after.get("subcategory") or "-",
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
