# 변경 이력

## [Unreleased]

### Breaking Changes (환경변수 제거)

- **모든 환경변수 제거 (7 → 0)**. zero-config 정체성과 일관되게 모든 설정을 CLI 위치 인자/플래그로 전환.
  - `WIKI_PATH` → 위치 인자: `wiki-search-mcp serve <path>`
  - `WIKI_EMBEDDING_MODEL` → `--model {fast|accurate|<id>}`
  - `WIKI_IGNORE` → `--ignore PATTERN` (반복 가능)
  - `WIKI_WATCH=false` → `--no-watch` 플래그
  - `WIKI_DEBOUNCE` → `--debounce SECONDS`
  - `WIKI_LOG_LEVEL` → `--log-level {DEBUG|INFO|WARNING|ERROR}`
  - `WIKI_LOG_FILE` → `--log-file PATH`
- **`config` 명령 출력 변경**: `claude_desktop_config.json`의 `env` 섹션을 더 이상 작성하지 않습니다. wiki path와 옵션이 `args` 배열에 직접 직렬화됩니다.
- **`serve` 명령 시그니처 변경**: 기존 `wiki-search-mcp serve` (인자 없음) → `wiki-search-mcp serve <path>` (위치 인자 필수).
- **`setup_logging()` 시그니처 변경**: 환경변수 대신 `level`, `log_file` 인자로 호출.
- **모듈 import 부작용 제거**: `import wiki_search_mcp.adapters.mcp.server` 시 더 이상 환경변수 또는 로깅 초기화가 자동 실행되지 않습니다.

### Migration

기존 사용자는 다음 한 줄로 재등록하면 됩니다:

```bash
wiki-search-mcp config /Users/me/notes
```

옵션 사용 시:

```bash
wiki-search-mcp config /Users/me/notes --model fast --no-watch
```

생성되는 JSON:

```json
{
  "mcpServers": {
    "wiki-search": {
      "command": "wiki-search-mcp",
      "args": ["serve", "/Users/me/notes", "--model", "fast", "--no-watch"]
    }
  }
}
```

### Internal

- `IgnoreMatcher.env_patterns` → `extra_patterns`로 이름 변경, `from_wiki(wiki_path, extra_patterns=())` 시그니처
- `ServiceContainer(wiki_path, model_name, ignore_patterns=())` 시그니처 확장
- `WikiIndexer(wiki_path, model_name, ignore_patterns=())` 시그니처 확장
- `ServerOptions` dataclass 신설 (`adapters/mcp/server.py`)
- 신규 테스트: `tests/unit/core/test_logging.py`, `tests/unit/adapters/test_cli_serialization.py`

---

## Zero-Config 자동 분류 PKM 전환 (이전 작업)

### Breaking Changes

- **`init` 명령 제거**: zero-config 정책으로 인해 `wiki-search-mcp init`이 더 이상 존재하지 않습니다. 빈 디렉토리든 기존 노트 디렉토리든 `wiki-search-mcp config <path>`만 실행하면 됩니다.
- **`wiki-template/` 디렉토리 제거**: 패키지에서 템플릿이 제거되었습니다. 카테고리는 사용자의 폴더 구조를 그대로 따릅니다.
- **설정 파일 폐지**: 설정 파일을 사용하지 않습니다. ignore 패턴은 dot-prefix 자동 + `.gitignore` 자동 + `WIKI_IGNORE` 환경변수로 대체되었습니다.
- **`WikiConfig` 단순화**: yaml 파싱 로직과 `ignore_patterns`/`should_ignore` 필드가 제거되었고, 임베딩 모델 환경변수는 `WIKI_EMBEDDING_MODEL`로 통일되었습니다.

### Added

- **MCP `instructions` 내장**: FastMCP의 instructions 인자에 워크플로우 가이드를 주입하여, 사용자가 `CLAUDE.md` 없이도 분류 워크플로우를 활용할 수 있습니다 (`adapters/mcp/instructions.py`).
- **자동 분류 도구 4개 추가**:
  - `wiki_get_categories`: 폴더 자동 감지된 카테고리 조회
  - `wiki_suggest_categories`: 인덱스 분석 기반 카테고리 후보 제안
  - `wiki_pending`: 미분류 / 정리 대기 파일 목록
  - `wiki_suggest_classification`: 단일 파일 카테고리/태그 추천
- **`IgnoreMatcher`** (`infrastructure/ignore/matcher.py`): dot-prefix + `.gitignore` + `WIKI_IGNORE` 통합 매처
- **`CategoryService`** (`services/category_service.py`): 폴더 자동 감지 + 60초 TTL 캐싱 + AI 폴백 제안
- **`ClassificationService`** (`services/classification_service.py`): 인덱스/디스크 set 차집합 기반 pending 감지 + 임베딩 재사용 분류 추천
- 새 도메인 모델: `CategoryListing`, `PendingItem`, `ClassificationSuggestion`
- 신규 단위 테스트 ~50개

### Changed

- `WikiIndexer`가 `IgnoreMatcher`를 사용하도록 변경 (이전: `WikiConfig.should_ignore`)
- `ServiceContainer`에 `ignore_matcher`, `category_service`, `classification_service` lazy singleton 추가
- `invalidate_all`이 카테고리/분류 캐시도 무효화

### Removed

- `WikiConfig.ignore_patterns`, `WikiConfig.should_ignore`, `DEFAULT_IGNORE_PATTERNS`
- `wiki-search-mcp init` 명령
- `get_template_dir()`, `get_package_dir()` CLI 헬퍼 함수
- `tests/test_config.py` (`WikiConfig` 단순화로 대부분 무효)

---

## [0.8.2] - 2026-04-25

### Fixed

- **Protocol 정합성**: VectorRepository에 `to_arrow_list()` 추가, GraphRepository에 `node_count` property 추가
- **타입 안정성**: search_service.py에서 `hasattr()` 체크 제거, 직접 Protocol 메서드 사용
- **QueryExpanderProtocol**: expander 타입을 `Any`에서 `QueryExpanderProtocol | None`으로 변경
- **예외 처리 세분화**: handlers.py의 11개 함수에서 BusinessException, TechnicalException 분리 처리
- **쿼리 확장 검증**: 빈 쿼리에 대한 ValueError 발생, 최대 확장 수 제한 (MAX_EXPANDED_QUERIES=10)
- **경로 처리 일관성**: `normalize_document_path()`, `path_matches()` 유틸리티 추가
- **confidence 타입 검증**: indexer.py에서 잘못된 타입의 factor 값 무시 및 경고 로깅
- **경로 형식 검증**: vector_store.py에서 허용되지 않는 문자 포함 경로 차단
- **코드 정리**: logging.py 불필요한 TYPE_CHECKING 제거, tagger_service.py stopwords에서 기술 용어 제거

### Added

- `QueryExpanderProtocol`: 쿼리 확장기 인터페이스 추가 (core/protocols.py)
- `normalize_document_path()`: 문서 경로 정규화 함수 (core/utils.py)
- `path_matches()`: 경로 비교 함수 (core/utils.py)
- Protocol 테스트 (tests/unit/core/test_protocols.py)
- 예외 처리 테스트 (tests/unit/adapters/test_handlers.py)
- 쿼리 확장 검증 테스트 (tests/test_expander.py)
- 경로 정규화 테스트 (tests/test_utils.py)
- confidence 타입 검증 테스트 (tests/test_indexer.py)

### Changed

- `_apply_sort()` 메서드에 상세 docstring 추가
- `_with_content()` 메서드에 설계 의도 문서화
- CLI main.py의 pass 문에 설명 주석 추가

---

## [0.8.1] - 2026-04-25

### Breaking Changes

#### WikiSearcher 완전 제거
- `from wiki_search_mcp import WikiSearcher` → **AttributeError**
- `from wiki_search_mcp.legacy import WikiSearcher` → **ImportError**
- 마이그레이션: `ServiceContainer` 사용

```python
# Before (removed)
from wiki_search_mcp import WikiSearcher
searcher = WikiSearcher(wiki_path)
results = searcher.search("query")

# After
from wiki_search_mcp import ServiceContainer
container = ServiceContainer(wiki_path)
results = container.search_service.search("query")
```

#### 삭제된 파일
| 파일 | 라인 수 | 이유 |
|------|---------|------|
| legacy/searcher.py | 232 | 레거시 facade |
| legacy/__init__.py | 10 | 패키지 초기화 |
| tests/test_searcher.py | 419 | 레거시 테스트 |
| server.py `get_searcher()` | 11 | deprecated 함수 |

---

## [0.8.0] - 2026-04-24

### 아키텍처 (Clean Architecture 계층 정리)

루트에 방치된 파일들을 Clean Architecture 계층으로 정리했습니다.

#### 파일 이동
| 원본 | 대상 |
|------|------|
| config.py | core/config.py |
| utils.py | core/utils.py |
| tagger.py | services/tagger_service.py |
| expander.py | services/expander_service.py |
| indexer.py | infrastructure/indexing/indexer.py |
| watcher.py | infrastructure/watcher/watcher.py |
| cli.py | adapters/cli/main.py |

#### 삭제
| 파일 | 이유 |
|------|------|
| server.py | re-export 불필요 (하위 호환성 무시) |

#### 신규
| 파일 | 설명 |
|------|------|
| core/logging.py | 로깅 인프라 |
| infrastructure/indexing/__init__.py | 패키지 초기화 |
| infrastructure/watcher/__init__.py | 패키지 초기화 |

### 기능

#### 로깅 인프라 (core/logging.py)
- 환경변수 기반 로깅 설정
  - `WIKI_LOG_LEVEL`: DEBUG/INFO/WARNING/ERROR (기본: WARNING)
  - `WIKI_LOG_FILE`: 로그 파일 경로 (선택)
- 서비스별 로거 제공: `get_logger("service_name")`
- 검색 요청, 인덱싱 진행 로깅

#### WikiConfig (런타임 설정)
- WikiConfig 클래스 추가
- ignore_patterns: 인덱싱에서 제외할 패턴
- embedding_model: 임베딩 모델 프리셋

### Breaking Changes
- `from wiki_search_mcp.server import ...` 제거 (adapters/mcp/server.py 직접 사용)
- `from wiki_search_mcp.cli import ...` 제거 (adapters/cli/main.py 직접 사용)

### 테스트
- WikiConfig 테스트 추가
- 기존 테스트 import 경로 수정

---

## [0.7.0] - 2026-04-24

### 아키텍처 (Clean Architecture 완성)

v0.6.0에서 시작된 Clean Architecture 리팩토링을 완료했습니다.

#### MCP Adapter 완성
- **adapters/mcp/handlers.py**: MCP 도구 핸들러를 별도 모듈로 분리
  - 입력 검증, 파라미터 정규화, JSON 직렬화 담당
  - ServiceContainer를 통해 서비스 호출
  - 테스트 가능한 순수 함수 구조
- **adapters/mcp/server.py**: MCP 서버 초기화 및 도구 정의
  - FastMCP 기반 서버 설정
  - handlers.py 함수 호출로 비즈니스 로직 위임
- **server.py**: re-export 모듈로 변경 (하위 호환성 유지)

#### 레거시 코드 정리
- **searcher.py 삭제** (930줄 제거)
  - 모든 기능이 services/ 계층으로 이동 완료
  - legacy/searcher.py를 통한 하위 호환성 유지

### 마이그레이션 가이드

```python
# Before (deprecated)
from wiki_search_mcp.searcher import WikiSearcher
searcher = WikiSearcher(wiki_path)
results = searcher.search("query")

# After (recommended)
from wiki_search_mcp import ServiceContainer
container = ServiceContainer(wiki_path)
results = container.search_service.search("query")

# 또는 (하위 호환성, deprecated)
from wiki_search_mcp import WikiSearcher  # DeprecationWarning 발생
searcher = WikiSearcher(wiki_path)
results = searcher.search("query")
```

### 테스트
- handlers.py 단위 테스트 26개 추가
- test_server.py를 ServiceContainer 기반으로 마이그레이션

### 파일 변경 요약
| 변경 유형 | 파일 | 설명 |
|-----------|------|------|
| 신규 | adapters/mcp/handlers.py | MCP 도구 핸들러 (~400줄) |
| 신규 | adapters/mcp/server.py | MCP 서버 설정 (~300줄) |
| 신규 | tests/unit/adapters/test_handlers.py | 핸들러 테스트 (26개) |
| 수정 | server.py | re-export로 변경 (~60줄) |
| 삭제 | searcher.py | 레거시 코드 제거 (930줄) |

---

## [0.6.0] - 2026-04-24

### 아키텍처 (Clean Architecture)

프로젝트 구조를 Clean Architecture 패턴으로 전면 리팩토링했습니다.

#### Core 계층
- **core/models.py**: 도메인 모델 (Document, SearchResult, WikiStats 등)
- **core/protocols.py**: Repository 인터페이스 정의
- **core/exceptions.py**: 도메인 예외

#### Infrastructure 계층
- **infrastructure/embedding/**: 임베딩 제공자
- **infrastructure/storage/**: LanceDB, BM25, Graph, Meta 저장소
- **infrastructure/cache/**: LRU 쿼리 캐시

#### Services 계층
- **services/search_service.py**: 검색 유스케이스
- **services/document_service.py**: 문서 CRUD
- **services/graph_service.py**: 그래프 연산
- **services/validation_service.py**: Wiki 검증
- **services/stats_service.py**: 통계 수집

#### Adapters 계층
- **adapters/mcp/container.py**: 서비스 의존성 컨테이너 (DI)

---

## [0.5.0] - 2026-04-24

### 리팩토링
- **utils.py 추출**: parse_frontmatter, resolve_pages_path, tokenize 함수 분리
- **config.py 추출**: 설정 상수 중앙 집중화

### 캐싱
- LRU 쿼리 캐시 구현 (쿼리 임베딩 재사용)

---

## [0.4.0] - 2026-04-24

### 추가
- **wiki_validate**: Wiki 인덱스 품질 검사 도구
  - frontmatter 필수 필드 누락 감지 (title, state, tags, confidence, created, updated)
  - 깨진 wikilink 감지
  - 문서 분류: complete / partial / no_frontmatter
  - 상태 레벨: valid / warning / error

### 변경
- **유연한 파일 구조 지원**: pages/ 디렉토리 없이도 동작
  - pages/ 있으면 기존처럼 사용
  - pages/ 없으면 wiki_path 루트를 문서 디렉토리로 사용
  - 옵시디언 볼트 등 다양한 디렉토리 구조 지원
- **wiki_get_document 컨텍스트 최적화**:
  - `include_content` 기본값: True → False
  - `preview_size` 파라미터 추가 (기본값: 500자)
  - 문장 경계에서 자르기로 가독성 유지
  - MCP 응답 크기 최소화로 Claude 컨텍스트 절약

### 개선
- CLI index 명령: pages/ 없어도 경고만 출력 (오류 종료 아님)
- README: pipx 설치 방법 추가, 옵시디언 볼트 사용법 추가

---

## [0.3.0] - 2026-04-24

### 추가
- **하이브리드 검색**: BM25 키워드 검색 + 벡터 검색 결합 (RRF 알고리즘)
  - `mode` 파라미터: "hybrid", "vector", "keyword" 선택
  - `vector_weight`: 벡터 검색 가중치 조절 (0.0~1.0)
- **쿼리 확장**: 동의어로 검색 쿼리 자동 확장
  - `expand=True` 파라미터로 활성화
  - 한국어/영어 IT 용어 동의어 내장 (nginx ↔ 엔진엑스, docker ↔ 도커 등)
- **검색 정렬 옵션**: 다양한 기준으로 결과 정렬
  - `sort_by`: "similarity", "confidence", "updated", "title"
  - `sort_order`: "asc", "desc"
- **wiki_find_orphans**: 연결 안 된 고아 문서 감지
- **wiki_get_similar**: 벡터 유사도 기반 유사 문서 추천
- **wiki_suggest_tags**: 문서 내용 분석으로 태그 자동 추출
- **임베딩 모델 선택**: fast/accurate 프리셋 지원
  - fast: `all-MiniLM-L6-v2` (빠름, 영어 최적화)
  - accurate: `ko-sroberta-multitask` (정확, 한국어 최적화)

### 개선
- **Python 3.9 지원**: `from __future__ import annotations`로 하위 호환
- BM25 인덱스 자동 구축 (reindex 시)

### 새 의존성
- `rank_bm25>=0.2.2`: BM25 키워드 검색

---

## [0.2.0] - 2026-04-24

### 추가
- **wiki_get_document**: 문서 전체 내용 조회 도구
- **wiki_list_documents**: 카테고리/태그/상태별 문서 목록 조회 도구
- **wiki_get_backlinks**: 역링크 조회 도구 (특정 문서를 참조하는 문서 목록)
- **wiki_search 고급 필터**: category, tags, states, confidence_min 파라미터
- **다중-hop 그래프 확장**: 1-hop에서 2-hop으로 확장 (BFS 기반)
- **검색 캐싱**: LRU 캐시로 동일 쿼리 재임베딩 방지 (maxsize=100)
- **배치 임베딩**: 인덱싱 시 문서를 배치로 처리 (성능 개선)

### 수정
- **증분 인덱싱 버그 수정**: 변경되지 않은 파일도 매번 재임베딩하던 문제 해결
  - 이제 변경된 파일만 임베딩하고, 미변경 파일은 기존 데이터 재사용
  - 삭제된 파일도 메타데이터에서 자동 제거

### 개선
- wiki_search에서 필터링을 위해 더 많은 결과를 가져옴 (top_k * 4)
- 그래프 엣지를 양방향 인덱싱하여 탐색 성능 개선
- 대용량 Wiki에서 진행 상황 표시 (show_progress_bar)

---

## [0.1.0] - 2026-04-23

### 추가
- 시맨틱 검색 (sentence-transformers, 기본 모델: `jhgan/ko-sroberta-multitask`)
- Graph RAG: wikilink (`[[link]]`) 기반 관련 문서 확장
- 파일 감시: 문서 변경 시 자동 인덱싱 (디바운스 적용)
- CLI 명령어: `init`, `config`, `index`, `serve`
- MCP 도구: `wiki_search`, `wiki_reindex`, `wiki_stats`, `wiki_watch_status`
- 5-State 문서 생명주기: draft, review, stable, deprecated, archived
- 4-Factor 신뢰도 점수: tested, production, sources, freshness
- Frontmatter 없는 문서도 자동 인덱싱
- 카테고리 기반 문서 구조
- 한국어 최적화 임베딩 모델

### 보안
- 모든 도구 파라미터 입력 검증
- SQL Injection 방어 (경로 쿼리)
- Path Traversal 방어 (인덱서)
- 예외 처리 및 안전한 JSON 응답
