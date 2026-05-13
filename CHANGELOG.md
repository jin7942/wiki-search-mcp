# 변경 이력

이 프로젝트의 모든 주요 변경사항은 이 파일에 기록됩니다.
포맷은 [Keep a Changelog](https://keepachangelog.com/) 기반이며 [Semantic Versioning](https://semver.org/)을 따릅니다.

## [0.2.2] - 2026-05-13

### Fixed

- **CLI 진입 시 torch/sentence_transformers 강제 로딩 제거 (hotfix)**: ``wiki-search-mcp --version``, ``--help``, ``daemon status`` 같은 가벼운 명령이 시작될 때 ``infrastructure/__init__.py``가 ``WikiIndexer``를 즉시 import하면서 ``sentence_transformers → transformers → torch`` 체인 전체를 로드하던 문제. 사용자 환경(Python 3.14 + pipx)에서 진입이 수십 초 걸리거나 Ctrl+C로 중단되는 사례 보고됨.
- 해결: ``infrastructure/__init__.py``를 PEP 562 ``__getattr__`` lazy 패턴으로 변환. ``WikiIndexer`` / ``WikiWatcher`` 호환성은 유지하되 실제 attribute 접근 시점에만 로드. ``--version`` 응답이 ~10초 → **0.1초**.

### Tests

- ``tests/unit/adapters/test_cli_lazy_import.py``: subprocess 격리 검증으로 ``torch`` / ``sentence_transformers`` / ``transformers`` / ``lancedb`` / ``wiki_search_mcp.infrastructure.indexing.indexer`` 가 CLI 진입 시점에 로드되지 않음을 보장.

---

## [0.2.1] - 2026-05-13

### Changed

- **daemon 명령의 `<wiki_path>` 인자를 선택적으로 변경**. 생략 시 ``claude_desktop_config.json``의 ``wiki-search`` 서버 등록 정보에서 wiki 경로를 자동 탐지한다. 사용자가 ``wiki-search-mcp config <path>``로 이미 등록한 경로를 재사용하므로 같은 경로를 두 번 입력할 필요가 없다.

```bash
wiki-search-mcp config ~/my-notes    # 1회 등록
wiki-search-mcp daemon start          # 경로 인자 생략 — config 정보 자동 사용
wiki-search-mcp daemon status
wiki-search-mcp daemon stop
```

명시적으로 경로를 지정하면 (예: 여러 wiki 보유 시) 그쪽이 우선한다.

### Internal

- `daemon_cli._resolve_wiki_path` 헬퍼 추가. 단위 테스트 5개 추가.

---

## [0.2.0] - 2026-05-13

### Added

- **백그라운드 자동 분류 daemon**: `wiki-search-mcp daemon start <wiki>` 한 줄로 새 .md 파일 감지 → Claude Agent SDK로 분류 → frontmatter 자동 작성 + 카테고리 폴더 이동까지 자율 수행. Claude Desktop이 꺼져 있어도 동작.
- **LLM Provider 추상화** (`services/llm/`): Protocol 인터페이스 + `ClaudeCodeProvider` 구현. 사용자 ``claude login`` OAuth를 재활용하므로 **API 키 등록 불필요, 추가 비용 0**. Anthropic API Provider는 v0.3.0 예약.
- **Confidence 임계값 기반 분기**: ``--confidence-threshold`` (기본 0.7) 이상이면 자동 적용, 미달은 ``pending.jsonl``에 적재 → MCP ``wiki_pending``이 우선 노출.
- **Rate limit 보호**: 분/시/일 sliding window (기본 5/100/500). 사용자의 인터랙티브 Claude 사용 한도를 daemon이 잠식하지 않도록.
- **CLI 명령**: ``daemon start / stop / status / logs / rollback``. PID 파일 + ``fcntl flock``으로 단일 인스턴스 보장.
- **Rollback**: ``applied.jsonl``에 적용 전 frontmatter + 원래 경로 저장 → ``daemon rollback --last N``으로 역재생.
- **MCP 신규 도구 `wiki_daemon_status`**: daemon 상태(state/alive/applied_count/pending_count 등) JSON 노출.
- **Atomic frontmatter writer**: tmp → fsync → rename. 사용자 값 우선 머지 (이미 작성된 category/tags는 절대 덮어쓰지 않음).
- **JSON Lines audit log**: ``pending.jsonl`` / ``applied.jsonl`` append-only + 동시 read 안전.

### Changed

- `wiki_pending`: daemon의 ``pending.jsonl`` active 항목을 ClassificationService 결과 앞에 머지. 각 item에 ``source`` 필드 추가 (``"daemon"`` 또는 ``"index"``).
- `wiki_stats`: 응답에 ``daemon`` 서브트리 추가. daemon 미실행 시 ``{"state": "not_running"}``.

### Dependencies

- `claude-agent-sdk>=0.1.81` 추가 (Claude Code CLI는 wheel에 번들).

### Tests

- 단위 테스트 54개 + 격리 환경 통합 테스트 4개 추가. 총 538 passed.
- 격리 환경 (별도 venv + ``XDG_STATE_HOME`` 분리) 에서 daemon 라이프사이클 / 자동 분류 적용 / pending 적재 / rollback / healthcheck 실패 시나리오 모두 검증.

---

## [0.1.1] - 2026-05-10

### Added

- **자동 부트스트랩 인덱싱**: 서버 기동 시 인덱스가 비어있으면 백그라운드에서 자동 full reindex 실행. 사용자가 별도로 CLI 인덱싱 명령을 알아낼 필요 없음.
- `wiki_stats` 응답에 `bootstrap` 필드 추가 — `state` (`not_started` / `in_progress` / `completed` / `failed` / `skipped`), 실패 시 `error` 노출.
- MCP `instructions`에 "첫 사용 / 인덱스 부트스트랩" 섹션 추가 — Claude가 `bootstrap.state`를 보고 사용자에게 진행 상황을 안내하도록 가이드.

### Changed

- 인덱스 미존재 시 에러 메시지 개선: `"Index not found. Run wiki_reindex() first."` → `"Index not built yet. The server is auto-indexing in the background; retry shortly. If this persists, run \`wiki-search-mcp index <wiki-path> --full\` once."` (CLI 명령 명시).

### Fixed

- Pylint cyclic-import (`adapters.cli.main` ↔ `adapters.mcp.server`) 해결: 사용되지 않던 `if __name__ == "__main__"` 블록 제거.
- Pylint 워크플로우 정상화: 패키지 설치 + `src/`만 분석 + `--fail-under=8.0`.

### Internal

- `pyproject.toml`에 `[tool.pylint.*]` 설정 추가 (tests/ 제외, duplicate-code 등 false-positive 비활성화).
- 부트스트랩 동작 검증 테스트 4개 + `wiki_stats` bootstrap 응답 테스트 2개 추가. 480 passed.

---

## [0.1.0] - 2026-04-27

PyPI 첫 공개 릴리즈. **Zero-config 자동 분류 PKM MCP 서버**.

### Highlights

- 설정 파일·환경변수 없이 `pip install` + `wiki-search-mcp config <path>` 두 줄로 동작
- 사용자 폴더 구조가 곧 카테고리 (자동 감지)
- 미분류 파일 감지 + 카테고리/태그 추천 (Claude가 직접 정리)
- 한국어 최적화 임베딩 + BM25 하이브리드 검색
- wikilink `[[link]]` 그래프 RAG
- 모든 처리 로컬 (외부 API 호출 없음)

### MCP 도구 (15개)

**검색/조회**
- `wiki_search` — 하이브리드(벡터+키워드) 검색 + 그래프 확장
- `wiki_get_similar` — 유사 문서 추천
- `wiki_get_backlinks` — 역링크 조회
- `wiki_find_orphans` — 고아 문서 탐색
- `wiki_get_document` — 문서 상세 조회
- `wiki_list_documents` — 카테고리/태그/상태별 목록
- `wiki_stats` — 전체 통계

**자동 분류**
- `wiki_get_categories` — 폴더 자동 감지 카테고리
- `wiki_suggest_categories` — AI 카테고리 후보 제안
- `wiki_pending` — 미분류 / 정리 대기 파일
- `wiki_suggest_classification` — 단일 파일 분류 추천
- `wiki_suggest_tags` — 태그 자동 추출

**관리**
- `wiki_reindex` — 인덱스 재구축
- `wiki_watch_status` — 파일 감시 상태
- `wiki_validate` — frontmatter / wikilink 검증

### 사용

```bash
pipx install wiki-search-mcp
wiki-search-mcp config ~/my-notes
```

옵션 사용 시:

```bash
wiki-search-mcp config ~/my-notes --model fast --no-watch --ignore draft
```

### 아키텍처

Hexagonal/Clean Architecture
- `core/` — 도메인 모델, 프로토콜, 유틸
- `services/` — 유스케이스 (Search, Document, Category, Classification 등)
- `infrastructure/` — LanceDB, BM25, sentence-transformers, watchdog
- `adapters/` — MCP 서버 (FastMCP), CLI

### 설계 결정

- **모든 도구 read-only**: 파일 쓰기는 Claude의 일반 도구(Read/Write/Edit/Bash)가 담당
- **MCP `instructions` 내장**: 사용자가 `CLAUDE.md` 없이도 분류 워크플로우를 활용
- **카테고리 = 폴더**: 사용자가 만든 디렉토리가 그대로 카테고리. 디렉토리 ≥ 2개면 folder mode, 그 외는 AI 제안 폴백
- **무시 패턴 3-tier**: dot-prefix 자동 + `.gitignore` 자동 + `--ignore` 옵션
- **환경변수 0개**: 모든 설정을 CLI 위치 인자/플래그로 단일화
- **60초 TTL 캐싱**: 디렉토리 스캔 비용 최소화

### 검증

- 단위 테스트 479개 통과
- 통합 테스트: Docker (clean Ubuntu 24.04), venv (호스트 격리) 두 환경에서 검증
