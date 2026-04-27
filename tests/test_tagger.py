"""AutoTagger 테스트

자동 태그 추출 기능을 테스트합니다.
"""

from wiki_search_mcp.services.tagger_service import AutoTagger


class TestAutoTagger:
    """자동 태그 추출 테스트."""

    def test_extract_korean_tags(self):
        """한글 태그 추출."""
        tagger = AutoTagger()
        content = """
        # Nginx 설정 가이드

        이 문서는 웹서버 설정에 대한 가이드입니다.
        Nginx는 리버스 프록시로 많이 사용됩니다.
        웹서버 설정 시 SSL 인증서도 필요합니다.
        """

        tags = tagger.extract_tags(content, top_n=5)

        # "설정"이 여러 번 등장하므로 상위에 있어야 함
        assert len(tags) > 0
        # 불용어("이", "는", "에" 등)는 제외되어야 함
        assert "이" not in tags
        assert "는" not in tags

    def test_extract_english_tags(self):
        """영문 태그 추출."""
        tagger = AutoTagger()
        content = """
        # Docker Container Setup

        Docker is a containerization platform.
        This guide explains Docker container deployment.
        Container orchestration with Kubernetes is also covered.
        """

        tags = tagger.extract_tags(content, top_n=5)

        assert len(tags) > 0
        # 불용어("the", "a", "is" 등)는 제외되어야 함
        assert "the" not in tags
        assert "is" not in tags
        assert "a" not in tags

    def test_stopwords_removed(self):
        """불용어 제거 확인."""
        tagger = AutoTagger()

        # 한글 불용어
        assert "이" in tagger.stopwords
        assert "가" in tagger.stopwords
        assert "을" in tagger.stopwords

        # 영어 불용어
        assert "the" in tagger.stopwords
        assert "is" in tagger.stopwords
        assert "and" in tagger.stopwords

    def test_custom_stopwords(self):
        """사용자 정의 불용어."""
        extra = {"customword", "anotherword"}
        tagger = AutoTagger(extra_stopwords=extra)

        assert "customword" in tagger.stopwords
        assert "anotherword" in tagger.stopwords

    def test_top_n_limit(self):
        """상위 N개 제한."""
        tagger = AutoTagger()
        content = "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10"

        tags = tagger.extract_tags(content, top_n=3)

        assert len(tags) <= 3

    def test_technical_terms_extraction(self):
        """기술 용어 추출."""
        tagger = AutoTagger()
        content = """
        Use `nginx` for reverse proxy.
        The `docker` container runs on port 8080.

        ```bash
        docker run nginx
        ```
        """

        terms = tagger.extract_technical_terms(content, top_n=5)

        # 백틱으로 감싼 용어가 추출되어야 함
        assert "nginx" in terms or "docker" in terms

    def test_empty_content(self):
        """빈 내용 처리."""
        tagger = AutoTagger()
        tags = tagger.extract_tags("", top_n=5)

        assert tags == []

    def test_short_words_filtered(self):
        """짧은 단어 필터링."""
        tagger = AutoTagger()
        content = "a b c ab cd ef abcd efgh"

        tags = tagger.extract_tags(content, top_n=10)

        # 1글자 단어는 제외
        assert "a" not in tags
        assert "b" not in tags
        assert "c" not in tags
