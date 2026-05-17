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


def test_instructions_clarifies_inbox_not_a_category():
    """v0.2.5: inbox는 카테고리가 아니라 staging 영역이라는 점이 명시되어야 한다.

    이전에는 instructions에 "inbox에 작성"만 있고 "inbox는 카테고리 아님"이
    빠져 있어서 Claude가 inbox를 일반 카테고리로 오해할 수 있었다.
    """
    text = WIKI_INSTRUCTIONS
    assert "staging" in text or "staging_folders" in text
    assert "카테고리가 아니" in text or "not a category" in text.lower()


def test_instructions_mandates_inbox_for_new_notes():
    """새 메모는 반드시 inbox/에 작성하도록 명시되어야 한다.

    v0.2.0 사용자 보고: Claude가 새 메모를 카테고리 폴더(예: ``infra/``)에
    직접 작성하면서 daemon 자동 분류 경로(``inbox`` → LLM 분류 → 이동)를
    우회하는 문제 발생. instructions에 강제 규칙이 명시되어야 한다.
    """
    text = WIKI_INSTRUCTIONS
    assert "inbox" in text
    # "반드시" 같은 강제 표현 또는 명시적 영문 강제어 중 하나는 포함되어야 함
    assert any(kw in text for kw in ("반드시", "언제나", "MUST", "must"))
