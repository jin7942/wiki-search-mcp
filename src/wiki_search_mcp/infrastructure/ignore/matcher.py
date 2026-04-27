from __future__ import annotations

"""무시 패턴 매처.

설정 파일 없이 다음 우선순위로 무시 대상을 결정합니다.

1. 하드코딩 dot-prefix: 이름이 점(.)으로 시작하는 모든 디렉토리/파일
   (.git, .obsidian, .vectordb, .DS_Store 등 자동 포괄)
2. .gitignore 자동 파싱: wiki 루트에 .gitignore가 있으면 fnmatch 기반 적용
3. WIKI_IGNORE 환경변수: 콤마(,) 구분 추가 패턴

사용 예:
    matcher = IgnoreMatcher.from_wiki(wiki_path)
    if matcher.should_ignore(path):
        ...
"""

import fnmatch
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# 추가 하드코딩 패턴: dot-prefix로 잡히지 않는 흔한 노이즈
_FALLBACK_PATTERNS: tuple[str, ...] = (
    "node_modules",
    "__pycache__",
)


def _parse_gitignore(gitignore_path: Path) -> list[str]:
    """.gitignore 파일을 파싱하여 패턴 리스트 반환.

    주석(#)과 빈 줄을 제외합니다. negation(!)과 ** 같은 고급 시맨틱은
    1차 구현에서 단순화하여 처리합니다.

    Args:
        gitignore_path: .gitignore 파일 경로

    Returns:
        패턴 문자열 리스트 (빈 리스트 가능)
    """
    try:
        lines = gitignore_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        logger.warning(f"Failed to read .gitignore: {e}")
        return []

    patterns: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # negation(!)은 1차 구현에서 미지원: 무시
        if stripped.startswith("!"):
            continue
        # 끝의 / 제거 (디렉토리 표기 제거 후 일반 패턴으로 처리)
        if stripped.endswith("/"):
            stripped = stripped[:-1]
        if stripped:
            patterns.append(stripped)
    return patterns


def _parse_env_patterns() -> list[str]:
    """WIKI_IGNORE 환경변수 파싱.

    콤마(,) 구분 패턴 리스트로 반환합니다.

    Returns:
        패턴 리스트 (빈 리스트 가능)
    """
    raw = os.getenv("WIKI_IGNORE", "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


@dataclass(frozen=True)
class IgnoreMatcher:
    """파일/디렉토리 무시 여부 판단기.

    Attributes:
        wiki_path: wiki 루트 경로 (상대 경로 계산 기준)
        gitignore_patterns: .gitignore에서 로드된 패턴
        env_patterns: WIKI_IGNORE 환경변수 패턴
        fallback_patterns: 추가 하드코딩 패턴 (node_modules 등)
    """

    wiki_path: Path
    gitignore_patterns: tuple[str, ...] = field(default_factory=tuple)
    env_patterns: tuple[str, ...] = field(default_factory=tuple)
    fallback_patterns: tuple[str, ...] = _FALLBACK_PATTERNS

    @classmethod
    def from_wiki(cls, wiki_path: Path) -> "IgnoreMatcher":
        """wiki 경로 기준으로 IgnoreMatcher 생성.

        Args:
            wiki_path: wiki 루트 경로

        Returns:
            IgnoreMatcher 인스턴스
        """
        gitignore = wiki_path / ".gitignore"
        gitignore_patterns: tuple[str, ...] = ()
        if gitignore.exists():
            gitignore_patterns = tuple(_parse_gitignore(gitignore))

        env_patterns = tuple(_parse_env_patterns())

        return cls(
            wiki_path=wiki_path,
            gitignore_patterns=gitignore_patterns,
            env_patterns=env_patterns,
        )

    @property
    def gitignore_loaded(self) -> bool:
        """.gitignore 패턴이 로드되었는지 여부."""
        return len(self.gitignore_patterns) > 0

    def should_ignore(self, path: Path) -> bool:
        """경로 무시 여부 판단.

        다음 순서로 검사합니다:
        1. 경로의 어떤 컴포넌트라도 점(.)으로 시작하면 무시
        2. fallback 패턴(node_modules 등)에 컴포넌트가 일치하면 무시
        3. .gitignore 패턴 매칭
        4. WIKI_IGNORE 환경변수 패턴 매칭

        Args:
            path: 검사할 경로 (절대/상대 모두 허용)

        Returns:
            True면 무시, False면 포함
        """
        # 1. dot-prefix: 경로 컴포넌트 중 하나라도 .으로 시작하면 무시
        for part in path.parts:
            if part.startswith(".") and part not in (".", ".."):
                return True

        # 2. fallback: 컴포넌트 정확히 일치
        for part in path.parts:
            if part in self.fallback_patterns:
                return True

        # 3, 4. gitignore + env 패턴 매칭
        rel_path = self._to_relative(path)
        all_patterns = (*self.gitignore_patterns, *self.env_patterns)
        for pattern in all_patterns:
            if self._matches_pattern(rel_path, pattern):
                return True
            # path basename도 매칭 시도 (gitignore 시맨틱)
            if fnmatch.fnmatch(path.name, pattern):
                return True

        return False

    def _to_relative(self, path: Path) -> str:
        """wiki_path 기준 상대 경로 문자열로 변환.

        절대 경로면 wiki_path 기준 상대 경로로, 상대 경로면 그대로 반환합니다.
        """
        try:
            if path.is_absolute():
                return str(path.relative_to(self.wiki_path))
        except ValueError:
            # wiki_path 외부면 절대 경로 유지
            pass
        return str(path)

    @staticmethod
    def _matches_pattern(rel_path: str, pattern: str) -> bool:
        """경로 컴포넌트 단위 fnmatch.

        패턴이 슬래시를 포함하면 전체 경로 매칭, 그렇지 않으면 각 컴포넌트 매칭.
        """
        if "/" in pattern:
            return fnmatch.fnmatch(rel_path, pattern)
        # 컴포넌트 단위 매칭
        for part in rel_path.split(os.sep):
            if fnmatch.fnmatch(part, pattern):
                return True
        return False
