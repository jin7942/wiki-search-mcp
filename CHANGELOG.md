# 변경 이력

이 프로젝트의 모든 주요 변경사항은 이 파일에 기록됩니다.
포맷은 [Keep a Changelog](https://keepachangelog.com/) 기반이며 [Semantic Versioning](https://semver.org/)을 따릅니다.

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
