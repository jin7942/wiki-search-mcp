"""Claude Code OAuth 재활용 provider.

``claude-agent-sdk``를 사용하여 사용자의 ``claude login`` OAuth 세션으로 분류 호출을 수행한다.
API 키 등록 없이 Claude Pro/Max 구독 한도 내에서 동작.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

# claude-agent-sdk
try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        CLIConnectionError,
        CLIJSONDecodeError,
        CLINotFoundError,
        ProcessError,
        TextBlock,
        query,
    )

    _SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - SDK 미설치 환경 (CI에서 발생)
    _SDK_AVAILABLE = False
    AssistantMessage = TextBlock = ClaudeAgentOptions = None  # type: ignore[assignment,misc]

    class _Stub(Exception):
        pass

    CLINotFoundError = ProcessError = CLIJSONDecodeError = CLIConnectionError = _Stub  # type: ignore[assignment,misc]

    async def query(*args: Any, **kw: Any):  # type: ignore[no-redef]
        raise RuntimeError("claude-agent-sdk not installed")


from wiki_search_mcp.core.exceptions import ClassifierError
from wiki_search_mcp.core.models import ClassificationDecision
from wiki_search_mcp.services.llm.prompt import (
    CLASSIFY_SYSTEM_PROMPT,
    build_user_prompt,
    parse_decision,
)
from wiki_search_mcp.services.llm.provider import ClassificationRequest

logger = logging.getLogger(__name__)


class ClaudeCodeProvider:
    """Claude Code OAuth 기반 LLM provider.

    Args:
        model: Claude 모델 alias ("haiku" / "sonnet" / "opus") 또는 풀 ID
        cli_path: 커스텀 claude CLI 경로 (없으면 SDK 번들 사용)
        timeout_s: 단일 호출 타임아웃
    """

    name = "claude-code"

    def __init__(
        self,
        model: str = "haiku",
        cli_path: str | None = None,
        timeout_s: float = 30.0,
        max_retries: int = 2,
        retry_backoff_s: tuple[float, ...] = (2.0, 8.0),
    ):
        if not _SDK_AVAILABLE:
            raise ClassifierError.of(
                "claude-agent-sdk not installed; run `pip install claude-agent-sdk`",
                code="CLI_NOT_FOUND",
            )
        self._model = model
        self._timeout_s = timeout_s
        # transient 실패(타임아웃 / 네트워크·프로세스 오류) 재시도 정책.
        # CLI 미설치(CLI_NOT_FOUND)는 재시도해도 무의미하므로 즉시 실패시킨다.
        self._max_retries = max(0, max_retries)
        self._retry_backoff_s = retry_backoff_s
        self._opts = ClaudeAgentOptions(
            model=model,
            max_turns=1,
            system_prompt=CLASSIFY_SYSTEM_PROMPT,
            tools=[],  # 모든 내장 도구 비활성
            permission_mode="dontAsk",
            cli_path=cli_path,
        )

    async def _drain(self, prompt: str, opts: Any | None = None) -> str:
        """SDK ``query()`` 결과를 끝까지 소비하고 텍스트 블록을 concat."""
        text_parts: list[str] = []
        async for msg in query(prompt=prompt, options=opts or self._opts):
            if isinstance(msg, AssistantMessage):
                for blk in msg.content:
                    if isinstance(blk, TextBlock):
                        text_parts.append(blk.text)
        return "".join(text_parts)

    def _backoff_for(self, attempt: int) -> float:
        """``attempt`` 번째 재시도 전 대기 초.

        ``retry_backoff_s`` 시퀀스를 순서대로 사용하되, max_retries 가
        시퀀스 길이보다 크면 마지막 값을 2배씩 지수 확장한다.

        과거에는 ``min(attempt, len-1)`` 이라 시퀀스 소진 후 마지막 값만
        반복돼(예: (2,8) 에서 8,8,8…) 지수 backoff 의도가 깨졌다. 이제
        (2, 8) + max_retries=4 → 2, 8, 16, 32 로 정상 증가한다.

        Args:
            attempt: 0부터 시작하는 시도 인덱스.

        Returns:
            대기 초(>= 0).
        """
        seq = self._retry_backoff_s
        if not seq:
            return 0.0
        if attempt < len(seq):
            return seq[attempt]
        # 시퀀스 소진: 마지막 값을 2^(초과분) 배로 확장.
        overflow = attempt - (len(seq) - 1)
        return seq[-1] * (2.0**overflow)

    async def _invoke_with_retry(
        self, prompt: str, opts: Any, *, label: str
    ) -> str:
        """LLM 1회 호출 (transient 실패는 exponential backoff 재시도).

        타임아웃 / 네트워크·프로세스 오류는 재시도하고, CLI 미설치는 즉시
        실패시킨다. 운영 로그상 단발 타임아웃 1회로 파일이 600초 cooldown 후
        사실상 영구 pending 되던 문제를 완화한다.

        Args:
            prompt: user prompt.
            opts: ``ClaudeAgentOptions``.
            label: 로그 식별용 (대상 경로 등).

        Returns:
            LLM 응답 텍스트 (파싱은 호출자 책임 — 파싱 오류는 재시도 대상 아님).

        Raises:
            ClassifierError: 재시도 소진 또는 재시도 불가 오류.
        """
        last_err: ClassifierError | None = None
        attempts = self._max_retries + 1
        for attempt in range(attempts):
            try:
                return await asyncio.wait_for(
                    self._drain(prompt, opts), timeout=self._timeout_s
                )
            except asyncio.TimeoutError as e:
                last_err = ClassifierError.of(
                    f"LLM call timed out after {self._timeout_s}s",
                    code="TIMEOUT",
                )
                last_err.__cause__ = e
            except CLINotFoundError as e:
                # 재시도 불가 — 즉시 실패.
                raise ClassifierError.of(
                    "claude CLI not found. Run `claude login` first.",
                    code="CLI_NOT_FOUND",
                ) from e
            except (ProcessError, CLIJSONDecodeError, CLIConnectionError) as e:
                last_err = ClassifierError.of(
                    f"Claude SDK error: {e}",
                    code="SDK_ERROR",
                )
                last_err.__cause__ = e

            # 여기 도달 = transient 실패. 남은 시도가 있으면 backoff 후 재시도.
            if attempt < attempts - 1:
                backoff = self._backoff_for(attempt)
                logger.warning(
                    "LLM call transient failure (%s), retry %d/%d after %.1fs: %s",
                    getattr(last_err.context, "code", "?") if last_err.context else "?",
                    attempt + 1,
                    self._max_retries,
                    backoff,
                    label,
                )
                await asyncio.sleep(backoff)

        # 모든 시도 소진.
        assert last_err is not None
        raise last_err

    async def classify(self, req: ClassificationRequest) -> ClassificationDecision:
        prompt = build_user_prompt(req)
        text = await self._invoke_with_retry(prompt, self._opts, label=req.path)
        return parse_decision(
            path=req.path,
            raw=text,
            provider=f"{self.name}:{self._model}",
            active_categories=req.active_categories,
            subfolders_by_category=dict(req.subfolders_by_category or {}),
        )

    async def complete(self, prompt: str, *, system_prompt: str) -> str:
        """분류 외 단발 텍스트 호출 (계층화 검증 등).

        ``classify`` 와 동일한 타임아웃/재시도 정책을 쓴다.

        Raises:
            ClassifierError: 호출 실패.
        """
        opts = ClaudeAgentOptions(
            model=self._model,
            max_turns=1,
            system_prompt=system_prompt,
            tools=[],
            permission_mode="dontAsk",
            cli_path=self._opts.cli_path,
        )
        return await self._invoke_with_retry(prompt, opts, label="complete")

    async def healthcheck(self) -> None:
        """간단한 ping 호출로 OAuth + CLI 정상 여부 확인.

        의도적으로 매우 짧은 prompt를 사용하여 한도 소모 최소화.
        """
        ping_opts = ClaudeAgentOptions(
            model=self._model,
            max_turns=1,
            system_prompt="Respond with the single word: OK",
            tools=[],
            permission_mode="dontAsk",
            cli_path=self._opts.cli_path,
        )

        async def _ping() -> None:
            async for _msg in query(prompt="ping", options=ping_opts):
                pass

        try:
            await asyncio.wait_for(_ping(), timeout=self._timeout_s)
            logger.info("Claude Code provider healthcheck OK (model=%s)", self._model)
        except asyncio.TimeoutError as e:
            raise ClassifierError.of("healthcheck timed out", code="TIMEOUT") from e
        except CLINotFoundError as e:
            raise ClassifierError.of(
                "claude CLI not found. Run `claude login` first.",
                code="CLI_NOT_FOUND",
            ) from e
        except (ProcessError, CLIJSONDecodeError, CLIConnectionError) as e:
            raise ClassifierError.of(f"Claude SDK error: {e}", code="SDK_ERROR") from e
