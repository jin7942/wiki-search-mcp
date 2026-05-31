"""Vault 경로 이전 후 고립된 daemon state 자동 탐지/이전.

state 디렉토리는 ``~/.local/state/wiki-search-mcp/<sha1(wiki_path)[:12]>/`` 로
wiki 절대경로 해시에 격리된다. 사용자가 vault를 옮기면 해시가 바뀌어 옛 작업 이력
(applied.jsonl / pending.jsonl / daemon_status.json)이 새 경로에서 보이지 않게 된다.

이 모듈은 daemon 시작 시 옛 state 를 안전하게 찾아 새 경로로 이전한다.

안전 원칙 (오탐 방지가 데이터 정확성보다 우선):
- 새 경로 state 가 **이미 데이터를 갖고 있으면** 이전하지 않는다 (덮어쓰기 금지).
- 옛 후보가 **정확히 1개일 때만** 자동 이전한다. 0개면 할 일 없음, 2개 이상이면
  어느 것이 맞는지 알 수 없으므로 자동 이전하지 않고 호출자가 안내만 하도록 둔다.
- 후보 조건: 그 디렉토리의 ``daemon_status.json`` 의 ``wiki_path`` 가 현재 wiki 와
  다르고(다른 해시이므로 당연), 실제 이전 흔적(applied 또는 pending 데이터)이 있다.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from wiki_search_mcp.infrastructure.daemon.paths import state_dir

logger = logging.getLogger(__name__)

# 이전 대상 파일 (있을 때만 복사)
_MIGRATE_FILES = (
    "applied.jsonl",
    "pending.jsonl",
    "daemon_status.json",
)


@dataclass(frozen=True)
class StaleStateCandidate:
    """이전 후보 — 옛 해시 디렉토리 1개를 가리킨다."""

    state_dir: Path
    recorded_wiki_path: str | None
    applied_count: int
    pending_count: int

    @property
    def has_data(self) -> bool:
        return self.applied_count > 0 or self.pending_count > 0


def _count_lines(path: Path) -> int:
    """JSONL 파일의 비어있지 않은 줄 수. 없으면 0."""
    try:
        with open(path, "r", encoding="utf-8") as fp:
            return sum(1 for line in fp if line.strip())
    except (FileNotFoundError, OSError):
        return 0


def _read_recorded_wiki_path(status_path: Path) -> str | None:
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    wp = data.get("wiki_path")
    return wp if isinstance(wp, str) else None


def _state_has_data(d: Path) -> bool:
    """주어진 state 디렉토리에 의미있는 작업 이력이 있는지."""
    return _count_lines(d / "applied.jsonl") > 0 or _count_lines(d / "pending.jsonl") > 0


def find_stale_candidates(wiki_path: Path) -> list[StaleStateCandidate]:
    """현재 wiki 의 state 디렉토리 형제들 중 이전 후보를 찾는다.

    Args:
        wiki_path: 현재 wiki 루트

    Returns:
        데이터를 가진 옛 state 디렉토리 후보 목록 (현재 디렉토리는 제외).
    """
    current = state_dir(wiki_path)  # 부수효과: 현재 디렉토리 생성됨
    parent = current.parent  # ~/.local/state/wiki-search-mcp/
    candidates: list[StaleStateCandidate] = []
    if not parent.is_dir():
        return candidates
    for child in parent.iterdir():
        if not child.is_dir() or child == current:
            continue
        if not _state_has_data(child):
            continue
        candidates.append(
            StaleStateCandidate(
                state_dir=child,
                recorded_wiki_path=_read_recorded_wiki_path(child / "daemon_status.json"),
                applied_count=_count_lines(child / "applied.jsonl"),
                pending_count=_count_lines(child / "pending.jsonl"),
            )
        )
    return candidates


def auto_migrate_if_safe(wiki_path: Path) -> StaleStateCandidate | None:
    """안전 조건을 만족할 때만 옛 state 를 현재 경로로 이전.

    조건:
    - 현재 state 가 비어 있어야 한다 (덮어쓰기 금지).
    - 데이터 가진 옛 후보가 **정확히 1개** 여야 한다.

    Returns:
        이전을 수행했으면 그 후보, 아니면 ``None``.
        후보가 2개 이상이라 자동 이전을 보류한 경우도 ``None`` 을 반환하므로,
        호출자는 ``find_stale_candidates`` 로 별도 안내를 띄울 수 있다.
    """
    current = state_dir(wiki_path)
    if _state_has_data(current):
        logger.debug("current state already has data; skip migration")
        return None

    candidates = find_stale_candidates(wiki_path)
    if len(candidates) != 1:
        if len(candidates) > 1:
            logger.warning(
                "found %d stale state dirs; not auto-migrating (ambiguous)",
                len(candidates),
            )
        return None

    src = candidates[0]
    for name in _MIGRATE_FILES:
        src_file = src.state_dir / name
        if src_file.exists():
            shutil.copy2(src_file, current / name)
    logger.info(
        "migrated daemon state: %s -> %s (applied=%d, pending=%d, old_wiki=%s)",
        src.state_dir,
        current,
        src.applied_count,
        src.pending_count,
        src.recorded_wiki_path,
    )
    return src


def migrate_from(src: Path, wiki_path: Path, *, overwrite: bool = False) -> StaleStateCandidate:
    """사용자가 지정한 옛 state 디렉토리를 현재 wiki 의 state 디렉토리로 복사한다.

    ``auto_migrate_if_safe`` 가 후보 2개 이상 등 안전 조건을 만족 못 해 자동 이전을
    포기한 경우의 수동 fallback.

    Args:
        src: 옛 state 디렉토리(또는 그 안의 daemon_status.json 경로).
        wiki_path: 현재 wiki 루트.
        overwrite: True 면 현재 state 에 데이터가 있어도 덮어쓴다 (위험).

    Returns:
        이전된 후보 정보.

    Raises:
        FileNotFoundError: ``src`` 가 디렉토리가 아니거나 마이그레이션 대상 파일이 전무.
        FileExistsError: 현재 state 에 이미 데이터가 있고 ``overwrite=False``.
    """
    src = src.expanduser().resolve()
    if src.is_file():
        # daemon_status.json 등 파일 경로가 넘어오면 부모를 source 로.
        src = src.parent
    if not src.is_dir():
        raise FileNotFoundError(f"source state directory not found: {src}")

    current = state_dir(wiki_path)
    if not overwrite and _state_has_data(current):
        raise FileExistsError(
            f"current state already has data: {current}. Use overwrite=True to force."
        )

    if src == current:
        raise FileNotFoundError(
            f"source equals current state directory: {src}. Nothing to migrate."
        )

    copied: list[str] = []
    for name in _MIGRATE_FILES:
        src_file = src / name
        if src_file.exists():
            shutil.copy2(src_file, current / name)
            copied.append(name)
    if not copied:
        raise FileNotFoundError(
            f"no migratable files in {src} "
            f"(expected any of: {', '.join(_MIGRATE_FILES)})"
        )

    candidate = StaleStateCandidate(
        state_dir=src,
        recorded_wiki_path=_read_recorded_wiki_path(src / "daemon_status.json"),
        applied_count=_count_lines(src / "applied.jsonl"),
        pending_count=_count_lines(src / "pending.jsonl"),
    )
    logger.info(
        "manually migrated daemon state: %s -> %s (files=%s, applied=%d, pending=%d)",
        src,
        current,
        copied,
        candidate.applied_count,
        candidate.pending_count,
    )
    return candidate


__all__ = [
    "StaleStateCandidate",
    "auto_migrate_if_safe",
    "find_stale_candidates",
    "migrate_from",
]
