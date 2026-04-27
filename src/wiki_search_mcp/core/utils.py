from __future__ import annotations

"""공통 유틸리티 함수.

여러 모듈에서 공유하는 유틸리티 함수를 모아둡니다.
- tokenize: BM25 검색용 토크나이저
- parse_frontmatter: YAML frontmatter 파싱
- resolve_pages_path: pages 디렉토리 탐지
"""

import re
from pathlib import Path
from typing import Any, cast

import yaml

from wiki_search_mcp.core.types import FrontmatterDict


def tokenize(text: str) -> list[str]:
    """BM25용 토크나이저.

    한글과 영문/숫자를 모두 처리하는 간단한 토크나이저.
    1글자 토큰은 제거합니다.

    Args:
        text: 토큰화할 텍스트

    Returns:
        토큰 리스트

    Examples:
        >>> tokenize("Nginx 설정 방법")
        ['nginx', '설정', '방법']
        >>> tokenize("SSL 인증서")
        ['ssl', '인증서']
    """
    text = text.lower()
    tokens = re.findall(r"[가-힣]+|[a-z0-9]+", text)
    return [t for t in tokens if len(t) > 1]


def parse_frontmatter(content: str) -> tuple[FrontmatterDict, str]:
    """YAML frontmatter와 본문 분리.

    Markdown 파일 상단의 YAML frontmatter를 파싱합니다.
    frontmatter가 없거나 파싱 실패 시 빈 dict와 원본 내용을 반환합니다.

    Args:
        content: 전체 Markdown 내용

    Returns:
        (frontmatter dict, 본문 문자열) 튜플

    Examples:
        >>> parse_frontmatter("---\\ntitle: Test\\n---\\n# Hello")
        ({'title': 'Test'}, '# Hello')
        >>> parse_frontmatter("# No frontmatter")
        ({}, '# No frontmatter')
    """
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
                body = parts[2].strip()
                return cast(FrontmatterDict, meta), body
            except yaml.YAMLError:
                pass
    return cast(FrontmatterDict, {}), content


def normalize_document_path(path: str) -> tuple[str, str]:
    """문서 경로를 정규화.

    .md 확장자 유무에 관계없이 동일한 문서를 참조할 수 있도록
    두 가지 버전의 경로를 반환합니다.

    Args:
        path: 문서 경로 (확장자 유무 상관없음)

    Returns:
        (확장자 포함 경로, 확장자 미포함 경로) 튜플

    Examples:
        >>> normalize_document_path("docs/readme.md")
        ('docs/readme.md', 'docs/readme')
        >>> normalize_document_path("docs/readme")
        ('docs/readme.md', 'docs/readme')
    """
    if path.endswith(".md"):
        return path, path[:-3]
    return f"{path}.md", path


def path_matches(path1: str, path2: str) -> bool:
    """두 경로가 같은 문서를 가리키는지 확인.

    .md 확장자 유무에 관계없이 동일한 문서인지 비교합니다.

    Args:
        path1: 첫 번째 경로
        path2: 두 번째 경로

    Returns:
        같은 문서면 True

    Examples:
        >>> path_matches("docs/readme.md", "docs/readme")
        True
        >>> path_matches("docs/readme.md", "docs/readme.md")
        True
        >>> path_matches("docs/readme", "docs/other")
        False
    """
    return normalize_document_path(path1)[0] == normalize_document_path(path2)[0]


def resolve_pages_path(wiki_path: Path) -> Path:
    """pages 디렉토리 탐지.

    wiki_path/pages/ 디렉토리가 있으면 사용하고,
    없으면 wiki_path 자체를 문서 루트로 사용합니다.
    이를 통해 옵시디언 볼트 등 다양한 디렉토리 구조를 지원합니다.

    Args:
        wiki_path: wiki 루트 경로

    Returns:
        문서가 저장된 경로 (pages/ 또는 wiki_path 자체)

    Examples:
        >>> resolve_pages_path(Path("/wiki"))  # pages/ 있음
        PosixPath('/wiki/pages')
        >>> resolve_pages_path(Path("/obsidian-vault"))  # pages/ 없음
        PosixPath('/obsidian-vault')
    """
    pages_candidate = wiki_path / "pages"
    if pages_candidate.exists() and pages_candidate.is_dir():
        return pages_candidate
    return wiki_path
