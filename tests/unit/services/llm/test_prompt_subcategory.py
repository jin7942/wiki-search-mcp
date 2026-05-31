"""LLM 프롬프트/파서 v0.4.0 회귀 테스트.

다루는 동작:
- ``build_user_prompt`` 가 ``subfolders_by_category`` 를 JSON 으로 포함한다.
- ``parse_decision`` 이 LLM 의 ``subcategory`` 응답을 카테고리별 화이트리스트로 검증한다.
- 화이트리스트에 없는 subcategory 는 ``None`` 으로 강등 (임의 폴더 생성 방지).
"""

from __future__ import annotations

import json

from wiki_search_mcp.services.llm.prompt import build_user_prompt, parse_decision
from wiki_search_mcp.services.llm.provider import ClassificationRequest


def _req(subfolders: dict[str, tuple[str, ...]]) -> ClassificationRequest:
    return ClassificationRequest(
        path="inbox/foo.md",
        body_preview="본문",
        suggestion_hints={
            "category_candidates": ["projects"],
            "tag_candidates": ["k"],
            "similar_paths": [],
        },
        active_categories=("projects", "personal"),
        subfolders_by_category=subfolders,
    )


def test_user_prompt_contains_subfolders_json() -> None:
    req = _req({"projects": ("myproj", "kbs"), "personal": ("budget-app",)})
    prompt = build_user_prompt(req)
    assert "subfolders_by_category" in prompt
    # JSON 직렬화 후에도 튜플이 list 로 들어가야 한다
    assert "myproj" in prompt and "kbs" in prompt and "budget-app" in prompt


def test_user_prompt_empty_subfolders_ok() -> None:
    """서브폴더가 없는 카테고리만 있는 경우에도 prompt 가 정상 생성된다."""
    req = _req({})
    prompt = build_user_prompt(req)
    assert "subfolders_by_category: {}" in prompt


def test_parse_decision_accepts_valid_subcategory() -> None:
    raw = json.dumps(
        {
            "category": "projects",
            "subcategory": "myproj",
            "tags": ["k"],
            "confidence": 0.9,
            "reasoning": "ok",
        }
    )
    decision = parse_decision(
        path="inbox/x.md",
        raw=raw,
        provider="fake",
        active_categories=("projects",),
        subfolders_by_category={"projects": ("myproj", "kbs")},
    )
    assert decision.subcategory == "myproj"


def test_parse_decision_demotes_unknown_subcategory() -> None:
    """LLM 이 화이트리스트 밖 서브폴더를 제안하면 ``None`` 으로 강등."""
    raw = json.dumps(
        {
            "category": "projects",
            "subcategory": "fancy-new-folder",
            "tags": [],
            "confidence": 0.9,
            "reasoning": "ok",
        }
    )
    decision = parse_decision(
        path="inbox/x.md",
        raw=raw,
        provider="fake",
        active_categories=("projects",),
        subfolders_by_category={"projects": ("myproj",)},
    )
    assert decision.subcategory is None


def test_parse_decision_subcategory_null_is_ok() -> None:
    raw = json.dumps(
        {
            "category": "projects",
            "subcategory": None,
            "tags": [],
            "confidence": 0.9,
            "reasoning": "ok",
        }
    )
    decision = parse_decision(
        path="inbox/x.md",
        raw=raw,
        provider="fake",
        active_categories=("projects",),
        subfolders_by_category={"projects": ("myproj",)},
    )
    assert decision.subcategory is None


def test_parse_decision_subcategory_field_missing_is_ok() -> None:
    """``subcategory`` 키 자체가 빠진 응답도 허용 (후방 호환)."""
    raw = json.dumps(
        {
            "category": "projects",
            "tags": [],
            "confidence": 0.9,
            "reasoning": "ok",
        }
    )
    decision = parse_decision(
        path="inbox/x.md",
        raw=raw,
        provider="fake",
        active_categories=("projects",),
        subfolders_by_category={},
    )
    assert decision.subcategory is None
