"""Path validation utility.

경로 검증 및 정규화를 담당합니다.
Path Traversal 공격 방어가 주요 목적입니다.

사용 예:
    from wiki_search_mcp.core.path_validator import validate_path

    try:
        safe_path = validate_path("docs/readme.md", base_dir)
    except InvalidPathError:
        # 경로 탐색 공격 시도
        pass
"""

from __future__ import annotations

import re
from pathlib import Path

from wiki_search_mcp.core.exceptions import InvalidPathError

# 허용 문자 패턴: 알파벳, 숫자, 한글(유니코드), 하이픈, 언더스코어, 점, 슬래시
# 완전한 유니코드 지원: 일본어, 중국어 등도 포함
SAFE_PATH_PATTERN = re.compile(r"^[\w\-./\u3131-\uD79D\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]+$", re.UNICODE)


def validate_path(path: str, base_dir: Path | None = None) -> str:
    """경로 검증 및 정규화.

    Path Traversal 공격을 방어하고 경로를 정규화합니다.

    Args:
        path: 검증할 상대 경로
        base_dir: 기준 디렉토리 (None이면 기본 검증만 수행)

    Returns:
        정규화된 경로 문자열 (.md 확장자 포함)

    Raises:
        InvalidPathError: 유효하지 않은 경로
            - 빈 문자열
            - 절대 경로 (/로 시작)
            - 상위 디렉토리 탐색 (..)
            - 허용되지 않은 문자
            - base_dir 외부 접근 시도

    Examples:
        >>> validate_path("docs/readme.md")
        'docs/readme.md'
        >>> validate_path("docs/readme")  # .md 자동 추가
        'docs/readme.md'
        >>> validate_path("../etc/passwd")  # InvalidPathError
        >>> validate_path("/etc/passwd")    # InvalidPathError
    """
    # 빈 문자열 검사
    if not path or not path.strip():
        raise InvalidPathError.of(path or "<empty>")

    path = path.strip()

    # 절대 경로 검사
    if path.startswith("/"):
        raise InvalidPathError.of(path)

    # Path Traversal 방어: .. 시퀀스 검사
    if ".." in path:
        raise InvalidPathError.of(path)

    # 허용 문자 검사
    if not SAFE_PATH_PATTERN.match(path):
        raise InvalidPathError.of(path)

    # .md 확장자 정규화
    normalized_path = path if path.endswith(".md") else f"{path}.md"

    # base_dir가 주어진 경우 추가 검증
    if base_dir is not None:
        _validate_within_base(normalized_path, base_dir)

    return normalized_path


def _validate_within_base(path: str, base_dir: Path) -> None:
    """경로가 base_dir 내부에 있는지 검증.

    resolve()를 사용하여 symlink 기반 공격도 방어합니다.

    Args:
        path: 상대 경로
        base_dir: 기준 디렉토리

    Raises:
        InvalidPathError: base_dir 외부 접근 시도
    """
    try:
        base_resolved = base_dir.resolve()
        full_path = (base_dir / path).resolve()

        # Python 3.9+: is_relative_to 사용
        if not full_path.is_relative_to(base_resolved):
            raise InvalidPathError.of(path)
    except (ValueError, OSError):
        # 경로 해석 실패 시 안전하게 거부
        raise InvalidPathError.of(path)


def validate_path_for_query(path: str) -> str:
    """쿼리용 경로 검증.

    find_by_path() 등 조회 시 사용합니다.
    base_dir 검증 없이 기본 검증만 수행합니다.

    Args:
        path: 검증할 경로

    Returns:
        검증된 경로 (확장자 정규화 없음)

    Raises:
        InvalidPathError: 유효하지 않은 경로
    """
    if not path or not path.strip():
        raise InvalidPathError.of(path or "<empty>")

    path = path.strip()

    if path.startswith("/"):
        raise InvalidPathError.of(path)

    if ".." in path:
        raise InvalidPathError.of(path)

    if not SAFE_PATH_PATTERN.match(path):
        raise InvalidPathError.of(path)

    return path
