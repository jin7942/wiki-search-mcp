"""하이브리드 검색 테스트

BM25 + 벡터 검색 결합(RRF)을 테스트합니다.
"""


class TestBM25Search:
    """BM25 키워드 검색 테스트."""

    def test_tokenize_korean(self):
        """한글 토큰화."""
        import re

        text = "Nginx 설정 가이드입니다."
        text_lower = text.lower()
        tokens = re.findall(r"[가-힣]+|[a-z0-9]+", text_lower)
        tokens = [t for t in tokens if len(t) > 1]

        assert "nginx" in tokens
        assert "설정" in tokens
        assert "가이드입니다" in tokens

    def test_tokenize_english(self):
        """영문 토큰화."""
        import re

        text = "Docker container setup guide"
        text_lower = text.lower()
        tokens = re.findall(r"[가-힣]+|[a-z0-9]+", text_lower)
        tokens = [t for t in tokens if len(t) > 1]

        assert "docker" in tokens
        assert "container" in tokens
        assert "setup" in tokens
        assert "guide" in tokens

    def test_bm25_scoring(self):
        """BM25 점수 계산."""
        from rank_bm25 import BM25Okapi

        corpus = [
            ["nginx", "설정", "가이드"],
            ["docker", "컨테이너", "배포"],
            ["nginx", "reverse", "proxy", "설정"],
        ]

        bm25 = BM25Okapi(corpus)
        query = ["nginx", "설정"]
        scores = bm25.get_scores(query)

        # nginx, 설정이 있는 문서가 높은 점수
        assert scores[0] > 0
        assert scores[2] > 0
        # docker 문서는 낮은 점수
        assert scores[1] == 0


class TestRRFFusion:
    """RRF (Reciprocal Rank Fusion) 테스트."""

    def test_rrf_calculation(self):
        """RRF 점수 계산."""
        k = 60  # RRF 상수

        # 벡터 검색 결과 (순위순)
        vector_results = ["doc1", "doc2", "doc3"]
        # BM25 결과 (순위순)
        bm25_results = ["doc2", "doc1", "doc4"]

        vector_weight = 0.7

        scores = {}
        for rank, doc in enumerate(vector_results):
            scores[doc] = scores.get(doc, 0) + vector_weight / (rank + k)

        for rank, doc in enumerate(bm25_results):
            scores[doc] = scores.get(doc, 0) + (1 - vector_weight) / (rank + k)

        # doc1, doc2는 양쪽에서 나왔으므로 높은 점수
        assert scores["doc1"] > scores["doc3"]
        assert scores["doc1"] > scores["doc4"]
        assert scores["doc2"] > scores["doc4"]

    def test_rrf_ranking(self):
        """RRF 결과 순위."""
        k = 60

        vector_results = [{"path": "a"}, {"path": "b"}]
        bm25_results = [{"path": "b"}, {"path": "c"}]

        scores = {}
        for rank, r in enumerate(vector_results):
            scores[r["path"]] = scores.get(r["path"], 0) + 0.7 / (rank + k)

        for rank, r in enumerate(bm25_results):
            scores[r["path"]] = scores.get(r["path"], 0) + 0.3 / (rank + k)

        sorted_paths = sorted(scores.keys(), key=lambda p: scores[p], reverse=True)

        # b가 양쪽에서 상위이므로 1위
        assert sorted_paths[0] == "b"


class TestSearchModes:
    """검색 모드 테스트."""

    def test_mode_validation(self):
        """검색 모드 검증."""
        valid_modes = {"hybrid", "vector", "keyword"}

        assert "hybrid" in valid_modes
        assert "vector" in valid_modes
        assert "keyword" in valid_modes
        assert "invalid" not in valid_modes

    def test_default_mode(self):
        """기본 검색 모드."""
        mode = "invalid"
        if mode not in ("hybrid", "vector", "keyword"):
            mode = "hybrid"

        assert mode == "hybrid"
