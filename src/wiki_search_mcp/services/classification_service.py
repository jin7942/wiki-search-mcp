from __future__ import annotations

"""Classification service.

미분류 파일 감지(``find_pending``)와 분류 추천(``suggest_classification``)을
담당합니다. MCP는 read-only 원칙을 유지하므로 이 서비스는 추천만 반환하고
실제 파일 수정은 Claude가 일반 도구로 수행합니다.

성능:
- ``find_pending``은 인덱스 기반 추출 우선 → 신규 파일은 set 차집합
- 60초 TTL 캐싱으로 디렉토리 재스캔 비용 최소화
- ``suggest_classification``은 기존 임베딩을 우선 활용 (재인코딩 회피)
"""

import logging
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from wiki_search_mcp.core.config import LISTING_TTL_SECONDS, is_staging_folder
from wiki_search_mcp.core.exceptions import DocumentNotFoundError
from wiki_search_mcp.core.models import (
    ClassificationSuggestion,
    FilenameNormalization,
    FilenameRename,
    FolderHealth,
    HealthReport,
    PendingItem,
    SubfolderGroup,
    SubfolderSuggestion,
)
from wiki_search_mcp.core.path_validator import validate_dir_path, validate_path
from wiki_search_mcp.core.utils import parse_frontmatter
from wiki_search_mcp.services.tagger_service import AutoTagger

if TYPE_CHECKING:
    from wiki_search_mcp.core.protocols import VectorRepository
    from wiki_search_mcp.infrastructure.ignore import IgnoreMatcher
    from wiki_search_mcp.services.category_service import CategoryService
    from wiki_search_mcp.services.document_service import DocumentService

logger = logging.getLogger(__name__)


def _format_mtime(path: Path) -> str | None:
    """파일 mtime을 ISO 8601 문자열로 반환."""
    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, timezone.utc).isoformat()
    except OSError:
        return None


class ClassificationService:
    """미분류 파일 감지 + 분류 추천.

    Attributes:
        pages_path: 페이지 루트
        vector_repository: 인덱스 조회 (pending/추천 모두에서 사용)
        document_service: 유사 문서 조회
        category_service: 카테고리 후보 조회
        ignore_matcher: 무시 패턴 매처
    """

    def __init__(
        self,
        pages_path: Path,
        vector_repository: "VectorRepository",
        document_service: "DocumentService",
        category_service: "CategoryService",
        ignore_matcher: "IgnoreMatcher",
        clock: callable = time.monotonic,
    ):
        """ClassificationService 초기화.

        Args:
            pages_path: 페이지 루트 (rglob 기준)
            vector_repository: 벡터 저장소
            document_service: 문서 서비스
            category_service: 카테고리 서비스
            ignore_matcher: 무시 매처
            clock: 캐시 만료 판정용 시계
        """
        self._pages_path = pages_path
        self._vector = vector_repository
        self._document_service = document_service
        self._category_service = category_service
        self._ignore_matcher = ignore_matcher
        self._clock = clock
        self._cached_pending: list[PendingItem] | None = None
        self._cached_at: float = 0.0

    def find_pending(self, limit: int = 50) -> list[PendingItem]:
        """미분류 / 정리 대기 파일 목록 반환.

        다음 두 소스를 합쳐 결과를 만듭니다.
        1. 인덱스: ``category``가 비어있거나 ``uncategorized``인 문서
        2. 디스크: 인덱스에 없는 신규 .md 파일

        결과는 60초 TTL로 캐시됩니다.

        Args:
            limit: 반환할 최대 개수

        Returns:
            PendingItem 리스트
        """
        if self._is_cache_valid():
            return (self._cached_pending or [])[:limit]

        # 인덱스를 한 번만 읽어 1차/2차에서 공유(과거엔 to_arrow_list 2회 호출).
        indexed_docs = self._read_indexed_docs()
        indexed_paths = {(d.get("path") or "").strip() for d in indexed_docs}

        seen_paths: set[str] = set()
        items: list[PendingItem] = []
        items.extend(self._pending_from_index(indexed_docs, seen_paths))
        items.extend(self._pending_from_disk(indexed_paths, seen_paths))

        self._sort_pending(items)

        # 캐시 갱신
        self._cached_pending = items
        self._cached_at = self._clock()

        return items[:limit]

    def _read_indexed_docs(self) -> list[dict]:
        """인덱스 문서 목록(실패/미존재 시 빈 리스트)."""
        if not self._vector.exists():
            return []
        try:
            return self._vector.to_arrow_list()
        except Exception as e:
            logger.warning(f"Failed to read vector index: {e}")
            return []

    def _pending_from_index(
        self, indexed_docs: list[dict], seen_paths: set[str]
    ) -> list[PendingItem]:
        """1차: 인덱스에서 분류 부족 문서 추출.

        staging 폴더 파일은 frontmatter 상태와 무관하게 항상 pending(daemon 이
        카테고리 폴더로 다시 이동시켜야 함). 그 외엔 category/tags 부족만.
        ``seen_paths`` 에 처리한 경로를 누적해 2차와 중복을 막는다.
        """
        items: list[PendingItem] = []
        for doc in indexed_docs:
            path = (doc.get("path") or "").strip()
            if not path or path in seen_paths:
                continue

            first = path.split("/", 1)[0] if "/" in path else ""
            if first and is_staging_folder(first):
                reason: str | None = "in_staging"
            else:
                category = (doc.get("category") or "").strip()
                tags = doc.get("tags") or []
                reason = self._categorize_indexed_doc(category, tags)
                if reason is None:
                    continue

            full_path = self._pages_path / path
            items.append(
                PendingItem.of(path=path, reason=reason, mtime=_format_mtime(full_path))
            )
            seen_paths.add(path)
        return items

    def _pending_from_disk(
        self, indexed_paths: set[str], seen_paths: set[str]
    ) -> list[PendingItem]:
        """2차: 인덱스에 없는 신규 디스크 파일(+ staging 은 항상 포함)."""
        try:
            disk_files = self._scan_disk_files()
        except OSError as e:
            logger.warning(f"Failed to scan disk: {e}")
            return []

        items: list[PendingItem] = []
        for rel_path in disk_files:
            if rel_path in seen_paths:
                continue
            first = rel_path.split("/", 1)[0] if "/" in rel_path else ""
            is_staging = bool(first) and is_staging_folder(first)
            # staging 파일은 인덱스 유무와 무관하게 항상 노출.
            if not is_staging and rel_path in indexed_paths:
                continue
            full_path = self._pages_path / rel_path
            reason = "in_staging" if is_staging else "not_indexed"
            items.append(
                PendingItem.of(path=rel_path, reason=reason, mtime=_format_mtime(full_path))
            )
            seen_paths.add(rel_path)
        return items

    @staticmethod
    def _sort_pending(items: list[PendingItem]) -> None:
        """in_staging → not_indexed → no_frontmatter → no_category, 동일 reason 은 path 순."""
        reason_order = {
            "in_staging": 0,
            "not_indexed": 1,
            "no_frontmatter": 2,
            "no_category": 3,
        }
        items.sort(key=lambda it: (reason_order.get(it.reason, 9), it.path))

    def suggest_classification(self, path: str) -> ClassificationSuggestion:
        """단일 파일에 대한 카테고리/태그 추천.

        Args:
            path: 대상 파일 상대 경로

        Returns:
            ClassificationSuggestion (path가 존재하지 않으면 빈 제안)

        Raises:
            InvalidPathError: 경로 검증 실패
            DocumentNotFoundError: 파일이 디스크에도 인덱스에도 없음
        """
        normalized = validate_path(path, self._pages_path)
        content = self._load_content(normalized)

        # 유사 문서를 한 번만 조회해 카테고리 투표와 유사경로 표시에 공유한다.
        # (과거엔 _compute_category_candidates 와 _compute_similar_paths 가
        # 각각 get_similar 를 호출해 동일 검색을 2번 수행했다.)
        similar_docs = self._get_similar_docs(normalized, top_k=5)

        category_candidates, signal_count = self._compute_category_candidates(
            normalized, similar_docs
        )
        tag_candidates = self._compute_tag_candidates(content, AutoTagger())
        similar_paths = tuple(
            getattr(doc, "path", "") for doc in similar_docs if getattr(doc, "path", "")
        )

        reasoning = self._build_reasoning(
            category_candidates, tag_candidates, similar_paths, signal_count
        )

        return ClassificationSuggestion.of(
            path=normalized,
            category_candidates=category_candidates,
            tag_candidates=tag_candidates,
            similar_paths=similar_paths,
            reasoning=reasoning,
        )

    def suggest_subfolders(
        self, folder_path: str, min_cluster_size: int = 3
    ) -> SubfolderSuggestion:
        """평면 폴더의 서브폴더 계층화 제안(read-only).

        폴더 직계 .md 파일들의 frontmatter 태그 + 본문 키워드를 모아 공통
        신호로 그룹을 만든다. ``min_cluster_size`` 이상 묶이는 신호만 서브폴더
        후보가 된다. 큰 그룹부터 파일을 선점(greedy)해 한 파일이 여러 그룹에
        중복되지 않게 한다. 어느 그룹에도 못 든 파일은 ``unclassified``.

        실제 폴더 생성/이동은 하지 않는다(보고서 #1/#3, read-only 정책 유지).

        Args:
            folder_path: 대상 폴더 상대 경로(pages 기준). 예: ``"projects/KT_ITPARK"``.
            min_cluster_size: 서브폴더로 제안할 최소 파일 수. 기본 3.

        Returns:
            SubfolderSuggestion. 폴더가 없거나 파일이 부족하면 빈 제안.

        Raises:
            InvalidPathError: 경로 검증 실패.
        """
        normalized = validate_dir_path(folder_path, self._pages_path)
        folder = self._pages_path / normalized
        if not folder.is_dir():
            return SubfolderSuggestion(
                folder=normalized,
                file_count=0,
                reasoning="폴더가 존재하지 않음",
            )

        files = self._list_direct_md(folder, normalized)
        if len(files) < min_cluster_size:
            return SubfolderSuggestion(
                folder=normalized,
                file_count=len(files),
                reasoning=(
                    f"파일 {len(files)}개 — 계층화 임계({min_cluster_size}) 미만, "
                    "평면 유지 권장"
                ),
            )

        signals = {rel: self._collect_signals(rel) for rel in files}
        groups, unclassified = self._cluster_by_signal(
            files, signals, min_cluster_size
        )

        if not groups:
            reasoning = (
                f"파일 {len(files)}개지만 {min_cluster_size}개 이상 묶이는 공통 "
                "태그/키워드 없음 — 서브폴더 제안 보류"
            )
        else:
            reasoning = (
                f"파일 {len(files)}개 → 공통 신호 기준 {len(groups)}개 그룹 제안 "
                f"(미분류 {len(unclassified)}개)"
            )

        return SubfolderSuggestion(
            folder=normalized,
            file_count=len(files),
            groups=tuple(groups),
            unclassified=tuple(unclassified),
            reasoning=reasoning,
        )

    def _list_direct_md(self, folder: Path, normalized: str) -> list[str]:
        """폴더 직계(하위 폴더 제외) .md 파일의 pages 기준 상대 경로."""
        rels: list[str] = []
        try:
            for entry in folder.iterdir():
                if not entry.is_file() or entry.suffix.lower() != ".md":
                    continue
                if self._ignore_matcher.should_ignore(entry):
                    continue
                rels.append(f"{normalized}/{entry.name}")
        except OSError as e:
            logger.warning(f"Failed to list {folder}: {e}")
        rels.sort()
        return rels

    def _collect_signals(self, rel_path: str) -> set[str]:
        """파일의 분류 신호(frontmatter 태그 + 본문 키워드) 집합.

        태그는 소문자 정규화. 본문 키워드는 AutoTagger 의 기술 용어 추출을
        사용한다. 읽기 실패 시 빈 집합.
        """
        full = self._pages_path / rel_path
        try:
            content = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return set()

        meta, body = parse_frontmatter(content)
        signals: set[str] = set()

        raw_tags = meta.get("tags")
        if isinstance(raw_tags, list):
            for t in raw_tags:
                if isinstance(t, str) and t.strip():
                    signals.add(t.strip().lower())
        elif isinstance(raw_tags, str) and raw_tags.strip():
            signals.add(raw_tags.strip().lower())

        if body.strip():
            tagger = AutoTagger()
            for kw in tagger.extract_technical_terms(body, top_n=5):
                signals.add(kw.strip().lower())

        return signals

    @staticmethod
    def _cluster_by_signal(
        files: list[str],
        signals: dict[str, set[str]],
        min_cluster_size: int,
    ) -> tuple[list[SubfolderGroup], list[str]]:
        """공통 신호로 파일을 그룹핑(greedy, 큰 그룹 우선 선점).

        1) 신호별 보유 파일 수를 센다.
        2) ``min_cluster_size`` 이상인 신호를 빈도 내림차순으로 본다.
        3) 아직 미할당인 파일만 모아 그룹을 만들고, 그 크기가 여전히 임계
           이상이면 그룹 확정(선점). 한 파일은 한 그룹에만 든다.

        Returns:
            ``(그룹 리스트(크기 내림차순), 미분류 파일 리스트)``.
        """
        signal_files: dict[str, list[str]] = {}
        for rel in files:
            for sig in signals.get(rel, set()):
                signal_files.setdefault(sig, []).append(rel)

        # 후보 신호: 임계 이상. 동률은 신호명 사전순으로 결정적 정렬.
        candidates = sorted(
            (s for s, fs in signal_files.items() if len(fs) >= min_cluster_size),
            key=lambda s: (-len(signal_files[s]), s),
        )

        assigned: set[str] = set()
        groups: list[SubfolderGroup] = []
        for sig in candidates:
            members = [
                rel for rel in signal_files[sig] if rel not in assigned
            ]
            if len(members) < min_cluster_size:
                continue
            members.sort()
            assigned.update(members)
            groups.append(
                SubfolderGroup(
                    name=sig,
                    files=tuple(members),
                    signal=f"공통 태그/키워드 '{sig}' ({len(members)}개)",
                )
            )

        groups.sort(key=lambda g: (-len(g.files), g.name))
        unclassified = sorted(rel for rel in files if rel not in assigned)
        return groups, unclassified

    # ------------------------------------------------------------------
    # 구조 건강 진단 (read-only)
    # ------------------------------------------------------------------

    def health_check(self, threshold_flat: int = 10) -> HealthReport:
        """Wiki 폴더 구조 건강 진단(read-only).

        모든 폴더를 순회하며 두 가지를 찾는다.
        1) 평면 누적: 직계 .md 파일이 ``threshold_flat`` 이상인데 서브폴더가
           없는 폴더 → 계층화 권장(``wiki_suggest_subfolders`` 대상).
        2) 빈 폴더: .md 파일이 0개인 폴더(하위 어디에도 .md 없음).

        Args:
            threshold_flat: 평면 누적 경고 임계(직계 파일 수).

        Returns:
            HealthReport. 제안만 반환하며 아무 것도 수정하지 않는다.
        """
        if not self._pages_path.exists():
            return HealthReport(reasoning="pages 경로가 존재하지 않음")

        needs: list[FolderHealth] = []
        empty: list[str] = []

        for folder in self._iter_folders():
            rel = self._rel(folder)
            direct_md = self._count_direct_md(folder)
            has_subfolders = self._has_subfolders(folder)

            if self._is_empty_of_md(folder):
                empty.append(rel)
                continue

            if direct_md >= threshold_flat and not has_subfolders:
                needs.append(
                    FolderHealth(
                        path=rel,
                        file_count=direct_md,
                        has_subfolders=has_subfolders,
                    )
                )

        needs.sort(key=lambda f: (-f.file_count, f.path))
        empty.sort()

        reasoning = (
            f"계층화 권장 {len(needs)}곳(직계 ≥{threshold_flat}, 서브폴더 없음), "
            f"빈 폴더 {len(empty)}곳"
        )
        return HealthReport(
            needs_hierarchization=tuple(needs),
            empty_folders=tuple(empty),
            reasoning=reasoning,
        )

    def _iter_folders(self):
        """pages 하위의 모든 폴더(무시 패턴/staging 제외). pages 루트 자신 제외."""
        for entry in self._pages_path.rglob("*"):
            if not entry.is_dir():
                continue
            if self._ignore_matcher.should_ignore(entry):
                continue
            if is_staging_folder(entry.name):
                continue
            yield entry

    def _rel(self, folder: Path) -> str:
        """pages 기준 상대 경로 문자열(슬래시 정규화)."""
        return str(folder.relative_to(self._pages_path)).replace("\\", "/")

    def _count_direct_md(self, folder: Path) -> int:
        """폴더 직계 .md 수(무시 패턴 제외)."""
        count = 0
        try:
            for entry in folder.iterdir():
                if (
                    entry.is_file()
                    and entry.suffix.lower() == ".md"
                    and not self._ignore_matcher.should_ignore(entry)
                ):
                    count += 1
        except OSError:
            return 0
        return count

    def _has_subfolders(self, folder: Path) -> bool:
        """폴더에 (무시/staging 아닌) 하위 폴더가 있는지."""
        try:
            for entry in folder.iterdir():
                if not entry.is_dir():
                    continue
                if self._ignore_matcher.should_ignore(entry):
                    continue
                if is_staging_folder(entry.name):
                    continue
                return True
        except OSError:
            return False
        return False

    def _is_empty_of_md(self, folder: Path) -> bool:
        """폴더 하위 어디에도 .md 가 없으면 True(빈 폴더 진단)."""
        try:
            for md in folder.rglob("*.md"):
                if not self._ignore_matcher.should_ignore(md):
                    return False
        except OSError:
            return False
        return True

    # ------------------------------------------------------------------
    # 파일명 정규화 제안 (read-only)
    # ------------------------------------------------------------------

    # 다양한 날짜 표기를 표준 YYYY-MM-DD 로 정규화하기 위한 패턴.
    # 파일명 선두의 날짜만 대상으로 한다(본문 영향 없음).
    _DATE_PATTERNS = (
        # 2026-05-19 / 2026.05.12 / 2026_05_19 / 2026/05/19
        re.compile(r"^(?P<y>\d{4})[._/-](?P<m>\d{1,2})[._/-](?P<d>\d{1,2})"),
        # 260513 / 20260513 (구분자 없는 YYMMDD / YYYYMMDD)
        re.compile(r"^(?P<digits>\d{6}|\d{8})(?=\D|$)"),
        # 26.05.11 / 26-05-11 (YY 구분자)
        re.compile(r"^(?P<yy>\d{2})[._-](?P<m>\d{1,2})[._-](?P<d>\d{1,2})"),
    )

    def suggest_filename_normalization(
        self, folder_path: str | None = None
    ) -> FilenameNormalization:
        """파일명 선두 날짜를 표준 ``YYYY-MM-DD`` 로 정규화 제안(read-only).

        제안만 반환한다. 실제 rename/백링크 갱신은 하지 않는다(read-only
        정책: 이동/링크 수정은 LLM 이 검토 후 수행).

        Args:
            folder_path: 대상 폴더(pages 기준). None 이면 pages 전체.

        Returns:
            FilenameNormalization. 정규화할 게 없으면 빈 candidates.

        Raises:
            InvalidPathError: folder_path 검증 실패.
        """
        if folder_path is None:
            base = self._pages_path
        else:
            # validate_dir_path 는 traversal 검증 부작용으로도 필요(예외 raise).
            base = self._pages_path / validate_dir_path(
                folder_path, self._pages_path
            )

        candidates: list[FilenameRename] = []
        if base.is_dir():
            for md in sorted(base.rglob("*.md")):
                if self._ignore_matcher.should_ignore(md):
                    continue
                rename = self._normalize_filename(md)
                if rename is not None:
                    candidates.append(rename)

        reasoning = (
            f"날짜 표기 정규화 대상 {len(candidates)}건"
            if candidates
            else "정규화 대상 없음"
        )
        return FilenameNormalization(
            candidates=tuple(candidates), reasoning=reasoning
        )

    def _normalize_filename(self, md: Path) -> FilenameRename | None:
        """단일 파일의 선두 날짜를 표준화한 rename 제안(없으면 None)."""
        name = md.stem  # 확장자 제외
        std, matched = self._standardize_date_prefix(name)
        if std is None or std == name:
            return None

        rel_dir = str(md.parent.relative_to(self._pages_path)).replace("\\", "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        current = f"{rel_dir}/{md.name}" if rel_dir else md.name
        suggested = f"{rel_dir}/{std}.md" if rel_dir else f"{std}.md"
        return FilenameRename(
            current=current,
            suggested=suggested,
            reason=f"날짜 표기 '{matched}' → 표준 YYYY-MM-DD",
        )

    @classmethod
    def _standardize_date_prefix(
        cls, name: str
    ) -> tuple[str | None, str]:
        """파일명 선두 날짜를 ``YYYY-MM-DD`` 로 치환.

        Returns:
            ``(정규화된 이름 또는 None, 매칭된 원본 날짜 문자열)``.
            날짜를 못 찾으면 ``(None, "")``.
        """
        for pat in cls._DATE_PATTERNS:
            m = pat.match(name)
            if not m:
                continue
            gd = m.groupdict()
            if "digits" in gd and gd.get("digits"):
                digits = gd["digits"]
                if len(digits) == 6:  # YYMMDD
                    y, mo, d = f"20{digits[:2]}", digits[2:4], digits[4:6]
                else:  # YYYYMMDD
                    y, mo, d = digits[:4], digits[4:6], digits[6:8]
            elif "yy" in gd and gd.get("yy"):
                y, mo, d = f"20{gd['yy']}", gd["m"], gd["d"]
            else:
                y, mo, d = gd["y"], gd["m"], gd["d"]

            # 유효성: 월 1-12, 일 1-31. 벗어나면 날짜 아님으로 간주.
            try:
                im, idd = int(mo), int(d)
            except ValueError:
                return None, ""
            if not (1 <= im <= 12 and 1 <= idd <= 31):
                return None, ""

            std_date = f"{y}-{im:02d}-{idd:02d}"
            matched = m.group(0)
            rest = name[m.end():].lstrip(" ._-")
            new_name = f"{std_date} {rest}".rstrip() if rest else std_date
            if new_name == name:
                return None, ""
            return new_name, matched
        return None, ""

    def _load_content(self, normalized_path: str) -> str:
        """분류용 본문 로드.

        파일이 디스크에 있으면 읽고, 없으면 인덱스 존재 여부만 확인한다
        (이동/삭제 직후 인덱스에만 남은 경우 허용). 둘 다 없으면 예외.

        Raises:
            DocumentNotFoundError: 디스크에도 인덱스에도 없음.
        """
        full_path = self._pages_path / normalized_path
        if not full_path.exists():
            indexed = (
                self._vector.find_by_path(normalized_path)
                if self._vector.exists()
                else None
            )
            if not indexed:
                raise DocumentNotFoundError.of(normalized_path)
            return ""
        try:
            return full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"Failed to read {full_path}: {e}")
            return ""

    def _get_similar_docs(self, normalized_path: str, top_k: int) -> list:
        """유사 문서 조회(실패 시 빈 리스트). 카테고리 투표/유사경로에 공유."""
        try:
            return self._document_service.get_similar(normalized_path, top_k=top_k)
        except Exception as e:
            logger.debug(f"get_similar failed: {e}")
            return []

    def invalidate(self) -> None:
        """캐시 무효화. ``wiki_reindex`` 후 호출."""
        self._cached_pending = None
        self._cached_at = 0.0

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _categorize_indexed_doc(
        self, category: str, tags: Any
    ) -> str | None:
        """인덱싱된 문서의 분류 부족 사유 반환. 분류 충분하면 None."""
        if not category or category == "uncategorized":
            # 카테고리 + 태그 둘 다 없으면 frontmatter 자체가 빈약
            if not tags:
                return "no_frontmatter"
            return "no_category"
        return None

    def _scan_disk_files(self) -> list[str]:
        """디스크에서 .md 파일 상대 경로 목록 (무시 패턴 적용)."""
        if not self._pages_path.exists():
            return []
        rel_paths: list[str] = []
        for md in self._pages_path.rglob("*.md"):
            if self._ignore_matcher.should_ignore(md):
                continue
            try:
                rel = md.relative_to(self._pages_path)
            except ValueError:
                continue
            rel_str = str(rel).replace("\\", "/")
            # frontmatter 누락 의심도 같이 잡힘 (인덱스에 없으므로 not_indexed)
            rel_paths.append(rel_str)
        return rel_paths

    def _compute_category_candidates(
        self, normalized_path: str, similar_docs: list
    ) -> tuple[tuple[str, ...], int]:
        """카테고리 후보 계산.

        신호 기반 후보(폴더 + 유사 문서 투표)를 먼저 모으고, 부족하면 활성
        카테고리로 보조 채운다. 보조 후보는 파일별 차별 신호가 아니라 정적
        목록이므로, 신호 후보 개수를 함께 반환해 호출자가 신뢰도를 판단할
        수 있게 한다(과거엔 신호가 0이어도 정적 5개를 그대로 반환해 모든
        파일이 동일 결과로 수렴하는 버그가 있었다).

        Args:
            normalized_path: 정규화된 대상 경로.
            similar_docs: 호출자가 한 번 조회해 공유하는 유사 문서 리스트.
                투표에는 상위 3개만 사용한다(과거 top_k=3 동작 보존).

        Returns:
            ``(후보 튜플(최대 5개), 신호 기반 후보 개수)``.
            신호 개수가 0이면 후보 전체가 정적 보조(차별 신호 없음)다.
        """
        listing = self._category_service.list_categories()
        active_cats = set(listing.categories)

        candidates: list[str] = []

        # 1) 경로 첫 컴포넌트 (신호)
        first_component = normalized_path.split("/", 1)[0]
        if (
            first_component
            and first_component != normalized_path
            and first_component in active_cats
        ):
            candidates.append(first_component)

        # 2) 유사 문서 투표 (신호, 상위 3개)
        votes: Counter[str] = Counter()
        for doc in similar_docs[:3]:
            cat = (getattr(doc, "category", "") or "").strip()
            if cat and cat != "uncategorized":
                votes[cat] += 1
        for name, _ in votes.most_common():
            if name not in candidates:
                candidates.append(name)

        signal_count = len(candidates)

        # 3) 활성 카테고리로 보조 채움 (정적, 신호 아님)
        for cat in listing.categories:
            if len(candidates) >= 5:
                break
            if cat not in candidates:
                candidates.append(cat)

        return tuple(candidates[:5]), signal_count

    def _compute_tag_candidates(self, content: str, tagger: AutoTagger) -> tuple[str, ...]:
        """본문에서 태그 후보 추출 (기술 용어 우선)."""
        if not content:
            return ()

        technical = tagger.extract_technical_terms(content, top_n=5)
        general = tagger.extract_tags(content, top_n=5)

        merged: list[str] = []
        seen: set[str] = set()
        for term in [*technical, *general]:
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(term)
            if len(merged) >= 8:
                break
        return tuple(merged)

    def _build_reasoning(
        self,
        category_candidates: tuple[str, ...],
        tag_candidates: tuple[str, ...],
        similar_paths: tuple[str, ...],
        category_signal_count: int = 0,
    ) -> str:
        """추천 근거 문자열 구성.

        Args:
            category_signal_count: 신호 기반 카테고리 후보 개수. 0이면 후보가
                전부 정적 보조라 신뢰할 수 없음을 근거에 명시한다.
        """
        parts: list[str] = []
        if category_candidates:
            if category_signal_count > 0:
                parts.append(f"카테고리 후보: {', '.join(category_candidates)}")
            else:
                # 폴더/유사 문서 신호가 없어 활성 카테고리 목록만 제시한 상태.
                parts.append(
                    "카테고리 후보(신호 없음, 활성 목록): "
                    f"{', '.join(category_candidates)}"
                )
        if tag_candidates:
            parts.append(f"태그 후보: {', '.join(tag_candidates[:5])}")
        if similar_paths:
            parts.append(f"유사 문서 {len(similar_paths)}건 참조")
        if not parts:
            return "추천 근거 부족 (인덱스가 비어있거나 본문 없음)"
        return " | ".join(parts)

    def _is_cache_valid(self) -> bool:
        if self._cached_pending is None:
            return False
        return (self._clock() - self._cached_at) < LISTING_TTL_SECONDS
