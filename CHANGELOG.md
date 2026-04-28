# 변경 이력

이 프로젝트의 모든 주요 변경사항은 이 파일에 기록됩니다.
포맷은 [Keep a Changelog](https://keepachangelog.com/) 기반이며 [Semantic Versioning](https://semver.org/)을 따릅니다.

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
