"""MCP Server 도구 테스트

wiki_search, wiki_reindex, wiki_stats, wiki_watch_status 도구를 테스트합니다.
wiki_get_document, wiki_get_backlinks, wiki_list_documents 도구도 테스트합니다.

v0.7.0: ServiceContainer 기반 구조로 마이그레이션됨.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import wiki_search_mcp.adapters.mcp.server as server_module
from wiki_search_mcp.adapters.mcp.server import ServerOptions


@pytest.fixture(autouse=True)
def _ensure_options(tmp_path: Path):
    """모든 server 테스트에 ServerOptions 기본값 주입.

    실제 main()이 호출되지 않으므로 _options이 None인 상태로 인해
    핸들러 진입 시 RuntimeError가 나는 것을 방지합니다.
    """
    original = server_module._options
    server_module._options = ServerOptions(wiki_path=tmp_path)
    try:
        yield
    finally:
        server_module._options = original


def _create_mock_container():
    """테스트용 mock ServiceContainer 생성."""
    mock_container = MagicMock()

    # 검색 결과 mock
    mock_search_response = MagicMock()
    mock_search_response.to_dict.return_value = {
        "results": [],
        "total_pages": 0,
        "query": "test",
        "mode": "hybrid",
    }
    mock_container.search_service.search.return_value = mock_search_response

    # 통계 mock
    mock_stats = MagicMock()
    mock_stats.to_dict.return_value = {
        "total_pages": 50,
        "by_category": {"infra": 10, "devops": 15},
        "by_state": {"stable": 40, "draft": 10},
        "by_confidence": {"high": 20, "medium": 25, "low": 5},
        "last_indexed": "2024-01-01T10:00:00",
    }
    mock_container.stats_service.get_stats.return_value = mock_stats

    return mock_container


class TestWikiSearchTool:
    """wiki_search 도구 테스트."""

    def test_empty_query_returns_error(self):
        """빈 쿼리 시 에러 반환."""
        from wiki_search_mcp.adapters.mcp.server import wiki_search

        result = wiki_search(query="")
        data = json.loads(result)

        assert "error" in data
        assert "empty" in data["error"].lower()

    def test_whitespace_query_returns_error(self):
        """공백만 있는 쿼리 시 에러 반환."""
        from wiki_search_mcp.adapters.mcp.server import wiki_search

        result = wiki_search(query="   \n\t  ")
        data = json.loads(result)

        assert "error" in data

    def test_top_k_clamped_to_valid_range(self):
        """top_k가 유효 범위로 조정됨."""
        mock_container = _create_mock_container()

        with patch.object(server_module, "get_container", return_value=mock_container):
            from wiki_search_mcp.adapters.mcp.server import wiki_search

            # top_k=0 -> 1로 조정되어 검색 실행
            wiki_search(query="test", top_k=0)
            call_args = mock_container.search_service.search.call_args
            assert call_args.kwargs.get("top_k", 5) >= 1

            # top_k=200 -> 100으로 조정
            wiki_search(query="test", top_k=200)
            call_args = mock_container.search_service.search.call_args
            assert call_args.kwargs.get("top_k", 5) <= 100


class TestWikiReindexTool:
    """wiki_reindex 도구 테스트."""

    def test_reindex_returns_result(self):
        """reindex 결과 반환."""
        mock_indexer = MagicMock()
        mock_indexer.reindex.return_value = {
            "indexed": 10,
            "updated": 2,
            "duration_ms": 500,
        }

        mock_container = _create_mock_container()

        with patch.object(server_module, "get_indexer", return_value=mock_indexer):
            with patch.object(server_module, "get_container", return_value=mock_container):
                from wiki_search_mcp.adapters.mcp.server import wiki_reindex

                result = wiki_reindex(full=False)
                data = json.loads(result)

                assert data["indexed"] == 10
                assert data["updated"] == 2
                assert data["duration_ms"] == 500

    def test_reindex_error_handling(self):
        """reindex 에러 처리.

        Note: 예상치 못한 예외(Exception)는 보안상 "Internal error"로 반환됩니다.
              원본 에러 메시지가 노출되지 않습니다.
        """
        mock_indexer = MagicMock()
        mock_indexer.reindex.side_effect = Exception("Index error")

        mock_container = _create_mock_container()

        with patch.object(server_module, "get_indexer", return_value=mock_indexer):
            with patch.object(server_module, "get_container", return_value=mock_container):
                from wiki_search_mcp.adapters.mcp.server import wiki_reindex

                result = wiki_reindex(full=True)
                data = json.loads(result)

                assert "error" in data
                # 예상치 못한 예외는 "Internal error"로 반환
                assert data["error"] == "Internal error"


class TestWikiStatsTool:
    """wiki_stats 도구 테스트."""

    def test_stats_returns_counts(self):
        """통계 결과 반환."""
        mock_container = _create_mock_container()

        with patch.object(server_module, "get_container", return_value=mock_container):
            from wiki_search_mcp.adapters.mcp.server import wiki_stats

            result = wiki_stats()
            data = json.loads(result)

            assert data["total_pages"] == 50
            assert data["by_category"]["infra"] == 10
            assert data["by_state"]["stable"] == 40

    def test_stats_error_handling(self):
        """stats 에러 처리."""
        mock_container = _create_mock_container()
        mock_container.stats_service.get_stats.side_effect = Exception("DB connection failed")

        with patch.object(server_module, "get_container", return_value=mock_container):
            from wiki_search_mcp.adapters.mcp.server import wiki_stats

            result = wiki_stats()
            data = json.loads(result)

            assert "error" in data


class TestWikiWatchStatusTool:
    """wiki_watch_status 도구 테스트."""

    def test_watch_status_when_disabled(self, tmp_path):
        """watcher 비활성화 상태 (_options.watch=False)."""
        from wiki_search_mcp.adapters.mcp.server import ServerOptions

        original_watcher = server_module._watcher
        original_options = server_module._options

        try:
            server_module._watcher = None
            server_module._options = ServerOptions(
                wiki_path=tmp_path,
                watch=False,
            )

            from wiki_search_mcp.adapters.mcp.server import wiki_watch_status

            result = wiki_watch_status()
            data = json.loads(result)

            assert data["enabled"] is False
            assert data["running"] is False
        finally:
            server_module._watcher = original_watcher
            server_module._options = original_options

    def test_watch_status_when_running(self, tmp_path):
        """watcher 실행 중 상태."""
        from wiki_search_mcp.adapters.mcp.server import ServerOptions

        mock_watcher = MagicMock()
        mock_watcher.get_status.return_value = {
            "enabled": True,
            "running": True,
            "watching_path": "/test/wiki/pages",
            "debounce_seconds": 2.0,
        }

        original_watcher = server_module._watcher
        original_options = server_module._options

        try:
            server_module._watcher = mock_watcher
            server_module._options = ServerOptions(
                wiki_path=tmp_path,
                watch=True,
            )

            from wiki_search_mcp.adapters.mcp.server import wiki_watch_status

            result = wiki_watch_status()
            data = json.loads(result)

            assert data["enabled"] is True
            assert data["running"] is True
        finally:
            server_module._watcher = original_watcher
            server_module._options = original_options


class TestWikiGetDocumentTool:
    """wiki_get_document 도구 테스트."""

    def test_empty_path_returns_error(self):
        """빈 경로 시 에러 반환."""
        from wiki_search_mcp.adapters.mcp.server import wiki_get_document

        result = wiki_get_document(path="")
        data = json.loads(result)

        assert "error" in data
        assert "empty" in data["error"].lower()

    def test_document_not_found(self):
        """문서 없을 때 에러 반환."""
        mock_container = _create_mock_container()
        mock_container.document_service.get_document.return_value = None

        with patch.object(server_module, "get_container", return_value=mock_container):
            from wiki_search_mcp.adapters.mcp.server import wiki_get_document

            result = wiki_get_document(path="nonexistent.md")
            data = json.loads(result)

            assert "error" in data
            assert "not found" in data["error"].lower()

    def test_document_found_with_content(self):
        """문서 조회 성공."""
        mock_container = _create_mock_container()

        # Document mock
        mock_doc = MagicMock()
        mock_doc.to_dict.return_value = {
            "path": "infra/nginx.md",
            "title": "Nginx 설정",
            "category": "infra",
            "tags": ["nginx"],
            "summary": "Nginx 설정 가이드",
            "confidence": {"level": "high", "score": 80},
            "state": "stable",
        }
        mock_container.document_service.get_document.return_value = mock_doc
        mock_container.document_service.read_content.return_value = {
            "content": "# Nginx 설정\n\n본문 내용"
        }

        with patch.object(server_module, "get_container", return_value=mock_container):
            from wiki_search_mcp.adapters.mcp.server import wiki_get_document

            result = wiki_get_document(path="infra/nginx.md", include_content=True)
            data = json.loads(result)

            assert data["path"] == "infra/nginx.md"
            assert data["title"] == "Nginx 설정"
            assert "content" in data

    def test_path_traversal_blocked(self):
        """path traversal 공격 차단."""
        mock_container = _create_mock_container()
        from wiki_search_mcp.core.exceptions import InvalidPathError
        mock_container.document_service.get_document.side_effect = InvalidPathError.of("../../../etc/passwd")

        with patch.object(server_module, "get_container", return_value=mock_container):
            from wiki_search_mcp.adapters.mcp.server import wiki_get_document

            result = wiki_get_document(path="../../../etc/passwd")
            data = json.loads(result)

            assert "error" in data


class TestWikiListDocumentsTool:
    """wiki_list_documents 도구 테스트."""

    def test_list_all_documents(self):
        """전체 문서 목록 조회."""
        mock_container = _create_mock_container()

        # Document mock 리스트
        mock_docs = [
            MagicMock(path="a.md", title="A", category="infra", state="stable", tags=()),
            MagicMock(path="b.md", title="B", category="devops", state="draft", tags=()),
        ]
        mock_container.document_service.list_documents.return_value = mock_docs

        with patch.object(server_module, "get_container", return_value=mock_container):
            from wiki_search_mcp.adapters.mcp.server import wiki_list_documents

            result = wiki_list_documents()
            data = json.loads(result)

            assert data["count"] == 2
            assert len(data["documents"]) == 2

    def test_list_with_category_filter(self):
        """카테고리 필터 적용."""
        mock_container = _create_mock_container()

        mock_docs = [
            MagicMock(path="a.md", title="A", category="infra", state="stable", tags=()),
        ]
        mock_container.document_service.list_documents.return_value = mock_docs

        with patch.object(server_module, "get_container", return_value=mock_container):
            from wiki_search_mcp.adapters.mcp.server import wiki_list_documents

            result = wiki_list_documents(category="infra")
            data = json.loads(result)

            assert data["filters"]["category"] == "infra"
            mock_container.document_service.list_documents.assert_called_with(
                category="infra", tag=None, state=None, limit=50
            )

    def test_limit_clamped(self):
        """limit 범위 제한."""
        mock_container = _create_mock_container()
        mock_container.document_service.list_documents.return_value = []

        with patch.object(server_module, "get_container", return_value=mock_container):
            from wiki_search_mcp.adapters.mcp.server import wiki_list_documents

            # limit=1000 -> 500으로 조정
            wiki_list_documents(limit=1000)
            call_args = mock_container.document_service.list_documents.call_args
            assert call_args.kwargs.get("limit", 50) <= 500


class TestWikiGetBacklinksTool:
    """wiki_get_backlinks 도구 테스트."""

    def test_empty_path_returns_error(self):
        """빈 경로 시 에러 반환."""
        from wiki_search_mcp.adapters.mcp.server import wiki_get_backlinks

        result = wiki_get_backlinks(path="")
        data = json.loads(result)

        assert "error" in data

    def test_backlinks_found(self):
        """역링크 조회 성공."""
        mock_container = _create_mock_container()

        mock_docs = [
            MagicMock(path="infra/ssl.md", title="SSL 설정", category="infra"),
            MagicMock(path="devops/deploy.md", title="배포", category="devops"),
        ]
        mock_container.graph_service.get_backlinks.return_value = mock_docs

        with patch.object(server_module, "get_container", return_value=mock_container):
            from wiki_search_mcp.adapters.mcp.server import wiki_get_backlinks

            result = wiki_get_backlinks(path="infra/nginx.md")
            data = json.loads(result)

            assert data["target"] == "infra/nginx.md"
            assert data["count"] == 2
            assert len(data["backlinks"]) == 2

    def test_no_backlinks(self):
        """역링크 없음."""
        mock_container = _create_mock_container()
        mock_container.graph_service.get_backlinks.return_value = []

        with patch.object(server_module, "get_container", return_value=mock_container):
            from wiki_search_mcp.adapters.mcp.server import wiki_get_backlinks

            result = wiki_get_backlinks(path="orphan.md")
            data = json.loads(result)

            assert data["count"] == 0
            assert data["backlinks"] == []


class TestWikiSearchWithFilters:
    """wiki_search 필터 파라미터 테스트."""

    def test_category_filter_passed(self):
        """카테고리 필터 전달."""
        mock_container = _create_mock_container()

        with patch.object(server_module, "get_container", return_value=mock_container):
            from wiki_search_mcp.adapters.mcp.server import wiki_search

            wiki_search(query="nginx", category="infra")
            call_args = mock_container.search_service.search.call_args

            # filters 객체에서 category 확인
            filters = call_args.kwargs.get("filters")
            assert filters.category == "infra"

    def test_tags_filter_passed(self):
        """태그 필터 전달."""
        mock_container = _create_mock_container()

        with patch.object(server_module, "get_container", return_value=mock_container):
            from wiki_search_mcp.adapters.mcp.server import wiki_search

            wiki_search(query="nginx", tags=["nginx", "ssl"])
            call_args = mock_container.search_service.search.call_args

            # filters 객체에서 tags 확인
            filters = call_args.kwargs.get("filters")
            assert "nginx" in filters.tags
            assert "ssl" in filters.tags

    def test_confidence_min_clamped(self):
        """confidence_min 범위 제한."""
        mock_container = _create_mock_container()

        with patch.object(server_module, "get_container", return_value=mock_container):
            from wiki_search_mcp.adapters.mcp.server import wiki_search

            # confidence_min=150 -> 100으로 조정
            wiki_search(query="test", confidence_min=150)
            call_args = mock_container.search_service.search.call_args

            # filters 객체에서 confidence_min 확인
            filters = call_args.kwargs.get("filters")
            assert filters.confidence_min <= 100
