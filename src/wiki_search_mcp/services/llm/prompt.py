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
You classify a single Markdown note into one of the user's existing categories,
and optionally into one of that category's existing subfolders.

Rules (strict):
- Output a single JSON object only. No prose, no markdown fence, no comments.
- Schema: {"category": str, "subcategory": str|null, "tags": [str, ...], "confidence": number, "reasoning": str}
- "category" MUST be exactly one of the active_categories list provided by the user.
  If none fits, use the literal string "uncategorized".
- "subcategory":
  - If the user provides subfolders_by_category[category] and one clearly fits the note,
    set it to that exact subfolder entry. Entries may be nested paths like
    "proj/meetings" — when both a folder and its subfolder fit, prefer the deepest
    (most specific) entry. The note will be placed at
    <category>/<subcategory>/<basename>.
  - Otherwise, set it to null. Do NOT invent new subfolders.
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
    # subfolders 는 dict[str, tuple] — JSON 직렬화 위해 dict[str, list] 로 변환.
    subfolders_raw = req.subfolders_by_category or {}
    subfolders = {k: list(v) for k, v in subfolders_raw.items()}
    return (
        f"path: {req.path}\n"
        f"active_categories: {json.dumps(active, ensure_ascii=False)}\n"
        f"subfolders_by_category: {json.dumps(subfolders, ensure_ascii=False)}\n"
        f"heuristic_hints:\n"
        f"  category_candidates: {json.dumps(list(cat_hints), ensure_ascii=False)}\n"
        f"  tag_candidates: {json.dumps(list(tag_hints), ensure_ascii=False)}\n"
        f"  similar_paths: {json.dumps(list(sim), ensure_ascii=False)}\n"
        f"---\n"
        f"{body}\n"
        f"---\n"
        f"Return only the JSON object."
    )


HIERARCHIZE_SYSTEM_PROMPT = """\
You review a proposed subfolder structure for one flat wiki folder and return the
final plan. The goal is grouping documents by TYPE or TOPIC so the folder stays
navigable.

Rules (strict):
- Output a single JSON object only. No prose, no markdown fence, no comments.
- Schema: {"groups": [{"name": str, "files": [str, ...]}, ...],
           "confidence": number, "reasoning": str}
- Every file you place MUST be one of the provided files (exact string match).
  Never invent files. A file may appear in at most one group. Files you leave
  out stay in the folder root (that is fine for ambiguous ones).
- "name": short folder name in the same language as the filenames. No '/', no
  leading dot. Prefer the heuristic group names when they fit.
- Keep numbered series files (00-, 01-, ... prefixes) together in ONE group.
- Do not create a group named after the folder itself (tautology).
- Groups with fewer than 2 files are not worth a folder — leave those files out.
- "confidence": float in [0.0, 1.0]. Use >=0.7 only when the grouping is clearly
  right for at least 80% of the files.
- "reasoning": one short sentence (<= 200 chars) in the language of the notes.
"""


def build_hierarchize_prompt(
    folder: str,
    files: tuple[str, ...] | list[str],
    heuristic_groups: list[dict[str, Any]],
) -> str:
    """계층화 검증용 user prompt 생성.

    Args:
        folder: 대상 폴더 상대 경로.
        files: 폴더 직계 .md 파일 basename 목록 (LLM 이 이 안에서만 선택).
        heuristic_groups: ``SubfolderGroup.to_dict()`` 목록 (휴리스틱 초안).
    """
    return (
        f"folder: {folder}\n"
        f"files: {json.dumps(list(files), ensure_ascii=False)}\n"
        f"heuristic_groups: {json.dumps(heuristic_groups, ensure_ascii=False)}\n"
        f"Return only the JSON object."
    )


_SUBFOLDER_NAME_BAD = re.compile(r"[/\\]|^\.|\.\.")


def parse_hierarchization(
    *,
    raw: str,
    allowed_files: tuple[str, ...] | list[str],
) -> tuple[list[dict[str, Any]], float, str]:
    """LLM 계층화 응답 파싱 + 검증.

    검증 정책:
    - ``allowed_files`` 밖의 파일은 버린다 (LLM 창작 방지).
    - 한 파일은 첫 등장 그룹에만 남긴다.
    - 그룹 이름에 경로 구분자/선행 점이 있으면 그 그룹을 버린다.
    - 검증 후 파일 2개 미만 그룹은 버린다.

    Returns:
        ``(groups, confidence, reasoning)`` — groups 는
        ``[{"name": str, "files": [str, ...]}]``.

    Raises:
        ClassifierError: JSON 파싱/필드 검증 실패.
    """
    if not raw or not raw.strip():
        raise ClassifierError.of("empty LLM response", code="INVALID_JSON")
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

    groups_raw = obj.get("groups")
    confidence_raw = obj.get("confidence")
    reasoning = obj.get("reasoning", "")
    if not isinstance(groups_raw, list):
        raise ClassifierError.of("'groups' must be a list", code="INVALID_FIELDS")
    if not isinstance(confidence_raw, (int, float)):
        raise ClassifierError.of("'confidence' must be number", code="INVALID_FIELDS")
    if not isinstance(reasoning, str):
        reasoning = str(reasoning)

    allowed = set(allowed_files)
    assigned: set[str] = set()
    groups: list[dict[str, Any]] = []
    for g in groups_raw:
        if not isinstance(g, dict):
            continue
        name = g.get("name")
        files = g.get("files")
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        if _SUBFOLDER_NAME_BAD.search(name):
            logger.warning("dropping group with invalid folder name %r", name)
            continue
        if not isinstance(files, list):
            continue
        members = []
        for f in files:
            if isinstance(f, str) and f in allowed and f not in assigned:
                members.append(f)
                assigned.add(f)
        if len(members) < 2:
            for f in members:
                assigned.discard(f)
            continue
        groups.append({"name": name, "files": members})

    confidence = max(0.0, min(1.0, float(confidence_raw)))
    return groups, confidence, reasoning[:300]


_JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def parse_decision(
    *,
    path: str,
    raw: str,
    provider: str,
    active_categories: tuple[str, ...],
    subfolders_by_category: dict[str, tuple[str, ...]] | None = None,
) -> ClassificationDecision:
    """LLM 응답 텍스트에서 첫 JSON 객체를 추출 + 검증 → ``ClassificationDecision``.

    Args:
        subfolders_by_category: 각 카테고리의 활성 서브폴더 화이트리스트. 주어지면
            LLM 이 제안한 ``subcategory`` 가 해당 카테고리의 화이트리스트에 있을 때만
            채택하고, 아니면 ``None`` 으로 강등 (임의 서브폴더 생성 방지).

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
    subcategory_raw = obj.get("subcategory")
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

    # subcategory 정규화 — 화이트리스트에 있을 때만 채택.
    subcategory: str | None = None
    if isinstance(subcategory_raw, str) and subcategory_raw.strip():
        candidate = subcategory_raw.strip()
        whitelist = (subfolders_by_category or {}).get(category, ())
        if candidate in whitelist:
            subcategory = candidate
        else:
            if whitelist:
                logger.warning(
                    "LLM proposed unknown subcategory %r for %r (active=%s); dropping",
                    candidate,
                    category,
                    list(whitelist),
                )
            else:
                logger.debug(
                    "LLM proposed subcategory %r for %r but no subfolders are active; dropping",
                    candidate,
                    category,
                )

    confidence = max(0.0, min(1.0, float(confidence_raw)))
    raw_trunc = raw.strip()
    if len(raw_trunc) > 200:
        raw_trunc = raw_trunc[:200] + "..."

    return ClassificationDecision(
        path=path,
        category=category,
        subcategory=subcategory,
        tags=tags,
        confidence=confidence,
        reasoning=reasoning[:300],
        provider=provider,
        raw_response=raw_trunc,
    )
