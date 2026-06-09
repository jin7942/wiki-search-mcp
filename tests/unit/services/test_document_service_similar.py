"""DocumentService.get_similar 본문 임베딩 fallback 테스트.

인덱스에 없는(신규/이동 직후) 파일도 디스크 본문을 즉석 임베딩해 유사
문서를 찾는지 검증한다. 분류 추천의 닭-달걀(인덱스 벡터 의존) 해소.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiki_search_mcp.services.document_service import DocumentService


def _make_service(
    pages_path: Path,
    *,
    path_vector: list[float] | None = None,
    embedder=None,
    search_results: list[dict] | None = None,
) -> DocumentService:
    store = MagicMock()
    store.exists.return_value = True
    store.get_vector_by_path.return_value = path_vector
    store.search.return_value = search_results or []
    return DocumentService(
        vector_repository=store,
        pages_path=pages_path,
        embedder=embedder,
    )


def test_uses_index_vector_when_available(tmp_path: Path):
    """인덱스 벡터가 있으면 본문 임베딩 없이 그대로 검색."""
    embedder = MagicMock()
    svc = _make_service(
        tmp_path,
        path_vector=[0.1, 0.2],
        embedder=embedder,
        search_results=[{"path": "other.md", "category": "infra", "title": "O"}],
    )

    results = svc.get_similar("target.md", top_k=5)

    assert [d.path for d in results] == ["other.md"]
    embedder.encode.assert_not_called()  # 인덱스 벡터로 충분
    svc._store.search.assert_called_once_with([0.1, 0.2], 6)


def test_embeds_disk_content_when_not_indexed(tmp_path: Path):
    """인덱스에 없는 파일은 디스크 본문을 즉석 임베딩해 검색."""
    (tmp_path / "new.md").write_text(
        "---\ntitle: New\n---\n\nKT IT Park 데이터센터 랙 레이아웃 설계",
        encoding="utf-8",
    )
    embedder = MagicMock()
    embedder.encode.return_value = [0.9, 0.8]

    svc = _make_service(
        tmp_path,
        path_vector=None,  # 인덱스에 없음
        embedder=embedder,
        search_results=[{"path": "kt/a.md", "category": "projects", "title": "A"}],
    )

    results = svc.get_similar("new.md", top_k=5)

    # 본문(frontmatter 제외)을 임베딩했어야 함
    embedder.encode.assert_called_once()
    encoded_text = embedder.encode.call_args[0][0]
    assert "데이터센터" in encoded_text
    assert "title: New" not in encoded_text  # frontmatter 제거됨
    # 그 벡터로 검색
    svc._store.search.assert_called_once_with([0.9, 0.8], 6)
    assert [d.path for d in results] == ["kt/a.md"]


def test_returns_empty_without_embedder_when_not_indexed(tmp_path: Path):
    """embedder 미주입 + 인덱스에 없으면 빈 리스트(기존 동작 보존)."""
    (tmp_path / "new.md").write_text("body", encoding="utf-8")
    svc = _make_service(tmp_path, path_vector=None, embedder=None)

    results = svc.get_similar("new.md", top_k=5)

    assert results == []
    svc._store.search.assert_not_called()


def test_returns_empty_when_file_missing_on_disk(tmp_path: Path):
    """인덱스에도 디스크에도 없으면 빈 리스트(임베딩 시도 안 함)."""
    embedder = MagicMock()
    svc = _make_service(tmp_path, path_vector=None, embedder=embedder)

    results = svc.get_similar("ghost.md", top_k=5)

    assert results == []
    embedder.encode.assert_not_called()


def test_empty_body_not_embedded(tmp_path: Path):
    """본문이 비어 있으면(frontmatter만) 임베딩하지 않고 빈 리스트."""
    (tmp_path / "empty.md").write_text("---\ntitle: E\n---\n\n   ", encoding="utf-8")
    embedder = MagicMock()
    svc = _make_service(tmp_path, path_vector=None, embedder=embedder)

    results = svc.get_similar("empty.md", top_k=5)

    assert results == []
    embedder.encode.assert_not_called()


def test_excludes_self_from_results(tmp_path: Path):
    """자기 자신은 결과에서 제외."""
    svc = _make_service(
        tmp_path,
        path_vector=[0.1],
        search_results=[
            {"path": "target.md", "category": "x", "title": "self"},
            {"path": "other.md", "category": "y", "title": "O"},
        ],
    )

    results = svc.get_similar("target.md", top_k=5)

    assert [d.path for d in results] == ["other.md"]


def test_returns_empty_when_store_absent(tmp_path: Path):
    """인덱스 테이블 자체가 없으면 빈 리스트."""
    store = MagicMock()
    store.exists.return_value = False
    embedder = MagicMock()
    svc = DocumentService(store, tmp_path, embedder=embedder)

    assert svc.get_similar("anything.md") == []
    embedder.encode.assert_not_called()
