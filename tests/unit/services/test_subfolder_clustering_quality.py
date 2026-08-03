"""suggest_subfolders 클러스터링 품질 회귀 테스트 (0.7.0 R3).

요청서(2026-07-20) 수용 기준 3:
- 폴더 주제 동어반복 그룹(``kt`` 등)이 나타나지 않는다.
- 넘버링 시리즈(``00-`` ~ ``NN-``)는 분리되지 않고 한 그룹으로 유지된다.
- 문서 유형 축(회의록/가이드/보고서/자격증명)이 1차 신호로 동작한다.
- 날짜 prefix 파일명은 회의록으로 추정한다 (포맷 4종 혼재 포함).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher
from wiki_search_mcp.services.classification_service import ClassificationService


@pytest.fixture
def wiki_path(tmp_path: Path) -> Path:
    return tmp_path


def _make_service(wiki_path: Path) -> ClassificationService:
    vector = MagicMock()
    vector.exists.return_value = False
    return ClassificationService(
        pages_path=wiki_path,
        vector_repository=vector,
        document_service=MagicMock(),
        category_service=MagicMock(),
        ignore_matcher=IgnoreMatcher.from_wiki(wiki_path),
    )


def _write(wiki_path: Path, rel: str, tags: list[str] | None = None) -> None:
    p = wiki_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = "tags: [" + ", ".join(tags) + "]" if tags else ""
    p.write_text(f"---\n{fm}\n---\n\n내용", encoding="utf-8")


def _group_by_name(result, name: str):
    for g in result.groups:
        if g.name == name:
            return g
    return None


def test_kt_itpark_scenario(wiki_path: Path) -> None:
    """요청서 2.2/2.3 재현: 회의록 날짜 4종 + 시리즈 8건 + 자격증명/가이드."""
    folder = "projects/KT_ITPARK"
    # 회의록 — 날짜 포맷 4종 혼재 + meeting 키워드
    meetings = [
        "2026-05-19 주간회의.md",
        "2026.05.12 정기회의.md",
        "26.05.11 킥오프.md",
        "260706-현장점검.md",
        "meeting-2026-04-23.md",
    ]
    # 아키텍처 시리즈 — 넘버링 prefix, 폴더 주제 동어반복 태그
    series = [f"0{i}-아키텍처-{i}.md" for i in range(6)]
    # 자격증명 / 가이드
    creds = ["ITPARK-VPN 자격증명.md", "DB 계정정보.md", "관리자 암호.md"]
    guides = ["서버 접속 방법.md", "배포 매뉴얼.md", "환경 세팅 튜토리얼.md"]
    # 동어반복 태그만 가진 파일 — 그룹 형성 금지 대상
    tautology = ["자료1.md", "자료2.md", "자료3.md"]

    for name in meetings:
        _write(wiki_path, f"{folder}/{name}", ["kt"])
    for name in series:
        _write(wiki_path, f"{folder}/{name}", ["kt", "kt-itpark"])
    for name in creds + guides:
        _write(wiki_path, f"{folder}/{name}", ["kt"])
    for name in tautology:
        _write(wiki_path, f"{folder}/{name}", ["kt", "kt-itpark"])

    r = _make_service(wiki_path).suggest_subfolders(folder, min_cluster_size=3)

    # 수용 기준 3-1: 동어반복 그룹 없음
    names = {g.name.lower() for g in r.groups}
    assert names.isdisjoint({"kt", "itpark", "kt-itpark", "kt_itpark", "projects"})

    # 수용 기준 3-2: 넘버링 시리즈는 한 그룹으로 유지 (분리 금지)
    series_rels = {f"{folder}/{n}" for n in series}
    containing = [g for g in r.groups if set(g.files) & series_rels]
    assert len(containing) == 1
    assert set(containing[0].files) == series_rels

    # 문서 유형 축
    meeting_group = _group_by_name(r, "회의록")
    assert meeting_group is not None
    assert set(meeting_group.files) == {f"{folder}/{n}" for n in meetings}
    cred_group = _group_by_name(r, "자격증명")
    assert cred_group is not None
    assert set(cred_group.files) == {f"{folder}/{n}" for n in creds}
    guide_group = _group_by_name(r, "가이드")
    assert guide_group is not None
    assert set(guide_group.files) == {f"{folder}/{n}" for n in guides}

    # 동어반복 태그만 가진 파일은 그룹을 못 만들고 미분류로 남는다
    assert {f"{folder}/{n}" for n in tautology} <= set(r.unclassified)


def test_type_keyword_beats_date_prefix(wiki_path: Path) -> None:
    """날짜 prefix 여도 명시 유형 키워드(보고서)가 이긴다."""
    folder = "projects/P"
    reports = [
        "2026-05-19 검토 보고서.md",
        "2026-06-01 중간 보고서.md",
        "260610-최종 검토.md",
    ]
    for name in reports:
        _write(wiki_path, f"{folder}/{name}")

    r = _make_service(wiki_path).suggest_subfolders(folder, min_cluster_size=3)
    g = _group_by_name(r, "보고서")
    assert g is not None
    assert len(g.files) == 3
    assert _group_by_name(r, "회의록") is None


def test_date_prefix_not_series(wiki_path: Path) -> None:
    """``26.05.11`` 같은 날짜 prefix 는 시리즈가 아니라 회의록 신호."""
    folder = "projects/D"
    for name in ["26.05.11 a.md", "26.05.12 b.md", "26.05.13 c.md"]:
        _write(wiki_path, f"{folder}/{name}")

    r = _make_service(wiki_path).suggest_subfolders(folder, min_cluster_size=3)
    assert _group_by_name(r, "회의록") is not None
    # 시리즈 그룹(넘버링) 은 없어야 함
    assert all("시리즈" not in g.name for g in r.groups)


def test_series_below_threshold_not_grouped(wiki_path: Path) -> None:
    """넘버링 파일이 임계 미만이면 시리즈 그룹을 만들지 않는다."""
    folder = "projects/S"
    _write(wiki_path, f"{folder}/00-a.md")
    _write(wiki_path, f"{folder}/01-b.md")
    _write(wiki_path, f"{folder}/x.md", ["t"])
    _write(wiki_path, f"{folder}/y.md", ["t"])
    _write(wiki_path, f"{folder}/z.md", ["t"])

    r = _make_service(wiki_path).suggest_subfolders(folder, min_cluster_size=3)
    grouped = {f for g in r.groups for f in g.files}
    assert f"{folder}/00-a.md" not in grouped
    assert f"{folder}/01-b.md" not in grouped
