from __future__ import annotations

"""Auto Tagger - 자동 태그 추출

문서 내용을 분석하여 적합한 태그를 자동으로 추출합니다.
"""

import re
from collections import Counter


class AutoTagger:
    """문서에서 태그를 자동 추출하는 클래스.

    단어 빈도를 기반으로 문서의 핵심 키워드를 추출합니다.
    """

    # 한글 불용어
    KOREAN_STOPWORDS = {
        "이", "가", "은", "는", "을", "를", "의", "에", "에서", "로", "으로",
        "와", "과", "도", "만", "까지", "부터", "처럼", "같이", "보다",
        "하다", "되다", "있다", "없다", "않다", "이다", "아니다",
        "그", "저", "이것", "그것", "저것", "여기", "거기", "저기",
        "무엇", "누구", "어디", "언제", "왜", "어떻게",
        "그리고", "하지만", "그러나", "또는", "혹은", "및", "등",
        "때", "후", "전", "중", "위", "아래", "사이",
        "것", "수", "때문", "경우", "위해", "통해", "대해",
        "매우", "아주", "정말", "너무", "조금", "약간",
        "다시", "또", "더", "덜", "잘", "못",
    }

    # 영어 불용어
    # Note: file, code, run, set, get, make, new 등 기술 용어는 제외
    # 이들은 기술 문서에서 유의미한 키워드가 될 수 있음
    ENGLISH_STOPWORDS = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "must", "shall", "can",
        "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us",
        "my", "your", "his", "its", "our", "their",
        "this", "that", "these", "those", "what", "which", "who", "whom",
        "where", "when", "why", "how",
        "and", "or", "but", "if", "then", "else", "because", "so", "as",
        "in", "on", "at", "to", "for", "of", "with", "by", "from", "up",
        "about", "into", "through", "during", "before", "after", "above",
        "below", "between", "under", "again", "further", "once",
        "here", "there", "all", "each", "few", "more", "most", "other",
        "some", "such", "no", "nor", "not", "only", "own", "same", "than",
        "too", "very", "just", "also", "now", "even", "still", "already",
        "use", "used", "using", "example", "see", "like", "way", "need",
        "want", "know",
    }

    def __init__(self, extra_stopwords: set[str] | None = None):
        """AutoTagger 초기화.

        Args:
            extra_stopwords: 추가 불용어 세트
        """
        self.stopwords = self.KOREAN_STOPWORDS | self.ENGLISH_STOPWORDS
        if extra_stopwords:
            self.stopwords |= extra_stopwords

    def extract_tags(self, content: str, top_n: int = 5) -> list[str]:
        """문서에서 태그 추출.

        Args:
            content: 문서 본문
            top_n: 추출할 태그 수

        Returns:
            태그 리스트 (빈도순)
        """
        # 단어 추출 (한글 2글자 이상, 영문 2글자 이상)
        korean_words = re.findall(r"[가-힣]{2,}", content)
        english_words = re.findall(r"[a-zA-Z]{2,}", content.lower())

        # 불용어 제거
        words = [
            w for w in korean_words + english_words
            if w.lower() not in self.stopwords and len(w) > 1
        ]

        # 빈도 계산
        counter = Counter(words)

        # 상위 N개 추출
        return [word for word, _ in counter.most_common(top_n)]

    def extract_technical_terms(self, content: str, top_n: int = 5) -> list[str]:
        """기술 용어 추출.

        코드 블록, 백틱 등에서 기술 용어를 우선 추출합니다.

        Args:
            content: 문서 본문
            top_n: 추출할 태그 수

        Returns:
            기술 용어 리스트
        """
        # 백틱으로 감싼 용어 추출
        backtick_terms = re.findall(r"`([^`]+)`", content)

        # 코드 블록 내 용어 (간단 패턴)
        code_blocks = re.findall(r"```[\w]*\n(.*?)```", content, re.DOTALL)
        code_words = []
        for block in code_blocks:
            # 함수/변수명 패턴 추출
            code_words.extend(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", block))

        # 모든 용어 합산
        all_terms = backtick_terms + code_words

        # 불용어 제거 및 빈도 계산
        filtered = [t for t in all_terms if t.lower() not in self.stopwords and len(t) > 2]
        counter = Counter(filtered)

        return [term for term, _ in counter.most_common(top_n)]
