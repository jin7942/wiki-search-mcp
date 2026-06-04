"""Document service.

문서 CRUD 유스케이스를 담당합니다.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from wiki_search_mcp.core.config import DEFAULT_PREVIEW_SIZE
from wiki_search_mcp.core.exceptions import DocumentNotFoundError, InvalidPathError
from wiki_search_mcp.core.models import Document
from wiki_search_mcp.core.path_validator import validate_path
from wiki_search_mcp.core.utils import parse_frontmatter
from wiki_search_mcp.services.filters import apply_simple_filters

if TYPE_CHECKING:
    from wiki_search_mcp.core.protocols import VectorRepository


class DocumentService:
    """문서 CRUD 유스케이스 담당."""

    def __init__(self, vector_repository: "VectorRepository", pages_path: Path):
        """DocumentService 초기화.

        Args:
            vector_repository: 벡터 저장소
            pages_path: 문서 파일 경로
        """
        self._store = vector_repository
        self._pages_path = pages_path

    def get_document(
        self,
        path: str,
        include_content: bool = False,
        preview_size: int = DEFAULT_PREVIEW_SIZE,
    ) -> Document | None:
        """특정 문서 조회.

        Args:
            path: 문서 상대 경로
            include_content: 전체 본문 포함 여부
            preview_size: 미리보기 크기 (문자 수)

        Returns:
            Document 객체 또는 None

        Raises:
            InvalidPathError: 경로 탐색 공격 시도
        """
        self._validate_path(path)

        if not self._store.exists():
            return None

        doc_data = self._store.find_by_path(path)
        if not doc_data:
            return None

        doc = Document.from_dict(doc_data)

        # 본문 처리가 필요하면 추가 정보 반환
        if include_content or preview_size > 0:
            return self._with_content(doc, include_content, preview_size)

        return doc

    def _with_content(
        self,
        doc: Document,
        include_content: bool,
        preview_size: int,
    ) -> Document:
        """본문 정보 추가 (현재는 Document 그대로 반환).

        설계 의도:
            Document는 @dataclass(frozen=True)로 정의되어 불변 객체입니다.
            본문 내용을 Document에 직접 추가하면 모델이 비대해지고,
            파일 시스템 의존성이 도메인 모델에 침투합니다.

            따라서 본문 조회는 별도 메서드(read_content)로 분리했습니다.
            이 메서드는 확장 포인트로 남겨두었으며, 추후 Document를
            DTO로 래핑하거나 캐싱 레이어를 추가할 때 활용할 수 있습니다.

        Args:
            doc: 원본 Document 객체
            include_content: 전체 본문 포함 여부 (현재 미사용)
            preview_size: 미리보기 크기 (현재 미사용)

        Returns:
            Document 객체 (현재는 입력 그대로 반환)
        """
        return doc

    def read_content(
        self,
        path: str,
        include_full: bool = False,
        preview_size: int = DEFAULT_PREVIEW_SIZE,
    ) -> dict[str, Any]:
        """문서 본문 조회.

        Args:
            path: 문서 경로
            include_full: 전체 본문 여부
            preview_size: 미리보기 크기

        Returns:
            {
                "content" or "content_preview": str,
                "content_size": int (미리보기일 때),
                "warning": str (파일 없을 때)
            }
        """
        self._validate_path(path)

        file_path = self._pages_path / path
        if not file_path.exists():
            return {"warning": "Source file not found"}

        content = file_path.read_text(encoding="utf-8")
        _, body = parse_frontmatter(content)

        if include_full:
            return {"content": body}

        if len(body) <= preview_size:
            return {"content_preview": body, "content_size": len(body)}

        # 미리보기 (문장 경계에서 자르기)
        preview = body[:preview_size]
        cut_points = [preview.rfind(c) for c in ".!?。"]
        cut_point = max(cut_points)

        if cut_point > preview_size * 0.5:
            preview = preview[: cut_point + 1]
        else:
            preview = preview + "..."

        return {"content_preview": preview, "content_size": len(body)}

    def list_documents(
        self,
        category: str | None = None,
        tag: str | None = None,
        state: str | None = None,
        limit: int = 50,
    ) -> list[Document]:
        """조건에 맞는 문서 목록 조회.

        Args:
            category: 카테고리 필터
            tag: 태그 필터
            state: 상태 필터
            limit: 최대 결과 수

        Returns:
            Document 리스트
        """
        if not self._store.exists():
            return []

        all_docs = self._store.to_arrow_list()

        # 필터 적용 (filters.py 사용)
        filtered_docs = apply_simple_filters(all_docs, category, tag, state)

        # limit 적용 및 Document 변환
        return [Document.from_dict(doc_data) for doc_data in filtered_docs[:limit]]

    def suggest_tags(self, path: str, top_n: int = 5) -> dict[str, Any]:
        """문서 본문 기반 태그 제안.

        adapter(handler)가 AutoTagger 를 직접 인스턴스화하던 것을 service 로
        옮긴 것이다(계층 경계 정리). 문서 조회 → 본문 읽기 → 태그 추출까지
        한 유스케이스로 캡슐화한다.

        Args:
            path: 대상 문서 경로(검증/정규화 전).
            top_n: 추출할 태그 수.

        Returns:
            ``{"path", "suggested_tags", "existing_tags"}`` dict.

        Raises:
            DocumentNotFoundError: 문서가 없거나 본문이 비어 있는 경우.
            InvalidPathError: 경로 검증 실패.
        """
        from wiki_search_mcp.services.tagger_service import AutoTagger

        validated_path = self._validate_path(path)

        doc = self.get_document(path=validated_path, include_content=True)
        if doc is None:
            raise DocumentNotFoundError.of(path)

        content_info = self.read_content(path=validated_path, include_full=True)
        content = content_info.get("content", "")
        if not content:
            raise DocumentNotFoundError.of(f"{path} (no content)")

        tagger = AutoTagger()
        suggested_tags = tagger.extract_tags(content, top_n)

        return {
            "path": validated_path,
            "suggested_tags": suggested_tags,
            "existing_tags": list(doc.tags),
        }

    def get_similar(self, path: str, top_k: int = 5) -> list[Document]:
        """특정 문서와 유사한 문서 목록.

        Args:
            path: 대상 문서 경로
            top_k: 반환할 유사 문서 수

        Returns:
            유사 Document 리스트
        """
        self._validate_path(path)

        if not self._store.exists():
            return []

        # 대상 문서의 벡터 조회
        target_vec = self._store.get_vector_by_path(path)
        if not target_vec:
            return []

        # 유사 문서 검색 (자기 자신 포함해서 top_k+1개)
        similar = self._store.search(target_vec, top_k + 1)

        # 자기 자신 제외
        results = []
        for r in similar:
            if r["path"] == path:
                continue

            doc = Document.from_dict(r)
            results.append(doc)

            if len(results) >= top_k:
                break

        return results

    def _validate_path(self, path: str) -> str:
        """경로 유효성 검사.

        Args:
            path: 검증할 경로

        Returns:
            검증된 경로 (.md 확장자 정규화됨)

        Raises:
            InvalidPathError: 경로 탐색 공격 시도
        """
        return validate_path(path, self._pages_path)
