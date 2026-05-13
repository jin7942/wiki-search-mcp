"""분류용 시스템 프롬프트 + JSON 응답 파서.

LLM은 자유 형식이므로 단일 JSON 객체만 출력하도록 시스템 프롬프트에서 강제하고,
응답 텍스트에서 첫 JSON 객체를 추출 후 dataclass로 검증한다.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from wiki_search_mcp.core.exceptions import ClassifierError
from wiki_search_mcp.core.models import ClassificationDecision
from wiki_search_mcp.services.llm.provider import ClassificationRequest

logger = logging.getLogger(__name__)


CLASSIFY_SYSTEM_PROMPT = """\
You classify a single Markdown note into one of the user's existing categories.

Rules (strict):
- Output a single JSON object only. No prose, no markdown fence, no comments.
- Schema: {"category": str, "tags": [str, ...], "confidence": number, "reasoning": str}
- "category" MUST be exactly one of the active_categories list provided by the user.
  If none fits, use the literal string "uncategorized".
- "tags": 1 to 5 short lowercase tokens that describe the note topic. No leading '#'.
- "confidence": float in [0.0, 1.0]. Use >=0.7 only when the note clearly belongs to the chosen category.
- "reasoning": one short sentence (<= 200 chars) in the same language as the note.
- Do not include any other keys. Do not add explanations outside the JSON.
"""


def build_user_prompt(req: ClassificationRequest) -> str:
    """LLM에게 보낼 user prompt 본문 생성."""
    hints = req.suggestion_hints or {}
    cat_hints = hints.get("category_candidates") or []
    tag_hints = hints.get("tag_candidates") or []
    sim = hints.get("similar_paths") or []
    active = list(req.active_categories) or ["uncategorized"]
    body = req.body_preview or ""
    return (
        f"path: {req.path}\n"
        f"active_categories: {json.dumps(active, ensure_ascii=False)}\n"
        f"heuristic_hints:\n"
        f"  category_candidates: {json.dumps(list(cat_hints), ensure_ascii=False)}\n"
        f"  tag_candidates: {json.dumps(list(tag_hints), ensure_ascii=False)}\n"
        f"  similar_paths: {json.dumps(list(sim), ensure_ascii=False)}\n"
        f"---\n"
        f"{body}\n"
        f"---\n"
        f"Return only the JSON object."
    )


_JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def parse_decision(
    *,
    path: str,
    raw: str,
    provider: str,
    active_categories: tuple[str, ...],
) -> ClassificationDecision:
    """LLM 응답 텍스트에서 첫 JSON 객체를 추출 + 검증 → ``ClassificationDecision``.

    Raises:
        ClassifierError: JSON 파싱/필드 검증 실패
    """
    if not raw or not raw.strip():
        raise ClassifierError.of("empty LLM response", code="INVALID_JSON")

    # 응답이 코드블록으로 감싸진 경우도 ``{...}`` 패턴으로 추출 가능
    m = _JSON_PATTERN.search(raw)
    if not m:
        raise ClassifierError.of(
            "no JSON object in response",
            code="INVALID_JSON",
            details={"raw_excerpt": raw[:200]},
        )
    try:
        obj: Any = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ClassifierError.of(
            f"invalid JSON: {e}",
            code="INVALID_JSON",
            details={"raw_excerpt": raw[:200]},
        ) from e

    if not isinstance(obj, dict):
        raise ClassifierError.of("response is not a JSON object", code="INVALID_JSON")

    category = obj.get("category")
    tags_raw = obj.get("tags", [])
    confidence_raw = obj.get("confidence")
    reasoning = obj.get("reasoning", "")

    if not isinstance(category, str) or not category.strip():
        raise ClassifierError.of("missing or invalid 'category'", code="INVALID_FIELDS")
    if not isinstance(tags_raw, list):
        raise ClassifierError.of("'tags' must be a list", code="INVALID_FIELDS")
    if not isinstance(confidence_raw, (int, float)):
        raise ClassifierError.of("'confidence' must be number", code="INVALID_FIELDS")
    if not isinstance(reasoning, str):
        reasoning = str(reasoning)

    tags = tuple(t.strip().lower() for t in tags_raw if isinstance(t, str) and t.strip())[:5]

    # category가 active_categories에 없으면 uncategorized로 강등 (LLM이 가끔 임의 카테고리 생성)
    if active_categories and category not in active_categories and category != "uncategorized":
        logger.warning(
            "LLM proposed unknown category %r (active=%s); demoting to 'uncategorized'",
            category,
            list(active_categories),
        )
        category = "uncategorized"

    confidence = max(0.0, min(1.0, float(confidence_raw)))
    raw_trunc = raw.strip()
    if len(raw_trunc) > 200:
        raw_trunc = raw_trunc[:200] + "..."

    return ClassificationDecision(
        path=path,
        category=category,
        tags=tags,
        confidence=confidence,
        reasoning=reasoning[:300],
        provider=provider,
        raw_response=raw_trunc,
    )
