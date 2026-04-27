"""MCP instructions 단위 테스트.

WIKI_INSTRUCTIONS가 핵심 워크플로우 키워드를 포함하는지 검증.
"""

from __future__ import annotations

from wiki_search_mcp.adapters.mcp.instructions import WIKI_INSTRUCTIONS


def test_instructions_not_empty():
    assert WIKI_INSTRUCTIONS
    assert len(WIKI_INSTRUCTIONS) > 100


def test_instructions_mentions_new_tools():
    """새로 추가한 4개 도구 이름이 instructions에 포함."""
    assert "wiki_pending" in WIKI_INSTRUCTIONS
    assert "wiki_suggest_classification" in WIKI_INSTRUCTIONS
    assert "wiki_get_categories" in WIKI_INSTRUCTIONS
    assert "wiki_suggest_categories" in WIKI_INSTRUCTIONS


def test_instructions_mentions_read_only_principle():
    """MCP가 read-only임을 명시."""
    assert "read-only" in WIKI_INSTRUCTIONS.lower()


def test_instructions_mentions_frontmatter_schema():
    """frontmatter 스키마 안내 포함."""
    assert "frontmatter" in WIKI_INSTRUCTIONS.lower()
    assert "category" in WIKI_INSTRUCTIONS
    assert "tags" in WIKI_INSTRUCTIONS


def test_instructions_mentions_wikilink():
    """wikilink 사용법 안내 포함."""
    assert "[[" in WIKI_INSTRUCTIONS or "wikilink" in WIKI_INSTRUCTIONS.lower()


def test_instructions_mentions_secrets():
    """민감정보 처리 안내 포함."""
    assert ".secrets" in WIKI_INSTRUCTIONS or "민감" in WIKI_INSTRUCTIONS


def test_fastmcp_accepts_instructions():
    """FastMCP가 instructions 인자 지원 확인 (사전 검증)."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test", instructions=WIKI_INSTRUCTIONS)
    assert server is not None
