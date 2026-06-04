"""MCP Handlers 단위 테스트

handlers.py의 핸들러 함수들을 직접 테스트합니다.
"""

import json
from unittest.mock import MagicMock

import pytest

from wiki_search_mcp.adapters.mcp.handlers import (
    handle_wiki_find_orphans,
    handle_wiki_get_backlinks,
    handle_wiki_get_categories,
    handle_wiki_get_document,
    handle_wiki_get_similar,
    handle_wiki_list_documents,
    handle_wiki_pending,
    handle_wiki_reindex,
    handle_wiki_search,
    handle_wiki_stats,
    handle_wiki_suggest_categories,
    handle_wiki_suggest_classification,
    handle_wiki_suggest_tags,
    handle_wiki_validate,
    handle_wiki_watch_status,
)
from wiki_search_mcp.core.exceptions import (
    BusinessException,
    InvalidPathError,
    TechnicalException,
)


def _create_mock_container():
    """테스트용 mock ServiceContainer 생성."""
    mock_container = MagicMock()

    # 검색 결과 mock
    mock_search_response = MagicMock()
    mock_search_response.to_dict.return_value = {
        "results": [],
        "total_pages": 10,
        "query": "test",
        "mode": "hybrid",
    }
    mock_container.search_service.search.return_value = mock_search_response

    # 통계 mock
    mock_stats = MagicMock()
    mock_stats.to_dict.return_value = {
        "total_pages": 50,
        "by_category": {"infra": 10},
        "by_state": {"stable": 40},
        "by_confidence": {"high": 20},
        "last_indexed": "2024-01-01T10:00:00",
    }
    mock_container.stats_service.get_stats.return_value = mock_stats

    # 검증 결과 mock
    mock_validation = MagicMock()
    mock_validation.to_dict.return_value = {
        "status": "valid",
        "total": 10,
        "issues": [],
        "stats": {},
        "summary": {},
    }
    mock_container.validation_service.validate.return_value = mock_validation

    return mock_container


class TestHandleWikiSearch:
    """handle_wiki_search 테스트."""

    def test_empty_query_returns_error(self):
        """빈 쿼리 시 에러 반환."""
        container = _create_mock_container()
        result = handle_wiki_search(container, query="")
        data = json.loads(result)

        assert "error" in data
        assert "empty" in data["error"].lower()

    def test_whitespace_query_returns_error(self):
        """공백만 있는 쿼리 시 에러 반환."""
        container = _create_mock_container()
        result = handle_wiki_search(container, query="   ")
        data = json.loads(result)

        assert "error" in data

    def test_successful_search(self):
        """정상 검색."""
        container = _create_mock_container()
        result = handle_wiki_search(container, query="nginx", top_k=5)
        data = json.loads(result)

        assert "results" in data
        assert data["total_pages"] == 10
        container.search_service.search.assert_called_once()

    def test_top_k_clamped(self):
        """top_k 범위 제한."""
        container = _create_mock_container()

        # 0 -> 1
        handle_wiki_search(container, query="test", top_k=0)
        call_args = container.search_service.search.call_args
        assert call_args.kwargs["top_k"] == 1

        # 200 -> 100
        handle_wiki_search(container, query="test", top_k=200)
        call_args = container.search_service.search.call_args
        assert call_args.kwargs["top_k"] == 100

    def test_mode_normalized(self):
        """잘못된 mode는 hybrid로 정규화."""
        container = _create_mock_container()
        handle_wiki_search(container, query="test", mode="invalid")
        call_args = container.search_service.search.call_args
        assert call_args.kwargs["mode"] == "hybrid"


class TestHandleWikiGetDocument:
    """handle_wiki_get_document 테스트."""

    def test_empty_path_returns_error(self):
        """빈 경로 시 에러 반환."""
        container = _create_mock_container()
        result = handle_wiki_get_document(container, path="")
        data = json.loads(result)

        assert "error" in data
        assert "empty" in data["error"].lower()

    def test_document_not_found(self):
        """문서 없을 때 에러 반환."""
        container = _create_mock_container()
        container.document_service.get_document.return_value = None

        result = handle_wiki_get_document(container, path="nonexistent.md")
        data = json.loads(result)

        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_path_traversal_blocked(self):
        """path traversal 차단."""
        container = _create_mock_container()
        container.document_service.get_document.side_effect = InvalidPathError.of("../etc/passwd")

        result = handle_wiki_get_document(container, path="../etc/passwd")
        data = json.loads(result)

        assert "error" in data

    def test_preview_size_clamped(self):
        """preview_size 범위 제한."""
        container = _create_mock_container()
        mock_doc = MagicMock()
        mock_doc.to_dict.return_value = {"path": "test.md"}
        container.document_service.get_document.return_value = mock_doc
        container.document_service.read_content.return_value = {}

        # 3000 -> 2000
        handle_wiki_get_document(container, path="test.md", preview_size=3000)
        call_args = container.document_service.read_content.call_args
        assert call_args.kwargs["preview_size"] == 2000


class TestHandleWikiListDocuments:
    """handle_wiki_list_documents 테스트."""

    def test_list_returns_documents(self):
        """문서 목록 반환."""
        container = _create_mock_container()
        mock_docs = [
            MagicMock(path="a.md", title="A", category="infra", state="stable", tags=("nginx",)),
            MagicMock(path="b.md", title="B", category="devops", state="draft", tags=()),
        ]
        container.document_service.list_documents.return_value = mock_docs

        result = handle_wiki_list_documents(container)
        data = json.loads(result)

        assert data["count"] == 2
        assert len(data["documents"]) == 2
        assert data["documents"][0]["path"] == "a.md"

    def test_limit_clamped(self):
        """limit 범위 제한."""
        container = _create_mock_container()
        container.document_service.list_documents.return_value = []

        # 1000 -> 500
        handle_wiki_list_documents(container, limit=1000)
        call_args = container.document_service.list_documents.call_args
        assert call_args.kwargs["limit"] == 500

        # 0 -> 1
        handle_wiki_list_documents(container, limit=0)
        call_args = container.document_service.list_documents.call_args
        assert call_args.kwargs["limit"] == 1


class TestHandleWikiGetSimilar:
    """handle_wiki_get_similar 테스트."""

    def test_empty_path_returns_error(self):
        """빈 경로 시 에러 반환."""
        container = _create_mock_container()
        result = handle_wiki_get_similar(container, path="")
        data = json.loads(result)

        assert "error" in data

    def test_similar_documents_returned(self):
        """유사 문서 반환."""
        container = _create_mock_container()
        mock_docs = [
            MagicMock(path="similar1.md", title="Similar 1", category="infra"),
        ]
        container.document_service.get_similar.return_value = mock_docs

        result = handle_wiki_get_similar(container, path="source.md", top_k=5)
        data = json.loads(result)

        assert data["source"] == "source.md"
        assert data["count"] == 1
        assert len(data["similar"]) == 1

    def test_top_k_clamped(self):
        """top_k 범위 제한 (1-20)."""
        container = _create_mock_container()
        container.document_service.get_similar.return_value = []

        # 30 -> 20
        handle_wiki_get_similar(container, path="test.md", top_k=30)
        call_args = container.document_service.get_similar.call_args
        assert call_args.kwargs["top_k"] == 20


class TestHandleWikiGetBacklinks:
    """handle_wiki_get_backlinks 테스트."""

    def test_empty_path_returns_error(self):
        """빈 경로 시 에러 반환."""
        container = _create_mock_container()
        result = handle_wiki_get_backlinks(container, path="")
        data = json.loads(result)

        assert "error" in data

    def test_backlinks_returned(self):
        """역링크 반환."""
        container = _create_mock_container()
        mock_docs = [
            MagicMock(path="link1.md", title="Link 1", category="infra"),
            MagicMock(path="link2.md", title="Link 2", category="devops"),
        ]
        container.graph_service.get_backlinks.return_value = mock_docs

        result = handle_wiki_get_backlinks(container, path="target.md")
        data = json.loads(result)

        assert data["target"] == "target.md"
        assert data["count"] == 2


class TestHandleWikiFindOrphans:
    """handle_wiki_find_orphans 테스트."""

    def test_orphans_returned(self):
        """고아 문서 반환."""
        container = _create_mock_container()
        mock_docs = [
            MagicMock(path="orphan1.md", title="Orphan 1", category="misc"),
        ]
        container.graph_service.find_orphans.return_value = mock_docs

        result = handle_wiki_find_orphans(container)
        data = json.loads(result)

        assert data["count"] == 1
        assert len(data["orphans"]) == 1


class TestHandleWikiValidate:
    """handle_wiki_validate 테스트."""

    def test_validation_returns_report(self):
        """검증 리포트 반환."""
        container = _create_mock_container()
        result = handle_wiki_validate(container)
        data = json.loads(result)

        assert data["status"] == "valid"
        assert data["total"] == 10


class TestHandleWikiStats:
    """handle_wiki_stats 테스트."""

    def test_stats_returned(self):
        """통계 반환."""
        container = _create_mock_container()
        result = handle_wiki_stats(container)
        data = json.loads(result)

        assert data["total_pages"] == 50
        assert "by_category" in data
        assert "by_state" in data
        # bootstrap_state 미전달 시 응답에 bootstrap 필드 없음
        assert "bootstrap" not in data

    def test_stats_includes_bootstrap_state(self):
        """bootstrap_state 전달 시 응답에 포함."""
        container = _create_mock_container()
        result = handle_wiki_stats(
            container, bootstrap_state=("in_progress", None)
        )
        data = json.loads(result)

        assert data["bootstrap"]["state"] == "in_progress"
        assert "error" not in data["bootstrap"]

    def test_stats_includes_bootstrap_error(self):
        """bootstrap이 failed 상태면 error도 함께 노출."""
        container = _create_mock_container()
        result = handle_wiki_stats(
            container, bootstrap_state=("failed", "disk full")
        )
        data = json.loads(result)

        assert data["bootstrap"]["state"] == "failed"
        assert data["bootstrap"]["error"] == "disk full"


class TestHandleWikiReindex:
    """handle_wiki_reindex 테스트."""

    def test_reindex_returns_result(self):
        """인덱싱 결과 반환."""
        container = _create_mock_container()
        mock_indexer = MagicMock()
        mock_indexer.reindex.return_value = {
            "indexed": 10,
            "updated": 2,
            "duration_ms": 500,
        }

        result = handle_wiki_reindex(container, mock_indexer, full=False)
        data = json.loads(result)

        assert data["indexed"] == 10
        assert data["updated"] == 2
        container.invalidate_all.assert_called_once()

    def test_reindex_error_handling(self):
        """인덱싱 에러 처리.

        Note: 예상치 못한 예외(Exception)는 보안상 "Internal error"로 반환됩니다.
        """
        container = _create_mock_container()
        mock_indexer = MagicMock()
        mock_indexer.reindex.side_effect = Exception("Index error")

        result = handle_wiki_reindex(container, mock_indexer, full=True)
        data = json.loads(result)

        assert "error" in data
        # 예상치 못한 예외는 "Internal error"로 반환
        assert data["error"] == "Internal error"


class TestHandleWikiWatchStatus:
    """handle_wiki_watch_status 테스트."""

    def test_status_when_watcher_none(self):
        """watcher가 None일 때 상태."""
        result = handle_wiki_watch_status(
            watcher=None,
            enabled=False,
            debounce_seconds=2.0,
            watching_path="/wiki/pages",
        )
        data = json.loads(result)

        assert data["enabled"] is False
        assert data["running"] is False
        assert data["watching_path"] == "/wiki/pages"

    def test_status_when_watcher_running(self):
        """watcher 실행 중 상태."""
        mock_watcher = MagicMock()
        mock_watcher.get_status.return_value = {
            "enabled": True,
            "running": True,
            "watching_path": "/wiki/pages",
            "debounce_seconds": 2.0,
        }

        result = handle_wiki_watch_status(
            watcher=mock_watcher,
            enabled=True,
            debounce_seconds=2.0,
            watching_path="/wiki/pages",
        )
        data = json.loads(result)

        assert data["enabled"] is True
        assert data["running"] is True


class TestHandleWikiSuggestTags:
    """handle_wiki_suggest_tags 테스트."""

    def test_empty_path_returns_error(self):
        """빈 경로 시 에러 반환."""
        container = _create_mock_container()
        result = handle_wiki_suggest_tags(container, path="")
        data = json.loads(result)

        assert "error" in data

    def test_document_not_found(self):
        """문서 없을 때 에러 반환 (service 가 DocumentNotFoundError raise)."""
        from wiki_search_mcp.core.exceptions import DocumentNotFoundError

        container = _create_mock_container()
        container.document_service.suggest_tags.side_effect = (
            DocumentNotFoundError.of("nonexistent.md")
        )

        result = handle_wiki_suggest_tags(container, path="nonexistent.md")
        data = json.loads(result)

        assert "error" in data
        assert "not found" in data["error"].lower()

    def test_delegates_to_service_with_clamped_top_n(self):
        """handler 는 검증 후 service.suggest_tags 에 위임한다."""
        container = _create_mock_container()
        container.document_service.suggest_tags.return_value = {
            "path": "test.md",
            "suggested_tags": ["nginx", "ssl"],
            "existing_tags": ["existing"],
        }

        result = handle_wiki_suggest_tags(container, path="test.md", top_n=15)
        data = json.loads(result)

        assert data["suggested_tags"] == ["nginx", "ssl"]
        # top_n 은 10 으로 clamp 되어 service 에 전달돼야 함
        _, kwargs = container.document_service.suggest_tags.call_args
        assert kwargs["top_n"] == 10


class TestHandleWikiGetCategories:
    """handle_wiki_get_categories 테스트."""

    def test_returns_listing_dict(self):
        container = _create_mock_container()
        listing = MagicMock()
        listing.to_dict.return_value = {
            "mode": "folder",
            "categories": ["Notes", "Projects"],
            "detected_at": "2026-04-27T00:00:00",
        }
        container.category_service.list_categories.return_value = listing

        result = handle_wiki_get_categories(container)
        data = json.loads(result)

        assert data["mode"] == "folder"
        assert data["categories"] == ["Notes", "Projects"]

    def test_handles_business_exception(self):
        container = _create_mock_container()
        container.category_service.list_categories.side_effect = BusinessException(
            "boom"
        )

        result = handle_wiki_get_categories(container)
        data = json.loads(result)
        assert "error" in data


class TestHandleWikiSuggestCategories:
    """handle_wiki_suggest_categories 테스트."""

    def test_returns_suggestions(self):
        container = _create_mock_container()
        container.category_service.suggest_categories.return_value = [
            {"name": "infra", "doc_count": 3, "keywords": ["nginx"]},
        ]

        result = handle_wiki_suggest_categories(container, top_k=5)
        data = json.loads(result)

        assert "suggestions" in data
        assert data["suggestions"][0]["name"] == "infra"

    def test_top_k_clamped_to_min(self):
        """top_k=0은 1로 클램핑되어 정상 응답."""
        container = _create_mock_container()
        container.category_service.suggest_categories.return_value = []
        result = handle_wiki_suggest_categories(container, top_k=0)
        data = json.loads(result)
        assert "suggestions" in data
        container.category_service.suggest_categories.assert_called_with(top_k=1)


class TestHandleWikiPending:
    """handle_wiki_pending 테스트."""

    def test_returns_items(self):
        container = _create_mock_container()
        item = MagicMock()
        item.to_dict.return_value = {
            "path": "Notes/x.md",
            "reason": "no_category",
            "mtime": "2026-04-27T00:00:00",
        }
        container.classification_service.find_pending.return_value = [item]

        result = handle_wiki_pending(container, limit=5)
        data = json.loads(result)

        assert data["count"] == 1
        assert data["items"][0]["path"] == "Notes/x.md"

    def test_limit_clamped_to_min(self):
        """limit=0은 1로 클램핑되어 정상 응답."""
        container = _create_mock_container()
        container.classification_service.find_pending.return_value = []
        result = handle_wiki_pending(container, limit=0)
        data = json.loads(result)
        # 에러 아닌 정상 응답 (0은 1로 클램핑)
        assert "items" in data
        # find_pending이 limit=1로 호출되었어야 함
        container.classification_service.find_pending.assert_called_with(limit=1)

    def test_empty_pending(self):
        container = _create_mock_container()
        container.classification_service.find_pending.return_value = []

        result = handle_wiki_pending(container)
        data = json.loads(result)
        assert data["count"] == 0
        assert data["items"] == []


class TestHandleWikiSuggestClassification:
    """handle_wiki_suggest_classification 테스트."""

    def test_empty_path_returns_error(self):
        container = _create_mock_container()
        result = handle_wiki_suggest_classification(container, path="")
        data = json.loads(result)
        assert "error" in data

    def test_returns_suggestion(self):
        container = _create_mock_container()
        suggestion = MagicMock()
        suggestion.to_dict.return_value = {
            "path": "Notes/memo.md",
            "category_candidates": ["Notes"],
            "tag_candidates": ["nginx"],
            "similar_paths": [],
            "reasoning": "...",
        }
        container.classification_service.suggest_classification.return_value = (
            suggestion
        )

        result = handle_wiki_suggest_classification(container, path="Notes/memo.md")
        data = json.loads(result)

        assert data["path"] == "Notes/memo.md"
        assert "category_candidates" in data

    def test_invalid_path_returns_error(self):
        container = _create_mock_container()
        container.classification_service.suggest_classification.side_effect = (
            InvalidPathError.of("../etc/passwd")
        )

        result = handle_wiki_suggest_classification(container, path="../etc/passwd")
        data = json.loads(result)
        assert "error" in data


class TestExceptionHandling:
    """예외 처리 세분화 테스트."""

    def test_business_exception_logged_as_warning(self):
        """BusinessException은 warning 레벨로 로깅."""
        container = _create_mock_container()
        container.search_service.search.side_effect = BusinessException("Business error")

        result = handle_wiki_search(container, query="test")
        data = json.loads(result)

        assert "error" in data
        assert data["error"] == "Business error"

    def test_technical_exception_logged_as_error(self):
        """TechnicalException은 error 레벨로 로깅."""
        container = _create_mock_container()
        container.search_service.search.side_effect = TechnicalException("Technical error")

        result = handle_wiki_search(container, query="test")
        data = json.loads(result)

        assert "error" in data
        assert data["error"] == "Technical error"

    def test_unexpected_exception_returns_internal_error(self):
        """예상치 못한 예외는 'Internal error' 반환."""
        container = _create_mock_container()
        container.search_service.search.side_effect = RuntimeError("Unexpected")

        result = handle_wiki_search(container, query="test")
        data = json.loads(result)

        assert "error" in data
        assert data["error"] == "Internal error"

    def test_reindex_exception_still_returns_original_message(self):
        """reindex의 예상치 못한 예외도 Internal error 반환."""
        container = _create_mock_container()
        mock_indexer = MagicMock()
        mock_indexer.reindex.side_effect = RuntimeError("Unexpected reindex error")

        result = handle_wiki_reindex(container, mock_indexer, full=True)
        data = json.loads(result)

        assert "error" in data


class TestMcpHandlerDecorator:
    """mcp_handler 데코레이터 예외→JSON 변환 5단계 검증 (동작 보존)."""

    def _run(self, exc):
        """search 핸들러에서 주어진 예외를 던지고 응답 dict 반환."""
        container = _create_mock_container()
        container.search_service.search.side_effect = exc
        result = handle_wiki_search(container, query="x")
        return json.loads(result)

    def test_business_exception_returns_message(self):
        data = self._run(BusinessException("biz problem"))
        assert "biz problem" in data["error"]

    def test_technical_exception_returns_message(self):
        data = self._run(TechnicalException("tech problem"))
        assert "tech problem" in data["error"]

    def test_invalid_path_returns_message(self):
        # InvalidPathError 는 TechnicalException 하위지만 메시지를 그대로 노출
        data = self._run(InvalidPathError.of("../etc/passwd"))
        assert "error" in data

    def test_value_error_returns_message(self):
        data = self._run(ValueError("bad value"))
        assert "bad value" in data["error"]

    def test_type_error_returns_message(self):
        data = self._run(TypeError("bad type"))
        assert "bad type" in data["error"]

    def test_os_error_returns_generic_fs_message(self):
        data = self._run(OSError("disk gone"))
        # OSError 는 내부 경로 노출 방지 위해 고정 문구
        assert data["error"] == "File system error"

    def test_unexpected_exception_returns_internal_error(self):
        data = self._run(RuntimeError("boom"))
        assert data["error"] == "Internal error"

    def test_success_passthrough_unaffected(self):
        """정상 경로는 데코레이터에 영향받지 않고 결과 반환."""
        container = _create_mock_container()
        result = handle_wiki_search(container, query="nginx")
        data = json.loads(result)
        assert "error" not in data
