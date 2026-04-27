"""QueryExpander 테스트

쿼리 확장 (동의어) 기능을 테스트합니다.
"""

from wiki_search_mcp.services.expander_service import QueryExpander


class TestQueryExpander:
    """쿼리 확장 테스트."""

    def test_expand_nginx(self):
        """nginx 동의어 확장."""
        expander = QueryExpander()
        expanded = expander.expand("nginx 설정")

        assert "nginx 설정" in expanded
        # 동의어로 확장된 쿼리도 포함
        assert len(expanded) > 1

    def test_expand_docker(self):
        """docker 동의어 확장."""
        expander = QueryExpander()
        expanded = expander.expand("docker 배포")

        assert "docker 배포" in expanded
        # "도커", "container" 등으로 확장
        has_korean = any("도커" in q for q in expanded)
        has_container = any("container" in q for q in expanded)
        assert has_korean or has_container

    def test_expand_ssl(self):
        """ssl 동의어 확장."""
        expander = QueryExpander()
        expanded = expander.expand("ssl 인증서")

        assert "ssl 인증서" in expanded
        # tls, https 등으로 확장
        has_tls = any("tls" in q for q in expanded)
        has_https = any("https" in q for q in expanded)
        assert has_tls or has_https

    def test_no_expansion_unknown_word(self):
        """알 수 없는 단어는 확장 안 함."""
        expander = QueryExpander()
        expanded = expander.expand("unknownword123")

        # 원본만 반환
        assert expanded == ["unknownword123"]

    def test_get_synonyms(self):
        """동의어 조회."""
        expander = QueryExpander()

        nginx_synonyms = expander.get_synonyms("nginx")
        assert len(nginx_synonyms) > 0
        assert "웹서버" in nginx_synonyms or "엔진엑스" in nginx_synonyms

        unknown_synonyms = expander.get_synonyms("unknownword")
        assert unknown_synonyms == []

    def test_custom_synonyms(self):
        """사용자 정의 동의어."""
        custom = {
            "myterm": ["synonym1", "synonym2"],
        }
        expander = QueryExpander(custom_synonyms=custom)

        expanded = expander.expand("myterm test")

        assert "myterm test" in expanded
        has_synonym1 = any("synonym1" in q for q in expanded)
        has_synonym2 = any("synonym2" in q for q in expanded)
        assert has_synonym1 or has_synonym2

    def test_merge_custom_with_default(self):
        """사용자 정의와 기본 동의어 병합."""
        custom = {
            "nginx": ["custom_nginx_synonym"],
        }
        expander = QueryExpander(custom_synonyms=custom)

        synonyms = expander.get_synonyms("nginx")

        # 기본 동의어도 유지
        assert "웹서버" in synonyms or "엔진엑스" in synonyms
        # 사용자 정의 동의어도 포함
        assert "custom_nginx_synonym" in synonyms

    def test_case_insensitive(self):
        """대소문자 구분 없이 확장."""
        expander = QueryExpander()

        # 대문자로 입력해도 확장됨
        expanded = expander.expand("NGINX config")

        # 원본 쿼리는 그대로 포함
        assert "NGINX config" in expanded

    def test_no_duplicates(self):
        """중복 쿼리 제거."""
        expander = QueryExpander()
        expanded = expander.expand("nginx nginx")

        # 중복 쿼리가 없어야 함
        assert len(expanded) == len(set(expanded))


class TestDefaultSynonyms:
    """기본 동의어 사전 테스트."""

    def test_has_common_terms(self):
        """주요 기술 용어 포함 확인."""
        expander = QueryExpander()

        assert "nginx" in expander.synonyms
        assert "docker" in expander.synonyms
        assert "ssl" in expander.synonyms
        assert "k8s" in expander.synonyms
        assert "mysql" in expander.synonyms

    def test_bidirectional_kubernetes(self):
        """kubernetes <-> k8s 양방향."""
        expander = QueryExpander()

        k8s_synonyms = expander.get_synonyms("k8s")
        kubernetes_synonyms = expander.get_synonyms("kubernetes")

        assert "kubernetes" in k8s_synonyms
        assert "k8s" in kubernetes_synonyms

    def test_korean_english_mapping(self):
        """한글-영어 매핑."""
        expander = QueryExpander()

        docker_synonyms = expander.get_synonyms("docker")
        assert "도커" in docker_synonyms

        nginx_synonyms = expander.get_synonyms("nginx")
        assert "엔진엑스" in nginx_synonyms


class TestQueryExpanderValidation:
    """쿼리 확장 검증 테스트."""

    def test_expand_empty_query_raises_error(self):
        """빈 쿼리는 ValueError 발생."""
        import pytest

        expander = QueryExpander()

        with pytest.raises(ValueError, match="empty"):
            expander.expand("")

    def test_expand_whitespace_query_raises_error(self):
        """공백만 있는 쿼리는 ValueError 발생."""
        import pytest

        expander = QueryExpander()

        with pytest.raises(ValueError, match="empty"):
            expander.expand("   ")

    def test_expand_limits_results(self):
        """확장 결과 수 제한."""
        from wiki_search_mcp.services.expander_service import MAX_EXPANDED_QUERIES

        # 많은 동의어가 있는 단어 조합
        custom = {
            "test": [f"syn{i}" for i in range(20)],  # 20개 동의어
        }
        expander = QueryExpander(custom_synonyms=custom)

        expanded = expander.expand("test query")

        # 최대 제한 이하
        assert len(expanded) <= MAX_EXPANDED_QUERIES
