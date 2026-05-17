"""Path validation utility.

경로 검증 및 정규화를 담당합니다. Path Traversal 공격 방어가 주요 목적입니다.

방어 전략 (v0.2.6 이후):
- **명시적 블랙리스트**: 빈 문자열, 절대 경로(``/`` 시작), ``..`` 시퀀스,
  NUL 바이트, 백슬래시(Windows 경로 인젝션), ``%`` (URL 인코딩 우회).
- **핵심 방어막**: ``_validate_within_base()``의 ``resolve() + is_relative_to(base)``.
  symlink 우회까지 포함해서 실제 traversal을 막는다.
- 화이트리스트 정규식은 **사용하지 않는다** — OS가 받아주는 정상 파일명
  (공백/괄호/이모지/한글/한자 등)을 거부하면 사용자가 자신의 vault에 둔
  파일을 분류하지 못하는 오탐이 발생한다.

사용 예:
    from wiki_search_mcp.core.path_validator import validate_path

    try:
        safe_path = validate_path("docs/readme.md", base_dir)
    except InvalidPathError as e:
        # e.context.details["reason"] 으로 거부 사유 구분 가능
        pass
"""

from __future__ import annotations

from pathlib import Path

from wiki_search_mcp.core.exceptions import InvalidPathError


def _basic_checks(path: str) -> str:
    """공통 1차 검증. 통과하면 trim된 경로 반환, 실패하면 ``InvalidPathError`` raise.

    Args:
        path: 검증할 경로 (원본)

    Returns:
        trim된 경로 문자열

    Raises:
        InvalidPathError: ``reason`` 컨텍스트와 함께
            - ``empty``: trim 후 빈
            - ``absolute``: ``/``로 시작
            - ``parent_traversal``: ``..`` 포함
            - ``null_byte``: ``\\x00`` 포함
            - ``backslash``: ``\\`` 포함 (Windows 경로 인젝션 방어)
            - ``percent_encoded``: ``%`` 포함 (URL 인코딩 우회 방어)
    """
    if not path or not path.strip():
        raise InvalidPathError.of(path or "<empty>", reason="empty")

    stripped = path.strip()

    if stripped.startswith("/"):
        raise InvalidPathError.of(stripped, reason="absolute")

    if ".." in stripped:
        raise InvalidPathError.of(stripped, reason="parent_traversal")

    if "\x00" in stripped:
        raise InvalidPathError.of(stripped, reason="null_byte")

    if "\\" in stripped:
        raise InvalidPathError.of(stripped, reason="backslash")

    if "%" in stripped:
        raise InvalidPathError.of(stripped, reason="percent_encoded")

    return stripped


def validate_path(path: str, base_dir: Path | None = None) -> str:
    """경로 검증 및 정규화.

    Path Traversal 공격을 방어하고 경로를 정규화합니다.

    Args:
        path: 검증할 상대 경로
        base_dir: 기준 디렉토리 (None이면 기본 검증만 수행)

    Returns:
        정규화된 경로 문자열 (.md 확장자 포함)

    Raises:
        InvalidPathError: 유효하지 않은 경로. ``context.details["reason"]``으로
            거부 사유를 구분할 수 있다 (empty/absolute/parent_traversal/null_byte/
            backslash/percent_encoded/outside_base/resolve_failed).

    Examples:
        >>> validate_path("docs/readme.md")
        'docs/readme.md'
        >>> validate_path("docs/readme")  # .md 자동 추가
        'docs/readme.md'
        >>> validate_path("../etc/passwd")  # InvalidPathError(reason=parent_traversal)
        >>> validate_path("/etc/passwd")    # InvalidPathError(reason=absolute)
    """
    stripped = _basic_checks(path)

    # .md 확장자 정규화
    normalized_path = stripped if stripped.endswith(".md") else f"{stripped}.md"

    # base_dir가 주어진 경우 추가 검증
    if base_dir is not None:
        _validate_within_base(normalized_path, base_dir)

    return normalized_path


def _validate_within_base(path: str, base_dir: Path) -> None:
    """경로가 base_dir 내부에 있는지 검증.

    ``resolve()``를 사용하여 symlink 기반 공격도 방어합니다. 화이트리스트
    정규식을 제거한 v0.2.6 이후로 이 검증이 traversal 방어의 핵심이 됩니다.

    Args:
        path: 상대 경로
        base_dir: 기준 디렉토리

    Raises:
        InvalidPathError(reason="outside_base"): resolve 후 base_dir 밖을 가리킬 때
        InvalidPathError(reason="resolve_failed"): resolve 자체가 실패할 때
    """
    try:
        base_resolved = base_dir.resolve()
        full_path = (base_dir / path).resolve()

        if not full_path.is_relative_to(base_resolved):
            raise InvalidPathError.of(path, reason="outside_base")
    except InvalidPathError:
        raise
    except (ValueError, OSError):
        # 경로 해석 실패 시 안전하게 거부
        raise InvalidPathError.of(path, reason="resolve_failed")


def validate_path_for_query(path: str) -> str:
    """쿼리용 경로 검증.

    ``find_by_path()`` 등 조회 시 사용합니다. ``base_dir`` 검증 없이 기본 검증만
    수행하고 ``.md`` 확장자 정규화도 하지 않습니다.

    Args:
        path: 검증할 경로

    Returns:
        trim된 경로 문자열

    Raises:
        InvalidPathError: 유효하지 않은 경로. ``context.details["reason"]``로 사유 구분.
    """
    return _basic_checks(path)
