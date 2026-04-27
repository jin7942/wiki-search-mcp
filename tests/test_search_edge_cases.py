"""검색 엣지케이스 테스트.

빈 결과, 특수문자, 유니코드, 단일 소스 등 경계 케이스를 테스트합니다.
"""

import pytest

from wiki_search_mcp.core.validators import (
    validate_query,
    validate_search_mode,
    validate_sort_by,
    validate_sort_order,
    validate_top_k,
)


class TestSearchEdgeCases:
    """검색 엣지케이스 테스트."""

    def test_search_empty_query_raises_error(self):
        """빈 쿼리는 ValueError 발생."""
        with pytest.raises(ValueError, match="Query cannot be empty"):
            validate_query("")

    def test_search_whitespace_only_query_raises_error(self):
        """공백만 있는 쿼리는 ValueError 발생."""
        with pytest.raises(ValueError, match="Query cannot be empty"):
            validate_query("   ")

    def test_search_query_strips_whitespace(self):
        """쿼리의 앞뒤 공백 제거."""
        result = validate_query("  hello world  ")
        assert result == "hello world"

    def test_search_special_characters_in_query(self):
        """특수문자가 포함된 쿼리 처리."""
        # 특수문자는 허용됨 (검색 쿼리이므로)
        result = validate_query("nginx (reverse proxy)")
        assert result == "nginx (reverse proxy)"

    def test_search_unicode_query(self):
        """유니코드 쿼리 처리."""
        # 한글
        result = validate_query("Nginx 설정 가이드")
        assert result == "Nginx 설정 가이드"

        # 일본어
        result = validate_query("ドキュメント検索")
        assert result == "ドキュメント検索"

        # 중국어
        result = validate_query("文档搜索")
        assert result == "文档搜索"

    def test_search_mode_validation(self):
        """검색 모드 검증."""
        assert validate_search_mode("hybrid") == "hybrid"
        assert validate_search_mode("vector") == "vector"
        assert validate_search_mode("keyword") == "keyword"
        # 잘못된 모드는 기본값으로
        assert validate_search_mode("invalid") == "hybrid"
        assert validate_search_mode("") == "hybrid"

    def test_sort_by_validation(self):
        """정렬 기준 검증."""
        assert validate_sort_by("similarity") == "similarity"
        assert validate_sort_by("confidence") == "confidence"
        assert validate_sort_by("updated") == "updated"
        assert validate_sort_by("title") == "title"
        # 잘못된 값은 기본값으로
        assert validate_sort_by("invalid") == "similarity"
        assert validate_sort_by("") == "similarity"

    def test_sort_order_validation(self):
        """정렬 순서 검증."""
        assert validate_sort_order("asc") == "asc"
        assert validate_sort_order("desc") == "desc"
        # 잘못된 값은 기본값으로
        assert validate_sort_order("invalid") == "desc"
        assert validate_sort_order("") == "desc"

    def test_top_k_clamping(self):
        """top_k 범위 클램핑."""
        # 범위 내
        assert validate_top_k(5) == 5
        assert validate_top_k(1) == 1
        assert validate_top_k(100) == 100

        # 범위 벗어남 - 클램핑
        assert validate_top_k(0) == 1
        assert validate_top_k(-1) == 1
        assert validate_top_k(200) == 100

    def test_top_k_custom_range(self):
        """top_k 커스텀 범위."""
        assert validate_top_k(5, min_val=10, max_val=20) == 10
        assert validate_top_k(25, min_val=10, max_val=20) == 20
        assert validate_top_k(15, min_val=10, max_val=20) == 15


class TestHybridSearchEdgeCases:
    """하이브리드 검색 엣지케이스 테스트."""

    def test_rrf_single_source_vector_only(self):
        """벡터 검색 결과만 있는 경우."""
        k = 60
        vector_results = [{"path": "a"}, {"path": "b"}]
        bm25_results = []  # 키워드 결과 없음

        scores = {}
        for rank, r in enumerate(vector_results):
            scores[r["path"]] = scores.get(r["path"], 0) + 0.7 / (rank + k)

        for rank, r in enumerate(bm25_results):
            scores[r["path"]] = scores.get(r["path"], 0) + 0.3 / (rank + k)

        sorted_paths = sorted(scores.keys(), key=lambda p: scores[p], reverse=True)

        # 벡터 결과 순서 유지
        assert sorted_paths == ["a", "b"]

    def test_rrf_single_source_keyword_only(self):
        """키워드 검색 결과만 있는 경우."""
        k = 60
        vector_results = []  # 벡터 결과 없음
        bm25_results = [{"path": "x"}, {"path": "y"}]

        scores = {}
        for rank, r in enumerate(vector_results):
            scores[r["path"]] = scores.get(r["path"], 0) + 0.7 / (rank + k)

        for rank, r in enumerate(bm25_results):
            scores[r["path"]] = scores.get(r["path"], 0) + 0.3 / (rank + k)

        sorted_paths = sorted(scores.keys(), key=lambda p: scores[p], reverse=True)

        # 키워드 결과 순서 유지
        assert sorted_paths == ["x", "y"]

    def test_rrf_empty_results(self):
        """양쪽 모두 결과 없는 경우."""
        k = 60
        vector_results = []
        bm25_results = []

        scores = {}
        for rank, r in enumerate(vector_results):
            scores[r["path"]] = scores.get(r["path"], 0) + 0.7 / (rank + k)

        for rank, r in enumerate(bm25_results):
            scores[r["path"]] = scores.get(r["path"], 0) + 0.3 / (rank + k)

        sorted_paths = sorted(scores.keys(), key=lambda p: scores[p], reverse=True)

        # 빈 결과
        assert sorted_paths == []

    def test_rrf_duplicate_handling(self):
        """중복 문서 처리."""
        k = 60
        # 같은 문서가 양쪽에 있음
        vector_results = [{"path": "a"}, {"path": "b"}]
        bm25_results = [{"path": "a"}, {"path": "c"}]

        scores = {}
        for rank, r in enumerate(vector_results):
            scores[r["path"]] = scores.get(r["path"], 0) + 0.7 / (rank + k)

        for rank, r in enumerate(bm25_results):
            scores[r["path"]] = scores.get(r["path"], 0) + 0.3 / (rank + k)

        # 'a'는 양쪽에 있으므로 점수 합산됨
        assert scores["a"] > scores["b"]
        assert scores["a"] > scores["c"]


class TestTokenizerEdgeCases:
    """토크나이저 엣지케이스 테스트."""

    def test_tokenize_empty_string(self):
        """빈 문자열 토큰화."""
        from wiki_search_mcp.core.utils import tokenize

        result = tokenize("")
        assert result == []

    def test_tokenize_single_char(self):
        """단일 문자는 필터링됨."""
        from wiki_search_mcp.core.utils import tokenize

        result = tokenize("a b c")
        assert result == []  # 1글자 토큰은 제거됨

    def test_tokenize_mixed_language(self):
        """혼합 언어 토큰화."""
        from wiki_search_mcp.core.utils import tokenize

        result = tokenize("Nginx는 좋은 reverse proxy입니다")
        assert "nginx" in result
        assert "좋은" in result
        assert "reverse" in result
        assert "proxy" in result

    def test_tokenize_numbers(self):
        """숫자 포함 토큰화."""
        from wiki_search_mcp.core.utils import tokenize

        result = tokenize("HTTP2 is faster than HTTP1")
        assert "http2" in result
        assert "http1" in result
        assert "faster" in result
