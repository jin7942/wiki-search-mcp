from __future__ import annotations

"""Query Expander - 쿼리 확장 (동의어)

동의어 사전을 기반으로 검색 쿼리를 확장합니다.
"""


# 쿼리 확장 최대 개수 (무한 확장 방지)
MAX_EXPANDED_QUERIES = 10


class QueryExpander:
    """검색 쿼리를 동의어로 확장하는 클래스.

    사용자 쿼리에 포함된 단어를 동의어로 확장하여
    검색 범위를 넓힙니다.

    Attributes:
        synonyms: 동의어 사전 (키: 정규화된 단어, 값: 동의어 리스트)
    """

    # 기본 동의어 사전 (IT 인프라 중심)
    DEFAULT_SYNONYMS: dict[str, list[str]] = {
        # 웹 서버
        "nginx": ["엔진엑스", "reverse proxy", "웹서버", "리버스프록시"],
        "apache": ["아파치", "httpd", "웹서버"],
        # 컨테이너
        "docker": ["도커", "container", "컨테이너"],
        "k8s": ["kubernetes", "쿠버네티스", "쿠베"],
        "kubernetes": ["k8s", "쿠버네티스", "쿠베"],
        # 보안
        "ssl": ["tls", "https", "인증서", "certificate"],
        "tls": ["ssl", "https", "인증서", "certificate"],
        "https": ["ssl", "tls", "인증서"],
        # 데이터베이스
        "db": ["database", "데이터베이스"],
        "database": ["db", "데이터베이스"],
        "mysql": ["mariadb", "마이에스큐엘"],
        "mariadb": ["mysql", "마리아디비"],
        "postgresql": ["postgres", "포스트그레스"],
        "postgres": ["postgresql", "포스트그레스"],
        "mongodb": ["몽고디비", "mongo"],
        "redis": ["레디스", "캐시"],
        # CI/CD
        "ci": ["continuous integration", "지속적통합"],
        "cd": ["continuous deployment", "지속적배포"],
        "cicd": ["ci/cd", "파이프라인", "pipeline"],
        "jenkins": ["젠킨스"],
        "gitlab": ["깃랩"],
        "github": ["깃허브"],
        # 인프라
        "aws": ["아마존", "클라우드"],
        "gcp": ["google cloud", "구글클라우드"],
        "azure": ["애저", "마이크로소프트클라우드"],
        "vm": ["virtual machine", "가상머신"],
        "vpc": ["virtual private cloud", "가상사설클라우드"],
        "lb": ["load balancer", "로드밸런서"],
        "loadbalancer": ["lb", "로드밸런서"],
        # 모니터링
        "monitoring": ["모니터링", "감시"],
        "prometheus": ["프로메테우스"],
        "grafana": ["그라파나"],
        # 네트워크
        "dns": ["domain name system", "도메인"],
        "ip": ["internet protocol", "아이피"],
        "firewall": ["방화벽", "iptables"],
        # 일반
        "server": ["서버"],
        "config": ["configuration", "설정"],
        "setting": ["설정", "config"],
        "error": ["에러", "오류"],
        "deploy": ["배포", "deployment"],
        "backup": ["백업"],
        "log": ["로그", "logging"],
    }

    def __init__(self, custom_synonyms: dict[str, list[str]] | None = None):
        """QueryExpander 초기화.

        Args:
            custom_synonyms: 사용자 정의 동의어 사전 (기본 사전에 병합)
        """
        self.synonyms = dict(self.DEFAULT_SYNONYMS)
        if custom_synonyms:
            for key, values in custom_synonyms.items():
                if key in self.synonyms:
                    # 기존 동의어에 추가
                    self.synonyms[key] = list(set(self.synonyms[key] + values))
                else:
                    self.synonyms[key] = values

    def expand(self, query: str) -> list[str]:
        """쿼리를 동의어로 확장.

        Args:
            query: 원본 검색 쿼리

        Returns:
            확장된 쿼리 리스트 (원본 포함)

        Raises:
            ValueError: 빈 쿼리가 전달된 경우
        """
        # 빈 쿼리 검증
        if not query or not query.strip():
            raise ValueError("Query cannot be empty or whitespace only")

        words = query.lower().split()
        expanded_queries = [query]

        for word in words:
            if word in self.synonyms:
                for synonym in self.synonyms[word]:
                    # 확장 제한 도달 시 조기 반환
                    if len(expanded_queries) >= MAX_EXPANDED_QUERIES:
                        return expanded_queries

                    # 원본 쿼리에서 해당 단어를 동의어로 교체
                    new_query = query.lower().replace(word, synonym)
                    if new_query not in expanded_queries:
                        expanded_queries.append(new_query)

        return expanded_queries

    def get_synonyms(self, word: str) -> list[str]:
        """특정 단어의 동의어 목록 반환.

        Args:
            word: 조회할 단어

        Returns:
            동의어 리스트 (없으면 빈 리스트)
        """
        return self.synonyms.get(word.lower(), [])
