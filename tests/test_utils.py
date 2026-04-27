"""공통 유틸리티 함수 테스트."""

from pathlib import Path

import pytest

from wiki_search_mcp.core.utils import (
    normalize_document_path,
    parse_frontmatter,
    path_matches,
    resolve_pages_path,
    tokenize,
)


class TestTokenize:
    """tokenize 함수 테스트."""

    def test_korean_tokens(self):
        """한글 토큰화."""
        result = tokenize("Nginx 설정 방법")
        assert "nginx" in result
        assert "설정" in result
        assert "방법" in result

    def test_english_tokens(self):
        """영문 토큰화."""
        result = tokenize("Hello World Test")
        assert "hello" in result
        assert "world" in result
        assert "test" in result

    def test_mixed_tokens(self):
        """한영 혼합 토큰화."""
        result = tokenize("SSL 인증서 설치")
        assert "ssl" in result
        assert "인증서" in result
        assert "설치" in result

    def test_single_char_removed(self):
        """1글자 토큰 제거."""
        result = tokenize("a b c 가 나 다")
        # 1글자는 모두 제거
        assert "a" not in result
        assert "b" not in result
        assert "가" not in result

    def test_lowercase(self):
        """소문자 변환."""
        result = tokenize("NGINX SSL")
        assert "nginx" in result
        assert "ssl" in result

    def test_empty_string(self):
        """빈 문자열."""
        result = tokenize("")
        assert result == []

    def test_numbers(self):
        """숫자 포함."""
        result = tokenize("python3 버전 확인")
        assert "python3" in result
        assert "버전" in result


class TestParseFrontmatter:
    """parse_frontmatter 함수 테스트."""

    def test_valid_frontmatter(self):
        """정상적인 frontmatter 파싱."""
        content = """---
title: Test Document
category: infra
tags:
  - nginx
  - ssl
---
# Hello World

This is content."""

        meta, body = parse_frontmatter(content)

        assert meta["title"] == "Test Document"
        assert meta["category"] == "infra"
        assert "nginx" in meta["tags"]
        assert "ssl" in meta["tags"]
        assert body.startswith("# Hello World")

    def test_no_frontmatter(self):
        """frontmatter 없음."""
        content = "# Just a Markdown file\n\nNo frontmatter here."

        meta, body = parse_frontmatter(content)

        assert meta == {}
        assert body == content

    def test_empty_frontmatter(self):
        """빈 frontmatter."""
        content = """---
---
# Content"""

        meta, body = parse_frontmatter(content)

        assert meta == {}
        assert body == "# Content"

    def test_invalid_yaml(self):
        """잘못된 YAML."""
        content = """---
title: [invalid yaml
---
# Content"""

        meta, body = parse_frontmatter(content)

        # YAML 파싱 실패 시 빈 dict와 원본 반환
        assert meta == {}
        assert body == content

    def test_partial_delimiter(self):
        """부분적인 구분자."""
        content = """---
title: Test
Only one delimiter"""

        meta, body = parse_frontmatter(content)

        # 닫는 --- 없으면 frontmatter로 인식 안 함
        assert meta == {}
        assert body == content


class TestResolvePagesPath:
    """resolve_pages_path 함수 테스트."""

    def test_with_pages_dir(self, tmp_path):
        """pages/ 디렉토리 있는 경우."""
        pages_dir = tmp_path / "pages"
        pages_dir.mkdir()

        result = resolve_pages_path(tmp_path)

        assert result == pages_dir

    def test_without_pages_dir(self, tmp_path):
        """pages/ 디렉토리 없는 경우."""
        result = resolve_pages_path(tmp_path)

        assert result == tmp_path

    def test_pages_as_file(self, tmp_path):
        """pages가 파일인 경우."""
        pages_file = tmp_path / "pages"
        pages_file.write_text("I am a file, not a directory")

        result = resolve_pages_path(tmp_path)

        # 파일이면 디렉토리로 인식 안 함
        assert result == tmp_path

    def test_nested_wiki(self, tmp_path):
        """중첩된 wiki 구조."""
        wiki_path = tmp_path / "my-wiki"
        wiki_path.mkdir()
        pages_dir = wiki_path / "pages"
        pages_dir.mkdir()

        result = resolve_pages_path(wiki_path)

        assert result == pages_dir


class TestNormalizeDocumentPath:
    """normalize_document_path 함수 테스트."""

    def test_normalize_with_md_extension(self):
        """확장자 있는 경로 정규화."""
        with_md, without_md = normalize_document_path("docs/readme.md")

        assert with_md == "docs/readme.md"
        assert without_md == "docs/readme"

    def test_normalize_without_md_extension(self):
        """확장자 없는 경로 정규화."""
        with_md, without_md = normalize_document_path("docs/readme")

        assert with_md == "docs/readme.md"
        assert without_md == "docs/readme"

    def test_normalize_nested_path(self):
        """중첩 경로 정규화."""
        with_md, without_md = normalize_document_path("category/sub/doc.md")

        assert with_md == "category/sub/doc.md"
        assert without_md == "category/sub/doc"

    def test_normalize_root_path(self):
        """루트 경로 정규화."""
        with_md, without_md = normalize_document_path("index")

        assert with_md == "index.md"
        assert without_md == "index"


class TestPathMatches:
    """path_matches 함수 테스트."""

    def test_same_path_with_extension(self):
        """동일 경로 (확장자 있음)."""
        assert path_matches("docs/readme.md", "docs/readme.md") is True

    def test_same_path_without_extension(self):
        """동일 경로 (확장자 없음)."""
        assert path_matches("docs/readme", "docs/readme") is True

    def test_mixed_extension(self):
        """확장자 유무 혼합."""
        assert path_matches("docs/readme.md", "docs/readme") is True
        assert path_matches("docs/readme", "docs/readme.md") is True

    def test_different_paths(self):
        """다른 경로."""
        assert path_matches("docs/readme.md", "docs/other.md") is False
        assert path_matches("docs/readme", "docs/other") is False

    def test_nested_paths(self):
        """중첩 경로."""
        assert path_matches("a/b/c.md", "a/b/c") is True
        assert path_matches("a/b/c.md", "a/b/d.md") is False
