"""prompt.parse_decision / build_user_prompt 단위 테스트."""

from __future__ import annotations

import json

import pytest

from wiki_search_mcp.core.exceptions import ClassifierError
from wiki_search_mcp.services.llm.prompt import build_user_prompt, parse_decision
from wiki_search_mcp.services.llm.provider import ClassificationRequest


def _parse(raw: str, active=("infra", "notes")):
    return parse_decision(
        path="x.md", raw=raw, provider="test", active_categories=active
    )


def test_parse_clean_json() -> None:
    raw = '{"category":"infra","tags":["nginx"],"confidence":0.9,"reasoning":"ok"}'
    d = _parse(raw)
    assert d.category == "infra"
    assert d.tags == ("nginx",)
    assert d.confidence == 0.9
    assert d.reasoning == "ok"


def test_parse_extracts_json_from_codeblock() -> None:
    raw = "```json\n{\"category\":\"infra\",\"tags\":[\"a\"],\"confidence\":0.7,\"reasoning\":\"r\"}\n```"
    d = _parse(raw)
    assert d.category == "infra"


def test_parse_clamps_confidence() -> None:
    raw = '{"category":"infra","tags":[],"confidence":2.5,"reasoning":"r"}'
    d = _parse(raw)
    assert d.confidence == 1.0
    raw2 = '{"category":"infra","tags":[],"confidence":-1,"reasoning":"r"}'
    assert _parse(raw2).confidence == 0.0


def test_parse_demotes_unknown_category() -> None:
    raw = '{"category":"random","tags":[],"confidence":0.9,"reasoning":"r"}'
    d = _parse(raw)
    assert d.category == "uncategorized"


def test_parse_keeps_uncategorized_literal() -> None:
    raw = '{"category":"uncategorized","tags":[],"confidence":0.5,"reasoning":"r"}'
    d = _parse(raw)
    assert d.category == "uncategorized"


def test_parse_truncates_tags_to_5() -> None:
    raw = json.dumps(
        {
            "category": "infra",
            "tags": ["a", "b", "c", "d", "e", "f", "g"],
            "confidence": 0.8,
            "reasoning": "r",
        }
    )
    assert len(_parse(raw).tags) == 5


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(ClassifierError) as exc:
        _parse("not a json at all")
    assert exc.value.context.code == "INVALID_JSON"


def test_parse_missing_field_raises() -> None:
    with pytest.raises(ClassifierError) as exc:
        _parse('{"tags":["a"],"confidence":0.5,"reasoning":"r"}')
    assert exc.value.context.code == "INVALID_FIELDS"


def test_build_user_prompt_includes_active_and_hints() -> None:
    req = ClassificationRequest(
        path="inbox/x.md",
        body_preview="some content",
        suggestion_hints={
            "category_candidates": ["infra"],
            "tag_candidates": ["nginx"],
            "similar_paths": ["infra/y.md"],
        },
        active_categories=("infra", "notes"),
    )
    prompt = build_user_prompt(req)
    assert "infra" in prompt
    assert "nginx" in prompt
    assert "some content" in prompt
    assert "inbox/x.md" in prompt
