# 변경 이력

이 프로젝트의 모든 주요 변경사항은 이 파일에 기록됩니다.
포맷은 [Keep a Changelog](https://keepachangelog.com/) 기반이며 [Semantic Versioning](https://semver.org/)을 따릅니다.

## [0.2.5] - 2026-05-17

### Fixed

- **inbox 폴더가 카테고리 후보로 잡혀 staging 파일이 영원히 머물던 silent stuck**: v0.2.3에서 MCP instructions에 "새 메모는 반드시 ``inbox/``에 작성" 규칙을 박았지만 런타임 코드는 ``inbox/``를 1depth 디렉토리로 보고 카테고리 목록에 포함시켰다. 그 결과 ``CategoryService.detect_from_folders()``가 ``inbox``를 ``active_categories``로 전달 → LLM이 모호한 문서를 ``category="inbox"``로 응답 가능 → ``FrontmatterWriter._decide_target_path``가 ``parts[0] == category == "inbox"``로 판정해 파일 이동 안 함 → 게다가 ``find_pending``이 ``category="inbox"``를 정상 분류로 인정해 daemon이 재분류하지 않는 silent stuck. inbox 폴더의 파일이 영원히 staging에 머무는 사용자 보고를 코드 흐름에서 정확히 재현.
- 해결 ①: ``core/config.py``에 ``STAGING_FOLDER_PATTERN``과 ``is_staging_folder(name)`` 헬퍼 신설. 정규식 ``^[._]*(?:\d+\.?)?inbox$`` (대소문자 무시)로 ``inbox`` / ``Inbox`` / ``INBOX`` / ``_inbox`` / ``.inbox`` / ``0.Inbox`` / ``00.inbox`` 등 정렬용 prefix 변형까지 매치. ``inbox-archive`` / ``my-inbox`` / ``inboxing`` 같은 본체가 inbox 단어로 끝나지 않는 폴더는 일반 카테고리로 유지(오탐 회피).
- 해결 ②: ``CategoryService.detect_from_folders()``에서 staging 폴더를 ``categories``에서 제외하고 새로운 ``CategoryListing.staging_folders`` 필드로 별도 노출. ``mode`` 판정은 staging을 제외한 일반 카테고리 수만 본다 (staging만 있으면 ``empty``).
- 해결 ③: ``ClassificationService.find_pending()``의 인덱스/디스크 루프 양쪽에 staging 분기 추가. inbox 폴더 안의 .md 파일은 frontmatter 상태(``category`` 박혀 있어도)와 무관하게 항상 ``reason="in_staging"``으로 pending에 노출. daemon이 다시 큐잉해 적절한 카테고리 폴더로 이동.

### Changed

- ``CategoryListing.to_dict()``에 ``staging_folders`` 필드 추가. ``wiki_get_categories`` MCP 응답에 자동 노출.
- ``PendingReason`` Literal에 ``"in_staging"`` 추가. ``find_pending`` 정렬 순서에서 가장 높은 우선순위.
- MCP ``instructions.py``에 한 문단 추가: "inbox는 카테고리가 아니라 staging 영역". Claude가 ``staging_folders`` 필드로 확인하도록 안내.

### Tests

- ``tests/unit/test_staging_folder.py`` 신설 (헬퍼 단위 18건 — 매치/비매치 parametrize).
- ``tests/unit/services/test_category_service.py``: staging 격리 회귀 4건 추가 (변형 폴더 제외 / inbox만 있을 때 empty / lookalike 오탐 없음 / to_dict 노출).
- ``tests/unit/services/test_classification_service.py``: staging 강제 pending 회귀 3건 추가 (인덱스 + category 박힘 / 변형 폴더 / 디스크 신규).
- ``tests/unit/adapters/test_instructions.py``: instructions가 "inbox는 카테고리 아님"을 명시하는지 회귀 1건 추가.
- 격리 실물 검증: 사용자 vault 구조(inbox + Inbox + 0.Inbox + infra + devops + inbox-archive) 그대로 재현 → staging 3종 격리, ``inbox-archive``는 일반 카테고리 유지, staging 파일은 category 박혀 있어도 항상 pending 확인.

---

## [0.2.4] - 2026-05-15

### Fixed

- **다중 worker daemon에서 post-apply reindex가 LanceDB race로 100% 실패하던 버그 (치명)**: v0.2.3에서 분류/frontmatter 적용이 정상화되자 다음 단계인 ``indexer.reindex(full=False)`` 가 노출됐다. 두 worker가 동시에 ``list_tables`` → ``drop_table`` → ``create_table`` 흐름을 실행하면서 lancedb 0.30.2의 매니페스트 commit conflict (``Retryable commit conflict ... Overwrite transaction was preempted by concurrent transaction`` / ``Table 'wiki' already exists``)로 항상 한쪽이 실패. 결과: 분류는 디스크에 반영되지만 검색 인덱스는 첫 부트스트랩 시점에 고정되어 신규 문서가 ``wiki_search``로 영영 검색되지 않는 silent 장애.
- 해결 ①: ``WikiIndexer.reindex``의 ``drop_table`` + ``create_table`` 두 단계를 ``create_table(..., mode="overwrite")`` 단일 atomic 호출로 통합.
- 해결 ②: ``DaemonRunner._reindex_lock`` (``asyncio.Lock``) 추가. lancedb 0.30.2가 동시 ``overwrite`` 호출 자체를 보호하지 못하는 것으로 격리 검증됨 — daemon 측 직렬화가 필수. ``asyncio.to_thread``로 blocking reindex를 thread executor에 위임해 다른 worker 분류는 계속 병렬 진행.

- **``post-apply reindex failed`` 가 ``error_count``에 잡히지 않아 운영자가 인덱스 갱신 누락을 인지하지 못하던 가시성 결함**: 분류 자체는 성공이라 분류 error와 묶을 수 없음.
- 해결: ``daemon_status.json``에 ``reindex_error_count`` 별도 카운터 신설.

- **로그 메시지가 두 번씩 출력되던 cosmetic 회귀**: ``setup_logging``이 root에 핸들러를 두면서 ``wiki_search_mcp`` 네임스페이스 로거에도 핸들러가 누적되어 propagate 경로로 메시지가 중복 출력. ``pkg_logger.handlers = []`` + ``propagate=True``로 정리.

### Tests

- ``tests/unit/infrastructure/test_daemon_reindex.py`` 신설 (3건):
  - 2-worker 동시 ``_classify_and_apply`` 시 reindex 동시 실행 peak가 1을 넘지 않음
  - reindex 실패가 ``reindex_error_count``만 증가시키고 ``error_count``/``applied_count``는 분류 성공대로 처리됨
  - 소스 가드: ``drop_table("wiki")`` 호출이 indexer에서 사라지고 ``mode="overwrite"``가 명시되어 있음
- 격리 실물 검증: lancedb 0.30.2 동시 ``create_table(mode="overwrite")`` 5회 × 2-thread → unprotected는 5건 실패, ``threading.Lock``으로 직렬화하면 0건. 즉 daemon ``_reindex_lock``이 race를 실제로 차단함을 lancedb 실물로 확인.

---

## [0.2.3] - 2026-05-15

### Fixed

- **Daemon worker가 ``datetime.date`` JSON 직렬화 실패로 적용 기록을 못 남기던 버그 (치명)**: PyYAML이 frontmatter의 ``created: 2026-04-23`` 같은 따옴표 없는 ISO 스칼라를 ``datetime.date`` 객체로 자동 파싱하는데, 이 객체가 ``AppliedRecord.frontmatter_before`` 경유로 ``applied.jsonl``에 들어갈 때 표준 ``json.dumps``가 ``TypeError: Object of type date is not JSON serializable`` 으로 죽었다. 이로 인해 frontmatter 적용은 디스크에 반영되어도 ``applied_count`` 가 0으로 유지되고 후속 ``_indexer.reindex()`` 호출이 한 번도 일어나지 않아 ``total_pages: 0``이 영구히 지속되는 연쇄 장애 발생.
- 해결: ``infrastructure/jsonl/log.py``의 ``json.dumps``에 ``default=_json_default`` 폴백 핸들러 추가. ``datetime.date`` / ``datetime`` / ``time`` → ISO 8601 문자열, ``Path`` → str, ``set`` → 정렬 리스트로 변환.

- **rate_limited path가 watcher 재진입마다 ``pending.jsonl``에 무한 적재되던 문제**: 한 번 rate limit에 걸린 path가 ``find_pending()`` 재스캔에서 계속 다시 큐에 들어가면서 1,830줄까지 부풀어오르는 사례 보고됨.
- 해결: ``DaemonRunner._cooldown`` 메모리 캐시 추가. ``rate_limited`` / ``classifier_error`` 발생 path는 10분 cooldown 동안 ``_rescan()``에서 큐 재투입을 스킵.

- **``pending_count(status)`` 카운터가 ``rate_limited`` 적재에 누락되던 동기화 버그**: ``pending.jsonl``에는 라인이 쌓이는데 ``daemon_status.json``의 ``pending_count``는 0으로 유지되어 사용자가 적체 상태를 인지하지 못함.
- 해결: ``RateLimitError`` 핸들러도 ``pending_count`` 카운터를 증가시키도록 보정.

### Changed

- **MCP ``instructions``에 "새 메모는 반드시 ``inbox/``에 작성" 규칙 명시**: Claude가 새 메모를 카테고리 폴더(예: ``infra/``, ``devops/``)에 직접 작성하면서 daemon 자동 분류 경로를 우회하는 사용자 보고. instructions에 강제 규칙 + 이유 + 예외 케이스를 추가해 모든 새 메모가 ``inbox/`` 게이트를 통과하도록 강제.

### Tests

- ``test_jsonl_log.py``: ``datetime.date`` / ``datetime`` / ``Path`` / ``set`` 직렬화 회귀 테스트 3개 추가.
- ``test_instructions.py``: ``inbox`` 강제 규칙 명시 회귀 테스트 1개 추가.

---

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
