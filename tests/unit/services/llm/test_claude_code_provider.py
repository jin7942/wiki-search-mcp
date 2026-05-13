"""ClaudeCodeProvider 단위 테스트 (SDK는 mock)."""

from __future__ import annotations

from typing import Any

import pytest

from wiki_search_mcp.core.exceptions import ClassifierError
from wiki_search_mcp.services.llm import ClaudeCodeProvider
from wiki_search_mcp.services.llm.provider import ClassificationRequest


class _FakeText:
    def __init__(self, text: str):
        self.text = text


class _FakeAssistantMessage:
    def __init__(self, text: str):
        self.content = [_FakeText(text)]


def _req(path: str = "inbox/x.md") -> ClassificationRequest:
    return ClassificationRequest(
        path=path,
        body_preview="hello",
        suggestion_hints={
            "category_candidates": ["infra"],
            "tag_candidates": [],
            "similar_paths": [],
        },
        active_categories=("infra", "notes"),
    )


@pytest.mark.asyncio
async def test_classify_parses_sdk_response(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = '{"category":"infra","tags":["nginx"],"confidence":0.9,"reasoning":"r"}'

    async def fake_query(prompt: str, options: Any):
        # Inject our fake AssistantMessage and TextBlock via monkeypatched isinstance
        yield _FakeAssistantMessage(raw)

    import wiki_search_mcp.services.llm.claude_code_provider as mod

    monkeypatch.setattr(mod, "query", fake_query)
    monkeypatch.setattr(mod, "AssistantMessage", _FakeAssistantMessage)
    monkeypatch.setattr(mod, "TextBlock", _FakeText)

    provider = ClaudeCodeProvider(model="haiku")
    decision = await provider.classify(_req())
    assert decision.category == "infra"
    assert decision.tags == ("nginx",)
    assert decision.confidence == 0.9
    assert decision.provider == "claude-code:haiku"


@pytest.mark.asyncio
async def test_classify_translates_cli_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    import wiki_search_mcp.services.llm.claude_code_provider as mod

    class _CLIErr(Exception):
        pass

    async def fake_query(prompt: str, options: Any):
        raise _CLIErr("missing")
        yield  # pragma: no cover

    monkeypatch.setattr(mod, "query", fake_query)
    monkeypatch.setattr(mod, "CLINotFoundError", _CLIErr)
    provider = ClaudeCodeProvider(model="haiku")

    with pytest.raises(ClassifierError) as exc:
        await provider.classify(_req())
    assert exc.value.context.code == "CLI_NOT_FOUND"


@pytest.mark.asyncio
async def test_classify_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import wiki_search_mcp.services.llm.claude_code_provider as mod

    async def fake_query(prompt: str, options: Any):
        import asyncio

        await asyncio.sleep(10)
        if False:
            yield None  # pragma: no cover

    monkeypatch.setattr(mod, "query", fake_query)
    monkeypatch.setattr(mod, "AssistantMessage", _FakeAssistantMessage)
    monkeypatch.setattr(mod, "TextBlock", _FakeText)

    provider = ClaudeCodeProvider(model="haiku", timeout_s=0.05)
    with pytest.raises(ClassifierError) as exc:
        await provider.classify(_req())
    assert exc.value.context.code == "TIMEOUT"
