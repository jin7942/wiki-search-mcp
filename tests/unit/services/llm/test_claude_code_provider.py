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

    provider = ClaudeCodeProvider(model="haiku", timeout_s=0.05, max_retries=0)
    with pytest.raises(ClassifierError) as exc:
        await provider.classify(_req())
    assert exc.value.context.code == "TIMEOUT"


@pytest.mark.asyncio
async def test_classify_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """transient SDK 오류가 나도 재시도해서 성공하면 정상 반환."""
    import wiki_search_mcp.services.llm.claude_code_provider as mod

    raw = '{"category":"infra","tags":[],"confidence":0.8,"reasoning":"r"}'
    calls = {"n": 0}

    class _ProcErr(Exception):
        pass

    async def fake_query(prompt: str, options: Any):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _ProcErr("transient connection reset")
        yield _FakeAssistantMessage(raw)

    monkeypatch.setattr(mod, "query", fake_query)
    monkeypatch.setattr(mod, "AssistantMessage", _FakeAssistantMessage)
    monkeypatch.setattr(mod, "TextBlock", _FakeText)
    monkeypatch.setattr(mod, "ProcessError", _ProcErr)

    provider = ClaudeCodeProvider(
        model="haiku", max_retries=2, retry_backoff_s=(0.0, 0.0)
    )
    decision = await provider.classify(_req())
    assert decision.category == "infra"
    assert calls["n"] == 2  # 1회 실패 + 1회 성공


@pytest.mark.asyncio
async def test_classify_exhausts_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """transient 오류가 계속되면 재시도 소진 후 마지막 오류를 raise."""
    import wiki_search_mcp.services.llm.claude_code_provider as mod

    calls = {"n": 0}

    class _ProcErr(Exception):
        pass

    async def fake_query(prompt: str, options: Any):
        calls["n"] += 1
        raise _ProcErr("always fails")
        yield  # pragma: no cover

    monkeypatch.setattr(mod, "query", fake_query)
    monkeypatch.setattr(mod, "ProcessError", _ProcErr)

    provider = ClaudeCodeProvider(
        model="haiku", max_retries=2, retry_backoff_s=(0.0, 0.0)
    )
    with pytest.raises(ClassifierError) as exc:
        await provider.classify(_req())
    assert exc.value.context.code == "SDK_ERROR"
    assert calls["n"] == 3  # 최초 1 + 재시도 2


@pytest.mark.asyncio
async def test_cli_not_found_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI 미설치는 재시도하지 않고 즉시 실패 (재시도 무의미)."""
    import wiki_search_mcp.services.llm.claude_code_provider as mod

    calls = {"n": 0}

    class _CLIErr(Exception):
        pass

    async def fake_query(prompt: str, options: Any):
        calls["n"] += 1
        raise _CLIErr("missing")
        yield  # pragma: no cover

    monkeypatch.setattr(mod, "query", fake_query)
    monkeypatch.setattr(mod, "CLINotFoundError", _CLIErr)

    provider = ClaudeCodeProvider(
        model="haiku", max_retries=2, retry_backoff_s=(0.0, 0.0)
    )
    with pytest.raises(ClassifierError) as exc:
        await provider.classify(_req())
    assert exc.value.context.code == "CLI_NOT_FOUND"
    assert calls["n"] == 1  # 재시도 안 함


def test_backoff_sequence_then_exponential_extension() -> None:
    """backoff 시퀀스 소진 후 마지막 값을 2배씩 지수 확장.

    과거: min(attempt, len-1) 이라 (2,8) → 2, 8, 8, 8… (지수 깨짐).
    수정: (2, 8) → 2, 8, 16, 32 (마지막 값 *2^overflow).
    """
    provider = ClaudeCodeProvider(
        model="haiku", max_retries=4, retry_backoff_s=(2.0, 8.0)
    )
    assert provider._backoff_for(0) == 2.0
    assert provider._backoff_for(1) == 8.0
    assert provider._backoff_for(2) == 16.0  # 8 * 2^1
    assert provider._backoff_for(3) == 32.0  # 8 * 2^2


def test_backoff_empty_sequence_returns_zero() -> None:
    """backoff 시퀀스가 비면 0초 (즉시 재시도)."""
    provider = ClaudeCodeProvider(
        model="haiku", max_retries=2, retry_backoff_s=()
    )
    assert provider._backoff_for(0) == 0.0
    assert provider._backoff_for(5) == 0.0


def test_backoff_single_element_extends() -> None:
    """단일 원소 시퀀스도 지수 확장된다."""
    provider = ClaudeCodeProvider(
        model="haiku", max_retries=3, retry_backoff_s=(1.0,)
    )
    assert provider._backoff_for(0) == 1.0
    assert provider._backoff_for(1) == 2.0  # 1 * 2^1
    assert provider._backoff_for(2) == 4.0  # 1 * 2^2
