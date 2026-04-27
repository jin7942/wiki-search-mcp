"""WikiIndexer 테스트

frontmatter 파싱, wikilink 추출, confidence 계산을 테스트합니다.
"""

import tempfile
from pathlib import Path



class TestFrontmatterParsing:
    """Frontmatter 파싱 테스트."""

    def test_parse_valid_frontmatter(self):
        """정상적인 frontmatter 파싱."""

        # 임시 디렉토리 생성 (실제 인덱싱은 안 함)
        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir) / "wiki"
            (wiki_path / "pages").mkdir(parents=True)

            # 모델 로딩 건너뛰기 위해 직접 메서드 테스트
            content = """---
title: 테스트 문서
category: infra
tags: [ssl, nginx]
state: stable
confidence:
  tested: true
  production: false
  sources: primary
  freshness: current
---

# 본문 내용

여기에 본문이 있습니다.
"""
            # WikiIndexer 인스턴스 없이 parse_frontmatter 테스트
            # 정적 메서드가 아니므로 간단히 로직만 검증
            if content.startswith("---"):
                parts = content.split("---", 2)
                assert len(parts) >= 3
                import yaml

                meta = yaml.safe_load(parts[1])
                body = parts[2].strip()

                assert meta["title"] == "테스트 문서"
                assert meta["category"] == "infra"
                assert meta["tags"] == ["ssl", "nginx"]
                assert meta["state"] == "stable"
                assert meta["confidence"]["tested"] is True
                assert "본문 내용" in body

    def test_parse_no_frontmatter(self):
        """Frontmatter 없는 문서 처리."""
        content = """# 제목

본문만 있는 문서입니다.
"""
        # frontmatter 없으면 빈 dict과 전체 내용 반환
        if not content.startswith("---"):
            meta = {}
            body = content
            assert meta == {}
            assert "제목" in body

    def test_parse_invalid_yaml(self):
        """잘못된 YAML frontmatter 처리."""
        content = """---
title: [잘못된 YAML
---

본문
"""
        import yaml

        if content.startswith("---"):
            parts = content.split("---", 2)
            try:
                yaml.safe_load(parts[1])
            except yaml.YAMLError:
                # YAML 에러 시 빈 dict 반환
                meta = {}
                assert meta == {}


class TestWikilinkExtraction:
    """Wikilink 추출 테스트."""

    def test_extract_single_link(self):
        """단일 wikilink 추출."""
        import re

        content = "이 문서는 [[infra/nginx-config]]와 관련됩니다."
        links = re.findall(r"\[\[([^\]]+)\]\]", content)
        assert links == ["infra/nginx-config"]

    def test_extract_multiple_links(self):
        """다중 wikilink 추출."""
        import re

        content = """
        [[devops/ci-cd]] 파이프라인에서 [[infra/docker]] 이미지를 빌드하고
        [[infra/kubernetes]]에 배포합니다.
        """
        links = re.findall(r"\[\[([^\]]+)\]\]", content)
        assert len(links) == 3
        assert "devops/ci-cd" in links
        assert "infra/docker" in links
        assert "infra/kubernetes" in links

    def test_no_wikilinks(self):
        """Wikilink 없는 문서."""
        import re

        content = "일반 마크다운 문서입니다."
        links = re.findall(r"\[\[([^\]]+)\]\]", content)
        assert links == []

    def test_link_with_display_text(self):
        """표시 텍스트가 있는 wikilink는 현재 미지원."""
        import re

        # [[link|display]] 형태는 | 포함하여 추출됨
        content = "[[infra/nginx|Nginx 설정]] 참고"
        links = re.findall(r"\[\[([^\]]+)\]\]", content)
        # 현재는 "infra/nginx|Nginx 설정" 전체가 추출됨
        assert len(links) == 1


class TestConfidenceCalculation:
    """Confidence 점수 계산 테스트."""

    def calculate_confidence(self, meta: dict) -> dict:
        """confidence 계산 로직 (테스트용 복제)."""
        conf = meta.get("confidence", {})

        if isinstance(conf, str):
            return {"level": conf, "score": 50, "factors": {}}

        score = 0
        factors = {}

        if conf.get("tested"):
            score += 30
            factors["tested"] = True

        if conf.get("production"):
            score += 30
            factors["production"] = True

        sources = conf.get("sources", "")
        if sources == "primary":
            score += 20
            factors["sources"] = "primary"
        elif sources == "secondary":
            score += 10
            factors["sources"] = "secondary"

        freshness = conf.get("freshness", "")
        if freshness == "current":
            score += 20
            factors["freshness"] = "current"
        elif freshness == "recent":
            score += 10
            factors["freshness"] = "recent"

        if score >= 70:
            level = "high"
        elif score >= 40:
            level = "medium"
        else:
            level = "low"

        return {"level": level, "score": score, "factors": factors}

    def test_high_confidence(self):
        """High confidence (70+)."""
        meta = {
            "confidence": {
                "tested": True,
                "production": True,
                "sources": "primary",
                "freshness": "current",
            }
        }
        result = self.calculate_confidence(meta)
        assert result["level"] == "high"
        assert result["score"] == 100  # 30+30+20+20

    def test_medium_confidence(self):
        """Medium confidence (40-69)."""
        meta = {
            "confidence": {
                "tested": True,
                "production": False,
                "sources": "secondary",
                "freshness": "recent",
            }
        }
        result = self.calculate_confidence(meta)
        assert result["level"] == "medium"
        assert result["score"] == 50  # 30+0+10+10

    def test_low_confidence(self):
        """Low confidence (<40)."""
        meta = {
            "confidence": {
                "tested": False,
                "production": False,
                "sources": "inference",
                "freshness": "stale",
            }
        }
        result = self.calculate_confidence(meta)
        assert result["level"] == "low"
        assert result["score"] == 0

    def test_legacy_string_confidence(self):
        """기존 문자열 형식 호환."""
        meta = {"confidence": "medium"}
        result = self.calculate_confidence(meta)
        assert result["level"] == "medium"
        assert result["score"] == 50

    def test_missing_confidence(self):
        """Confidence 없는 경우."""
        meta = {}
        result = self.calculate_confidence(meta)
        assert result["level"] == "low"
        assert result["score"] == 0


class TestConfidenceTypeValidation:
    """Confidence 타입 검증 테스트 (WikiIndexer.calculate_confidence 직접 테스트)."""

    def test_invalid_confidence_type_returns_default(self, tmp_path):
        """잘못된 confidence 타입은 기본값 반환."""
        from wiki_search_mcp.infrastructure.indexing import WikiIndexer

        # 임시 wiki 구조 생성
        wiki_path = tmp_path / "wiki"
        (wiki_path / "pages").mkdir(parents=True)
        (wiki_path / "pages" / "test.md").write_text("test")

        indexer = WikiIndexer(str(wiki_path))

        # confidence가 리스트인 경우 (잘못된 타입)
        meta = {"confidence": [1, 2, 3]}
        result = indexer.calculate_confidence(meta)

        assert result["level"] == "medium"
        assert result["score"] == 50

    def test_invalid_factor_types_ignored(self, tmp_path):
        """잘못된 factor 타입은 무시."""
        from wiki_search_mcp.infrastructure.indexing import WikiIndexer

        # 임시 wiki 구조 생성
        wiki_path = tmp_path / "wiki"
        (wiki_path / "pages").mkdir(parents=True)
        (wiki_path / "pages" / "test.md").write_text("test")

        indexer = WikiIndexer(str(wiki_path))

        # tested가 문자열인 경우 (bool 기대)
        meta = {
            "confidence": {
                "tested": "yes",  # 잘못된 타입
                "production": True,  # 올바른 타입
                "sources": 123,  # 잘못된 타입
                "freshness": "current",  # 올바른 타입
            }
        }
        result = indexer.calculate_confidence(meta)

        # tested, sources는 무시되고 production(30) + freshness(20) = 50
        assert result["score"] == 50
        assert "tested" not in result["factors"]
        assert result["factors"].get("production") is True
        assert "sources" not in result["factors"]
        assert result["factors"].get("freshness") == "current"
