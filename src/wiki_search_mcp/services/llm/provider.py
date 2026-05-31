"""LLM Provider 인터페이스.

Daemon이 분류 호출을 위해 사용하는 추상화. 현재 구현체는
``ClaudeCodeProvider`` (Claude Agent SDK + OAuth 재활용)뿐이며,
``AnthropicAPIProvider``는 v0.3.0 예약 스텁이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ClassificationRequest:
    """LLM 분류 요청 페이로드.

    Attributes:
        path: 대상 파일 상대 경로
        body_preview: 본문 앞부분 (토큰 절약용 4000자 권장)
        suggestion_hints: ClassificationSuggestion.to_dict() (휴리스틱 힌트로 prompt에 주입)
        active_categories: 사용자 wiki에 존재하는 카테고리 목록 (LLM이 이 중에서 선택)
        subfolders_by_category: 각 카테고리의 1-depth 서브폴더 이름 맵 (옵션).
            예: ``{"projects": ("myproj", "kbs"), "personal": ("budget-app",)}``.
            LLM 이 평탄 배치 대신 적절한 프로젝트 폴더로 라우팅하도록 힌트로 전달한다.
            비어 있으면 LLM 은 subcategory 없이 1-depth 로만 응답해야 한다.
    """

    path: str
    body_preview: str
    suggestion_hints: dict[str, Any]
    active_categories: tuple[str, ...]
    subfolders_by_category: dict[str, tuple[str, ...]] = field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    """LLM provider Protocol.

    daemon은 ``classify()``로 분류 결정을 받고, ``healthcheck()``로 가용성을 검증한다.
    구현체는 stateless여야 하며 동시 호출은 ``asyncio.Lock``으로 직렬화한다.
    """

    name: str

    async def classify(self, req: ClassificationRequest):  # -> ClassificationDecision
        """문서를 분류하여 ``ClassificationDecision``을 반환.

        Raises:
            ClassifierError: CLI 미설치/SDK 호출 실패/JSON 파싱 실패 등
        """
        ...

    async def healthcheck(self) -> None:
        """provider가 정상 동작 가능한지 1회 ping.

        Raises:
            ClassifierError: 사용 불가능 상태
        """
        ...
