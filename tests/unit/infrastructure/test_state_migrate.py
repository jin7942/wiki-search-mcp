"""daemon state 자동 탐지/이전 안전 가드 회귀 테스트 (v0.3.0, P3).

vault 경로 이전 시 옛 해시 디렉토리의 작업 이력(applied/pending)을 새 경로로
이전한다. 핵심은 오탐 방지 가드:
- 새 경로 state 에 데이터 있으면 이전 안 함 (덮어쓰기 금지).
- 데이터 가진 옛 후보가 정확히 1개일 때만 자동 이전. 2개 이상이면 보류.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wiki_search_mcp.infrastructure.daemon.paths import _hash_wiki_path, state_dir
from wiki_search_mcp.infrastructure.daemon.state_migrate import (
    auto_migrate_if_safe,
    find_stale_candidates,
    migrate_from,
)


@pytest.fixture(autouse=True)
def _xdg_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """state 디렉토리를 tmp 로 격리."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _seed_old_state(
    base_root: Path,
    old_wiki: Path,
    *,
    applied: int = 0,
    pending: int = 0,
    wiki_path_in_status: str | None = None,
) -> Path:
    """옛 해시 디렉토리를 직접 만들어 작업 이력을 심는다."""
    d = base_root / _hash_wiki_path(old_wiki)
    d.mkdir(parents=True, exist_ok=True)
    if applied:
        (d / "applied.jsonl").write_text(
            "\n".join(json.dumps({"i": i}) for i in range(applied)) + "\n",
            encoding="utf-8",
        )
    if pending:
        (d / "pending.jsonl").write_text(
            "\n".join(json.dumps({"i": i}) for i in range(pending)) + "\n",
            encoding="utf-8",
        )
    status = {"state": "stopped", "wiki_path": wiki_path_in_status or str(old_wiki)}
    (d / "daemon_status.json").write_text(json.dumps(status), encoding="utf-8")
    return d


def _wsm_root(tmp_path: Path) -> Path:
    """``XDG_STATE_HOME/wiki-search-mcp/`` 루트."""
    return tmp_path / "state" / "wiki-search-mcp"


class TestFindStaleCandidates:
    def test_finds_old_dir_with_data(self, tmp_path: Path) -> None:
        new_wiki = tmp_path / "new_vault"
        new_wiki.mkdir()
        old_wiki = tmp_path / "old_vault"
        _seed_old_state(_wsm_root(tmp_path), old_wiki, applied=17, pending=1603)

        candidates = find_stale_candidates(new_wiki)

        assert len(candidates) == 1
        assert candidates[0].applied_count == 17
        assert candidates[0].pending_count == 1603
        assert candidates[0].recorded_wiki_path == str(old_wiki)

    def test_ignores_empty_old_dirs(self, tmp_path: Path) -> None:
        new_wiki = tmp_path / "new_vault"
        new_wiki.mkdir()
        old_wiki = tmp_path / "old_vault"
        _seed_old_state(_wsm_root(tmp_path), old_wiki, applied=0, pending=0)

        candidates = find_stale_candidates(new_wiki)

        assert candidates == []

    def test_excludes_current_dir(self, tmp_path: Path) -> None:
        """현재 vault 자신의 디렉토리는 후보에서 제외."""
        new_wiki = tmp_path / "new_vault"
        new_wiki.mkdir()
        # 현재 디렉토리에 데이터를 심어도 후보로 잡히면 안 됨
        cur = state_dir(new_wiki)
        (cur / "applied.jsonl").write_text(json.dumps({"i": 0}) + "\n", encoding="utf-8")

        candidates = find_stale_candidates(new_wiki)

        assert candidates == []


class TestAutoMigrateIfSafe:
    def test_migrates_single_candidate(self, tmp_path: Path) -> None:
        new_wiki = tmp_path / "new_vault"
        new_wiki.mkdir()
        old_wiki = tmp_path / "old_vault"
        _seed_old_state(_wsm_root(tmp_path), old_wiki, applied=17, pending=1603)

        result = auto_migrate_if_safe(new_wiki)

        assert result is not None
        assert result.applied_count == 17
        cur = state_dir(new_wiki)
        # 파일이 실제로 복사됐는지
        assert (cur / "applied.jsonl").exists()
        assert (cur / "pending.jsonl").exists()
        assert (cur / "daemon_status.json").exists()
        applied_lines = [
            l for l in (cur / "applied.jsonl").read_text().splitlines() if l.strip()
        ]
        assert len(applied_lines) == 17

    def test_skips_when_current_has_data(self, tmp_path: Path) -> None:
        """새 경로에 이미 데이터가 있으면 이전하지 않는다 (덮어쓰기 금지)."""
        new_wiki = tmp_path / "new_vault"
        new_wiki.mkdir()
        old_wiki = tmp_path / "old_vault"
        _seed_old_state(_wsm_root(tmp_path), old_wiki, applied=17)
        # 현재 디렉토리에 기존 데이터
        cur = state_dir(new_wiki)
        (cur / "applied.jsonl").write_text(json.dumps({"existing": 1}) + "\n", encoding="utf-8")

        result = auto_migrate_if_safe(new_wiki)

        assert result is None
        # 기존 데이터가 보존되어야 함 (1줄 그대로)
        lines = [l for l in (cur / "applied.jsonl").read_text().splitlines() if l.strip()]
        assert len(lines) == 1

    def test_skips_when_multiple_candidates(self, tmp_path: Path) -> None:
        """후보가 2개 이상이면 모호하므로 자동 이전하지 않는다."""
        new_wiki = tmp_path / "new_vault"
        new_wiki.mkdir()
        _seed_old_state(_wsm_root(tmp_path), tmp_path / "old_a", applied=5)
        _seed_old_state(_wsm_root(tmp_path), tmp_path / "old_b", applied=9)

        result = auto_migrate_if_safe(new_wiki)

        assert result is None
        # 둘 다 후보로 보고되어야 함 (호출자가 안내용으로 사용)
        assert len(find_stale_candidates(new_wiki)) == 2
        # 현재 디렉토리는 비어 있어야 함 (아무것도 복사 안 됨)
        cur = state_dir(new_wiki)
        assert not (cur / "applied.jsonl").exists()

    def test_no_candidates_returns_none(self, tmp_path: Path) -> None:
        new_wiki = tmp_path / "new_vault"
        new_wiki.mkdir()

        assert auto_migrate_if_safe(new_wiki) is None


class TestMigrateFrom:
    """수동 마이그레이션 — auto 가 ambiguous 로 보류된 경우의 fallback."""

    def test_migrates_from_explicit_source(self, tmp_path: Path) -> None:
        new_wiki = tmp_path / "new_vault"
        new_wiki.mkdir()
        old_wiki_a = tmp_path / "old_a"
        old_wiki_b = tmp_path / "old_b"
        src_a = _seed_old_state(_wsm_root(tmp_path), old_wiki_a, applied=5)
        _seed_old_state(_wsm_root(tmp_path), old_wiki_b, applied=9)

        # 후보 2개 → auto 는 보류
        assert auto_migrate_if_safe(new_wiki) is None

        # 수동으로 a 를 지정
        result = migrate_from(src_a, new_wiki)
        assert result.applied_count == 5
        cur = state_dir(new_wiki)
        assert (cur / "applied.jsonl").exists()

    def test_refuses_when_current_has_data(self, tmp_path: Path) -> None:
        new_wiki = tmp_path / "new_vault"
        new_wiki.mkdir()
        cur = state_dir(new_wiki)
        (cur / "applied.jsonl").write_text(json.dumps({"existing": 1}) + "\n", encoding="utf-8")
        src = _seed_old_state(_wsm_root(tmp_path), tmp_path / "old", applied=3)

        with pytest.raises(FileExistsError):
            migrate_from(src, new_wiki)

    def test_overwrite_flag_forces(self, tmp_path: Path) -> None:
        new_wiki = tmp_path / "new_vault"
        new_wiki.mkdir()
        cur = state_dir(new_wiki)
        (cur / "applied.jsonl").write_text(json.dumps({"existing": 1}) + "\n", encoding="utf-8")
        src = _seed_old_state(_wsm_root(tmp_path), tmp_path / "old", applied=3)

        migrate_from(src, new_wiki, overwrite=True)
        # 옛 데이터(3줄)로 덮어쓰여야 함
        lines = [l for l in (cur / "applied.jsonl").read_text().splitlines() if l.strip()]
        assert len(lines) == 3

    def test_accepts_status_json_path_and_resolves_to_dir(self, tmp_path: Path) -> None:
        new_wiki = tmp_path / "new_vault"
        new_wiki.mkdir()
        src = _seed_old_state(_wsm_root(tmp_path), tmp_path / "old", applied=4)

        # 사용자가 daemon_status.json 파일 경로를 넘겨도 부모를 source 로 간주.
        result = migrate_from(src / "daemon_status.json", new_wiki)
        assert result.applied_count == 4

    def test_raises_when_source_is_current_dir(self, tmp_path: Path) -> None:
        new_wiki = tmp_path / "new_vault"
        new_wiki.mkdir()
        cur = state_dir(new_wiki)

        with pytest.raises(FileNotFoundError):
            migrate_from(cur, new_wiki)

    def test_raises_when_no_migratable_files(self, tmp_path: Path) -> None:
        new_wiki = tmp_path / "new_vault"
        new_wiki.mkdir()
        empty = tmp_path / "empty_state"
        empty.mkdir()

        with pytest.raises(FileNotFoundError):
            migrate_from(empty, new_wiki)
