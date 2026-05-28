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

# [최우선 규칙] 신규 문서는 반드시 ``inbox/``에 작성

이 규칙은 이 서버의 다른 모든 안내보다 우선합니다. 새 .md 파일을 만들 때
**예외 없이** 적용하세요.

## 파일 작성 전 자가 확인 (매번)

```
[ ] 사용자가 경로/카테고리를 명시했는가? (예: "infra/nginx.md에 저장")
      → YES: 그 위치에 작성. (frontmatter category는 사용자 명시 값 우선)
      → NO : 아래로.
[ ] 새 파일을 inbox/<slug>.md 에 작성하는가?
      → YES만 진행. 카테고리 폴더에 직접 쓰려 했다면 멈추고 inbox/로 변경.
```

## 금지 / 강제

- **금지**: 신규 파일을 카테고리 폴더(예: ``infra/``, ``devops/``, ``domain/``)에
  직접 작성. Claude가 작성 시점에 카테고리를 추측해 폴더를 고르는 행위 자체가 금지입니다.
- **강제**: 사용자가 경로를 명시하지 않은 모든 신규 메모는 ``inbox/<slug>.md``
  (또는 ``pages/inbox/<slug>.md``)에 작성. ``inbox/`` 폴더가 없으면 ``mkdir -p`` 로 만드세요.
- 새 파일의 ``category`` 필드는 비워두거나 ``inbox``로 둡니다. 카테고리는
  **daemon이 LLM 분류로 자동 결정**하고 적절한 폴더로 이동시킵니다.

## 왜 inbox 강제인가

- 카테고리는 사용자의 폴더 구조(``infra/`` vs ``devops/`` 경계 등)에 의존합니다.
  Claude가 작성 시점에 추측하면 **사용자 분류 체계와 불일치**가 누적되고,
  한 번 잘못 놓인 파일은 사용자가 직접 찾아 옮기기 전까지 그대로 남습니다.
- daemon은 임베딩 유사도 + 폴더 컨텍스트 + LLM 분류를 종합하므로 더 일관됩니다.
- inbox 한 곳만 보면 미분류 항목을 추적할 수 있습니다(단일 진실 원천).

## 예외 (이때만 카테고리 폴더에 직접 작성)

- 사용자가 경로/카테고리를 **명시**한 경우(예: "infra/nginx.md로 저장해줘"):
  지시대로 작성하되 frontmatter ``category``는 사용자 명시 값을 우선합니다.
- 기존 파일을 **수정**하는 경우: 현재 위치를 그대로 유지합니다(이동 금지).

## inbox는 카테고리가 아니라 staging 영역

``inbox``는 ``wiki_get_categories`` 응답의 ``staging_folders`` 배열에 나오며
``categories``에는 포함되지 않습니다. 분류기는 ``inbox``를 분류 답으로 고르지 않고,
``inbox/``의 파일은 frontmatter에 ``category``가 박혀 있어도 daemon이 다시 분류해
적절한 폴더로 이동시킵니다. ``inbox`` 변형(``Inbox``, ``0.Inbox``, ``_inbox`` 등)도
동일하게 staging으로 식별됩니다.

## 핵심 원칙

- **MCP는 read-only**: 이 서버의 어떤 도구도 파일을 만들거나 수정하지 않습니다.
  파일 쓰기/이동/삭제는 모두 Claude의 일반 도구(Read, Write, Edit, Bash)로 수행하세요.
  (그래서 위 inbox 규칙은 Claude가 스스로 지켜야 합니다 — 서버가 강제하지 못합니다.)
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
