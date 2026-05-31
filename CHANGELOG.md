# 변경 이력

이 프로젝트의 모든 주요 변경사항은 이 파일에 기록됩니다.
포맷은 [Keep a Changelog](https://keepachangelog.com/) 기반이며 [Semantic Versioning](https://semver.org/)을 따릅니다.

## [0.4.0] - 2026-05-31

0.3.0 운영 보고서의 P0/P1/P2 일괄 해결. inbox 작성 중 분류 인터럽트(P0), 카테고리
1-depth 평탄 배치(P1), 파일 이동 후 깨지는 wikilink 누적(P1), pending 큐 정체(P2),
자동 state 마이그레이션이 ambiguous 로 보류된 경우의 수동 fallback(P3).

### Added

- **분류 진입 가드 — quiescence + min_body_chars + draft frontmatter (P0)**: inbox 에
  파일을 작성하다 잠깐 멈춘 사이 분류기가 미완성 본문을 LLM 에 보내 카테고리를
  결정해 버리던 문제. 세 겹 가드 추가:
  - ``DaemonOptions.quiescence_seconds`` (기본 60): 파일 ``mtime`` 이 임계 미만이면
    LLM 호출 없이 짧은 cooldown 후 다음 rescan 에서 재시도.
  - ``DaemonOptions.min_body_chars`` (기본 200): 본문(frontmatter 제외) ``strip()``
    길이가 임계 미만이면 ``ClassifierSkipped("too_short")`` 로 pending 처리.
  - frontmatter ``draft: true`` 또는 ``locked: true``: 사용자가 명시적으로 표시한
    초안은 분류 대상에서 제외 (``"true"``/``"yes"`` 문자열도 인정).
  - 각 가드는 단독 비활성 가능 (0 또는 비표시).
- **서브카테고리 자동 라우팅 (P1)**: 기존엔 분류기가 항상 ``<category>/<basename>``
  으로 평탄 배치해 사용자 정리분(``projects/한수원/...``) 과 자동분(``projects/...``)
  이 두 층으로 갈렸음. 변경:
  - ``ClassificationDecision`` 에 ``subcategory: str | None`` 추가.
  - ``CategoryService.list_subfolders()`` 가 각 카테고리의 1-depth 활성 서브폴더
    목록을 반환 (staging/ignore 제외).
  - LLM 프롬프트가 ``subfolders_by_category`` 화이트리스트를 받아 적절한 서브폴더로
    라우팅. 화이트리스트에 없는 임의 폴더 제안은 파서에서 ``None`` 으로 강등.
  - frontmatter 에도 ``subcategory`` 키 기록 (사용자 값 우선).
  - 파일은 ``<category>/<subcategory>/<basename>`` 으로 이동.
- **파일 이동 시 inbound wikilink 자동 보정 (P1)**: 분류기가 ``inbox/foo.md`` →
  ``infra/foo.md`` 로 옮길 때 다른 파일 본문에 박힌 ``[[inbox/foo]]`` / ``[[foo]]``
  같은 wikilink 가 깨진 상태로 누적되던 문제. ``FrontmatterWriter.rewrite_inbound_links``
  옵션 (기본 ``True``) 으로 자동 치환. 안전 정책:
  - 전체 경로 표기는 즉시 치환.
  - basename-only 링크는 vault 전역에 동일 basename 이 유일할 때만 치환 (모호하면 보존).
  - ``#anchor`` / ``|label`` 보존.
  - 옮긴 파일 본인은 건드리지 않음.
- **daemon 주기 self-rescan (P2)**: ``rescan_interval_seconds`` (기본 300) 마다 외부
  FS 이벤트 없이도 ``_rescan()`` 발화. cooldown 만료 항목이 영원히 안 깨어나던 문제
  (``rate_limited`` / ``classifier_error`` 후 잔류 pending) 해결. 0 이하로 두면 비활성.
- **``daemon migrate-state`` CLI (P3)**: 자동 state 마이그레이션이 후보 2개 이상이라
  ambiguous 로 보류된 경우의 수동 fallback. ``wiki-search-mcp daemon migrate-state
  <옛 state 디렉토리> [WIKI_PATH] [--overwrite]``. ``daemon_status.json`` 파일 경로를
  넘겨도 부모를 source 로 인식.

### Changed

- ``ClassificationRequest`` 에 ``subfolders_by_category: dict[str, tuple[str, ...]]``
  필드 추가 (기본값 빈 dict — 후방 호환).
- CLI ``daemon start`` 에 ``--quiescence-seconds`` / ``--min-body-chars`` /
  ``--rescan-interval-seconds`` / ``--rewrite-inbound-links`` / ``--no-rewrite-inbound-links``
  옵션 노출. 백그라운드 spawn 시에도 그대로 전달.

### Tests

- ``tests/unit/services/test_classifier_guards.py`` 신설: ``too_short`` / ``user_locked``
  reason, ``min_body_chars=0`` 비활성, ``draft: false`` 통과, 문자열/불리언 모두 인정.
- ``tests/unit/infrastructure/test_writer_subcategory_and_links.py`` 신설:
  서브카테고리 이동, 평탄 배치 회귀 보존, 전체 경로/basename 보정, 모호 시 보존,
  anchor/label 보존, rewrite 비활성, 자기 파일 보존.
- ``tests/unit/services/test_category_list_subfolders.py`` 신설: 1-depth 만, staging
  제외, 파일 제외, 재귀 안 함, 사전순.
- ``tests/unit/services/llm/test_prompt_subcategory.py`` 신설: prompt 에 subfolders
  포함, 파서가 화이트리스트 검증, 알 수 없는 값은 ``None`` 강등, 누락/null 후방 호환.
- ``tests/unit/infrastructure/test_daemon_quiescence.py`` 신설: 최근 수정 파일은 LLM
  호출 없이 cooldown, 과거 mtime 은 통과, periodic rescan 외부 이벤트 없이 발화.
- ``tests/unit/infrastructure/test_state_migrate.py`` 에 ``TestMigrateFrom`` 추가: 수동
  source 지정 / 현재 데이터 있으면 거부 / overwrite 강제 / status.json 경로 허용 /
  source==current 거부 / 옮길 파일 전무 시 raise.
- 기존 회귀 테스트(``test_classifier_service::test_classify_uses_suggestion_and_categories``,
  ``test_daemon_reindex``, ``test_daemon_lifecycle``) 는 신규 가드와 의도 충돌 부분만
  ``min_body_chars=0`` / ``quiescence_seconds=0`` 으로 비활성해 원 의도 보존.

### Notes

- 그래프를 "온톨로지"로 만드는 작업(보고서 #3b)은 v0.4.0 범위 외 — 별도 RFC.
- MCP serve 멀티 클라이언트 share(보고서 #4.2)는 stdio transport 한계로 본 릴리스
  범위 외.

## [0.3.0] - 2026-05-27

사용자 환경 진단 보고서(0.2.6)의 부차 결함 P2/P3 및 신규 문서 inbox 우회 문제를 일괄 해결.

### Added

- **``daemon install`` / ``daemon uninstall`` — OS 레벨 자동 재기동 (P2)**: daemon이 죽어도 아무도 살리지 않아 inbox 자동분류가 사실상 멈추던 문제. macOS는 launchd LaunchAgent(``KeepAlive``), Linux는 systemd user service(``Restart=always``)를 생성/로드해 OS가 supervisor 역할을 한다. vault 경로 해시로 유닛을 격리해 여러 vault를 동시 등록 가능. 유닛 텍스트 생성은 ``infrastructure/daemon/service_unit.py`` 의 순수 함수로 분리(테스트 가능).
- **vault 경로 이전 시 옛 daemon state 자동 탐지/이전 (P3)**: state 디렉토리는 ``sha1(wiki_path)[:12]`` 로 격리되는데, vault를 옮기면 해시가 바뀌어 옛 작업 이력(applied 17건 + pending 1603건 등)이 고립됐다. ``daemon start`` 시 ``infrastructure/daemon/state_migrate.py`` 가 안전 조건 하에 자동 이전: 새 경로 state가 비어 있고 + 데이터를 가진 옛 후보가 **정확히 1개일 때만** 복사. 후보가 2개 이상이면 모호하므로 자동 이전하지 않고 안내만 표시(오탐 방지 우선).

### Fixed

- **MCP serve 중복 기동 (P2)**: serve 진입점이 기존 인스턴스 검사 없이 새 프로세스를 띄워 같은 vault에 serve가 3개까지 동시 실행되던 문제. file watcher가 같은 파일을 두 번 보고 reindex가 중복 트리거되어 LanceDB 매니페스트 race 위험. serve 전용 PidLock(``serve.lock`` / ``serve.pid``, daemon 것과 별도)을 추가해 두 번째 인스턴스는 ``sys.exit(0)`` 으로 깨끗하게 종료.

### Changed

- **MCP instructions의 inbox 강제 규칙을 최우선 + 단정형으로 강화**: 신규 문서를 카테고리 폴더에 직접 작성해 daemon 자동 분류 경로를 우회하는 문제가 잔존. 권고 톤("따르세요")을 "[최우선 규칙]" 섹션 + 파일 작성 전 자가 확인 체크리스트 + "금지/강제" 명시로 전환. read-only 원칙은 유지(서버가 강제 못 하므로 Claude가 스스로 지키도록 명령 강도만 높임).

### Tests

- ``tests/unit/infrastructure/test_state_migrate.py`` 신설: 단일 후보 이전 / 새 경로에 데이터 있으면 skip / 후보 2개 이상이면 보류 / 현재 디렉토리 제외 / 빈 경우.
- ``tests/unit/infrastructure/test_service_unit.py`` 신설: launchd KeepAlive+RunAtLoad / systemd Restart=always / ExecStart 정확성 / 폴백 CLI argv split / 같은 vault 동일 label.
- ``tests/unit/adapters/test_serve_lock.py`` 신설: serve/daemon 락 파일 분리 / 두 번째 serve 거부 / ``_acquire_serve_lock`` True·False.
- ``tests/unit/adapters/test_instructions.py``: v0.3.0 최우선 규칙 + 금지 + 자가 확인 체크리스트 회귀 1건 추가.

## [0.2.7] - 2026-05-27

### Fixed

- **lancedb 0.13+ 의 ``list_tables()`` 반환 타입 변경에 미대응해 검색·통계가 전체 무력화되던 P0 회귀**: lancedb는 0.13 전후로 ``list_tables()`` 반환을 ``list[str]`` 에서 ``ListTablesResponse(tables=[...], page_token=...)`` 객체로 변경(pagination 도입)했다. ``vector_store.py:58`` 과 ``indexer.py:217`` 의 ``"wiki" in self._db.list_tables()`` 는 신버전에서 객체를 ``(field_name, value)`` 쌍으로 순회하므로 **항상 False**. 그 결과:
  - ``LanceVectorStore.exists()`` → False → ``StatsService`` 가 ``total_pages=0``, ``SearchService`` / ``ValidationService`` 가 "Index not built yet" 반환.
  - ``WikiIndexer.reindex()`` 는 게이트를 안 거쳐 정상 동작 → "reindex는 156건 indexed인데 stats는 0건" 모순의 정체.
  - 증분 인덱싱 경로(``indexer.py:217``)도 기존 테이블 인식 실패 → 매번 사실상 full 재구축으로 떨어지던 잠재 비효율.
  
  ``infrastructure/storage/lancedb_compat.py`` 에 ``list_table_names(db)`` / ``has_table(db, name)`` 헬퍼 신설. 반환이 ``ListTablesResponse`` 면 ``.tables`` 에서, ``list`` 면 그대로 정규화해 신/구버전 모두에서 동작. 두 호출처를 ``has_table`` 로 전환.

### Changed

- **``lancedb`` 의존성에 상한 추가** (``>=0.4.0`` → ``>=0.4.0,<0.31``): 상한 부재가 0.30.2 의 breaking change 를 자유롭게 끌어들여 P0 를 유발한 구조적 원인. 검증된 0.30.x 까지로 제한. (헬퍼가 버전 호환을 흡수하므로 추후 상한 상향은 동작 확인 후 진행.)

### Tests

- ``tests/unit/infrastructure/test_lancedb_compat.py`` 신설 9건: 신버전(ListTablesResponse) / 구버전(list[str]) / 빈 경우 + ``in`` 직접 사용 시 False 가 되는 함정 고정 + 실물 lancedb create→has_table end-to-end.
- ``tests/unit/infrastructure/test_vector_store.py::test_exists_returns_true_when_table_exists`` 가 수정 전 코드에서 FAIL → 수정 후 PASS 확인 (회귀 실증).
- 격리 실물 검증: ``WikiIndexer.reindex(full=True)`` → 1 indexed, 파일 추가 후 ``reindex(full=False)`` → 2 indexed (증분 경로 기존 테이블 인식), ``exists()`` True, doc count 2.

## [0.2.6] - 2026-05-18

### Fixed

- **공백/한글/이모지 포함 정상 파일명이 ``InvalidPathError``로 거부되던 오탐**: ``core/path_validator.py:25``의 ``SAFE_PATH_PATTERN`` 정규식 화이트리스트가 일반 공백(U+0020)을 누락해 ``inbox/한수원 안전관리 SER 제안서.md`` 같은 OS상 정상 파일명이 분류 단계에서 모두 거부됐다. 더 나쁜 건 로그가 ``Path traversal attempt: ...``로 찍혀 사용자가 진짜 공격으로 오인. 정규식 화이트리스트를 통째로 제거하고 ``..`` / ``/시작`` / ``\\x00`` / ``\\`` / ``%`` 명시 블랙리스트 + ``_validate_within_base`` 의 ``resolve() + is_relative_to(base)`` 를 traversal 방어의 단일 진실로 사용. Obsidian/Logseq/Notion 등 다른 PKM 도구의 관행과 일치.
- **daemon ``error_count`` 가 silent 실패 2경로에서 증가 안 하던 가시성 결함**:
  - ``runner.py:200~204`` 의 ``find_pending() failed`` (인덱스/디스크 스캔 예외)
  - ``runner.py:217~221`` 의 ``queue full; dropping enqueue`` (큐 적체로 path 누락)
  
  운영자가 ``daemon_status.json`` 만 봐서는 두 실패를 인지할 수 없었음. 두 경로 모두 ``self._status.increment("error_count")`` 추가.

### Changed

- **``InvalidPathError.of(path, reason=None)`` 시그니처 확장**: 거부 사유 8종(``empty`` / ``absolute`` / ``parent_traversal`` / ``null_byte`` / ``backslash`` / ``percent_encoded`` / ``outside_base`` / ``resolve_failed``)을 ``context.details["reason"]`` 에 노출. 메시지는 reason 있으면 ``"Invalid path (absolute): /etc/passwd"`` 형식, 없으면 기존 ``"Path traversal attempt: ..."`` 유지(backward compat).
- ``services/graph_service.py:_validate_path`` 가 자체 ``..``/``/`` 검사 대신 ``validate_path_for_query`` 로 위임. reason 분기를 일관되게 흘림.

### Security

- 화이트리스트 제거가 보안 약화로 보일 수 있지만, 실제 traversal 방어는 ``_validate_within_base`` 의 resolve+is_relative_to 가 담당하므로 방어 강도는 유지. 명시 블랙리스트에 ``%`` 를 추가해 URL 인코딩 우회 공격(``%2e%2e``, ``%2f``)을 보수적으로 차단. ``사용률 95%.md`` 같이 ``%`` 가 포함된 정상 파일은 거부되므로 ``percent`` 또는 다른 표기로 대체 필요.

### Tests

- ``tests/test_path_validator.py`` 전면 재구성:
  - 정규식이 막던 OS 정상 파일명(이모지/세미콜론/파이프/전각 문자) 거부 케이스 4건 삭제 — 의도적 허용으로 전환
  - 신규 8건: 공백 한글 파일명 / 괄호 대괄호 / apostrophe / 이모지 통과 / 전각 문자 통과 / 모든 reason 분기 검증(parametrize) / backward compat
- ``tests/unit/infrastructure/test_daemon_error_count.py`` 신설 2건: ``find_pending`` 예외 / ``queue full`` 모두 ``error_count++``
- 격리 실물 검증: 사용자 보고서의 실제 4개 파일명(``한수원 안전관리 SER 제안서.md`` 등) 통과 + 8개 attack 패턴(``/etc/passwd``, ``../``, ``\\x00``, ``\\``, ``%``, 빈) 모두 정확한 reason 으로 거부 확인.

---

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
