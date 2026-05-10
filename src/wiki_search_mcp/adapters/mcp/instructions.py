"""MCP 서버 instructions.

FastMCP의 ``instructions`` 인자에 주입되어, MCP 클라이언트(예: Claude Desktop)에
서버 사용 가이드를 자동으로 전달합니다. 사용자가 별도 ``CLAUDE.md``를 두지 않아도
zero-config로 분류 워크플로우가 동작합니다.

이 파일을 수정하면 다음 MCP 연결부터 적용됩니다.
"""

WIKI_INSTRUCTIONS: str = """\
# wiki-search MCP

이 서버는 사용자의 로컬 Markdown wiki를 자동 분류·검색하는 zero-config PKM입니다.
설정 파일은 사용하지 않으며, 사용자의 폴더 구조와 .gitignore를 그대로 따릅니다.

## 핵심 원칙

- **MCP는 read-only**: 이 서버의 어떤 도구도 파일을 만들거나 수정하지 않습니다.
  파일 쓰기/이동/삭제는 모두 Claude의 일반 도구(Read, Write, Edit, Bash)로 수행하세요.
- **카테고리 = 폴더**: 사용자가 wiki 루트(또는 pages/) 하위에 만든 디렉토리가 카테고리입니다.
- **임베딩 기반 추천**: 분류 추천은 폴더 구조 + 유사 문서 투표 + 본문 키워드를 종합합니다.

## 첫 사용 / 인덱스 부트스트랩

서버는 기동 시 인덱스가 비어있으면 **백그라운드에서 자동으로 전체 인덱싱**을 시작합니다.
``wiki_stats()`` 응답의 ``bootstrap.state`` 필드로 진행 상태를 확인할 수 있습니다.

- ``in_progress``: 인덱싱 진행 중. 검색/분류 도구는 잠시 후 재시도.
- ``completed`` / ``skipped``: 사용 준비 완료.
- ``failed``: ``bootstrap.error``로 원인 확인. 사용자에게
  ``wiki-search-mcp index <wiki-path> --full`` 수동 실행을 안내하세요.

검색이나 분류 도구가 ``Index not built yet``으로 응답하면 부트스트랩 진행 중입니다.
``wiki_stats()``로 상태 확인 후 사용자에게 안내하세요.

## 시작 시 권장 흐름

세션 초반에 사용자가 "정리할 거 있어?", "메모 정리해줘"와 같은 요청을 하거나
명시적으로 작업을 시작하면 다음 절차를 따르세요.

1. ``wiki_get_categories()`` 호출
   - ``mode == "folder"`` → ``categories``를 사용 가능한 카테고리로 인지
   - ``mode == "empty"`` → 사용자에게 카테고리 제안을 받을지 물어보고
     동의 시 ``wiki_suggest_categories()`` 호출
2. ``wiki_pending(limit=20)`` 호출하여 미분류 파일 확인
   - ``not_indexed``: 신규 파일 (인덱싱 대기)
   - ``no_frontmatter``: frontmatter 자체가 빈약
   - ``no_category``: ``category`` 필드 누락
3. 각 파일에 대해 ``wiki_suggest_classification(path)`` 호출하여 후보 확보
4. 사용자에게 후보를 보고하고 승인받기
5. 승인된 분류대로 Claude의 Read/Write로 frontmatter 수정 및 파일 이동
6. 파일 변경은 watcher가 감지하여 자동 재인덱싱됩니다 (``wiki_reindex`` 직접 호출은 선택)

## Frontmatter 스키마

```
---
title: 문서 제목
category: <wiki_get_categories의 categories 중 하나>
tags: [tag1, tag2]
created: YYYY-MM-DD
updated: YYYY-MM-DD
state: stable | draft | deprecated | archived
confidence:
  tested: true | false
  production: true | false
  sources: primary | secondary | inference
  freshness: current | recent | outdated
---
```

State 권장 진행: ``draft`` → ``stable`` → 필요 시 ``deprecated`` → ``archived``.

## 검색 워크플로우

- ``wiki_search(query)``로 의미 기반 검색
- 결과의 ``path``를 Claude의 Read로 상세 조회
- 답변은 검색 결과를 근거로 작성. 모호하면 ``wiki_get_similar(path)``로 보강.

## Wikilink

관련 문서는 ``[[path/to/doc]]`` 형식으로 연결합니다. 그래프 확장은
``wiki_search``의 ``expand_graph=true``와 ``wiki_get_backlinks(path)``로 활용합니다.

## 민감정보

비밀번호, 토큰, IP 등은 본문에 직접 쓰지 말고 ``.secrets/credentials.md``에
저장한 뒤 ``[[.secrets/credentials#항목명]]``으로 참조하도록 안내하세요.

## 도구 요약

- 검색: ``wiki_search``, ``wiki_get_similar``, ``wiki_get_backlinks``,
  ``wiki_find_orphans``
- 조회: ``wiki_get_document``, ``wiki_list_documents``, ``wiki_stats``
- 분류 보조: ``wiki_get_categories``, ``wiki_suggest_categories``,
  ``wiki_pending``, ``wiki_suggest_classification``, ``wiki_suggest_tags``
- 관리: ``wiki_reindex``, ``wiki_watch_status``, ``wiki_validate``

이 도구들은 모두 read-only입니다. 파일 작성·이동은 Claude가 직접 하세요.
"""
