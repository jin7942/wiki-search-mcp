# wiki-search-mcp

[![PyPI version](https://badge.fury.io/py/wiki-search-mcp.svg)](https://badge.fury.io/py/wiki-search-mcp)
[![PyPI downloads](https://img.shields.io/pypi/dm/wiki-search-mcp.svg)](https://pypi.org/project/wiki-search-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/wiki-search-mcp.svg)](https://pypi.org/project/wiki-search-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub stars](https://img.shields.io/github/stars/jin7942/wiki-search-mcp.svg)](https://github.com/jin7942/wiki-search-mcp/stargazers)
[![GitHub issues](https://img.shields.io/github/issues/jin7942/wiki-search-mcp.svg)](https://github.com/jin7942/wiki-search-mcp/issues)
[![GitHub last commit](https://img.shields.io/github/last-commit/jin7942/wiki-search-mcp.svg)](https://github.com/jin7942/wiki-search-mcp/commits)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

**Zero-config Personal Knowledge Management(PKM) MCP 서버** — Claude Desktop이 로컬 Markdown 노트를 자동 분류·검색·정리합니다. 설정 파일 없음. 사용자의 폴더 구조를 그대로 따릅니다.

## 무엇을 할 수 있나

```text
사용자: "오늘 nginx SSL 설정 메모 정리해줘"
Claude: → 미분류 파일 감지
        → 본문 분석 → "infra" 카테고리 + ["nginx","ssl"] 태그 추천
        → 사용자 승인
        → frontmatter 추가 + infra/ 폴더로 이동
        → 자동 인덱싱

사용자: "지난번 SSL 인증서 어떻게 적용했더라?"
Claude: → 의미 기반 검색 (벡터 + 키워드 하이브리드)
        → 관련 문서 + wikilink로 연결된 문서 함께 반환
```

## Features

- **Zero-Config**: 설정 파일 없음. 빈 디렉토리든 기존 노트 폴더든 그대로 사용
- **자동 분류**: 미분류 파일 감지 → 카테고리/태그 추천 → Claude가 직접 정리
- **카테고리 자동 감지**: 사용자 폴더 구조가 곧 카테고리 (수동 정의 불필요)
- **Hybrid Search**: 벡터(sentence-transformers) + BM25 키워드 결합 (RRF), 한국어 최적화
- **Graph RAG**: wikilink `[[link]]` 관계로 연관 문서 자동 확장
- **Local Execution**: 외부 API 없이 로컬에서 모든 처리 (비용 0)
- **Read-only MCP**: 모든 도구가 읽기 전용. 파일 쓰기는 Claude의 일반 도구가 담당하므로 데이터 안전

## Quick Start

```bash
# 1. 설치
pipx install wiki-search-mcp

# 2. Claude Desktop 등록 (어떤 디렉토리든)
wiki-search-mcp config ~/my-notes

# 3. Claude Desktop 재시작
```

빈 디렉토리든 기존 노트 디렉토리든 가리키기만 하면 됩니다. 첫 검색 시 자동으로 인덱스가 생성되고, 이후엔 watcher가 변경을 감지합니다.

## Table of Contents

- [Quick Start](#quick-start)
- [Features](#features)
- [카테고리는 어떻게 정해지나](#카테고리는-어떻게-정해지나)
- [MCP Tools](#mcp-tools)
- [CLI Commands](#cli-commands)
- [Configuration](#configuration)
- [Ignore Patterns](#ignore-patterns)
- [File Watching](#file-watching)
- [Troubleshooting](#troubleshooting)
- [Documentation](#documentation)
- [License](#license)

## 카테고리는 어떻게 정해지나

설정 파일을 만들지 않습니다. 다음 우선순위로 자동 결정됩니다.

1. **사용자 폴더 자동 감지**: 노트 루트(또는 `pages/`) 하위 디렉토리 ≥ 2개면 그 이름이 카테고리
2. **AI 제안 폴백**: 카테고리가 없거나 1개뿐이면 Claude가 인덱스를 분석해 후보 제시

```text
~/my-notes/
├── work/         ← 카테고리 "work"
├── personal/     ← 카테고리 "personal"
├── infra/        ← 카테고리 "infra"
└── memo.md       ← 분류 대기 (Claude가 정리 제안)
```

## MCP Tools

총 15개 도구. **모두 read-only** — 파일 쓰기는 Claude의 일반 도구가 담당.

| 분류 | 도구 | 설명 |
|------|------|------|
| 검색 | `wiki_search` | 하이브리드(벡터+키워드) 검색 + 그래프 확장 |
| 검색 | `wiki_get_similar` | 유사 문서 추천 |
| 검색 | `wiki_get_backlinks` | 역링크 조회 |
| 검색 | `wiki_find_orphans` | 고아 문서 탐색 |
| 조회 | `wiki_get_document` | 문서 상세 조회 |
| 조회 | `wiki_list_documents` | 카테고리/태그/상태별 목록 |
| 조회 | `wiki_stats` | 전체 통계 |
| 분류 | `wiki_get_categories` | 폴더 자동 감지 카테고리 |
| 분류 | `wiki_suggest_categories` | AI 카테고리 후보 제안 |
| 분류 | `wiki_pending` | 미분류 / 정리 대기 파일 |
| 분류 | `wiki_suggest_classification` | 단일 파일 분류 추천 |
| 분류 | `wiki_suggest_tags` | 태그 자동 추출 |
| 관리 | `wiki_reindex` | 인덱스 재구축 |
| 관리 | `wiki_watch_status` | 파일 감시 상태 |
| 관리 | `wiki_validate` | frontmatter / wikilink 검증 |

상세 사용법: [API Reference](docs/API.md)

## Requirements

- Python 3.9+
- ~500MB 디스크 (임베딩 모델 캐시)

## CLI Commands

### `config <path>`

Claude Desktop에 MCP 서버를 등록합니다.

```bash
wiki-search-mcp config ~/my-notes
```

`~/.claude/claude_desktop_config.json`에 자동 추가됩니다.

### `index <path>`

수동 인덱싱. MCP 서버는 시작/변경 시 자동 인덱싱하므로 일반적으로 불필요합니다.

```bash
wiki-search-mcp index ~/my-notes          # 증분 업데이트
wiki-search-mcp index ~/my-notes --full   # 전체 재구축
```

### `serve <path>`

MCP 서버 직접 실행 (디버깅용).

```bash
wiki-search-mcp serve ~/my-notes
wiki-search-mcp serve ~/my-notes --log-level DEBUG --no-watch
```

## Configuration

**환경변수 없음.** 모든 설정은 CLI 위치 인자/플래그로 전달합니다. `config` 명령은 옵션을 `claude_desktop_config.json`의 `args` 배열에 직접 직렬화합니다.

### CLI Options (`serve` / `config` 공통)

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `<path>` | 노트 루트 경로 (위치 인자, 필수) | — |
| `--model NAME` | 임베딩 모델 프리셋 (`fast`/`accurate`) 또는 모델명 | `accurate` |
| `--ignore PATTERN` | 추가 무시 패턴 (반복 가능) | (없음) |
| `--no-watch` | 파일 감시 비활성화 | (감시 활성) |
| `--debounce SECONDS` | 감시 디바운스(초) | `2.0` |
| `--log-level LEVEL` | `DEBUG`/`INFO`/`WARNING`/`ERROR` | `WARNING` |
| `--log-file PATH` | 로그 파일 경로 | (stderr만) |

### Embedding Models

| 프리셋 | 모델 | 특징 |
|--------|------|------|
| `fast` | `all-MiniLM-L6-v2` | 빠름, 영어 최적화 |
| `accurate` | `ko-sroberta-multitask` | 정확, 한국어 최적화 (기본값) |

### Manual Setup

CLI 대신 직접 설정하려면 `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "wiki-search": {
      "command": "wiki-search-mcp",
      "args": ["serve", "/absolute/path/to/your/notes"]
    }
  }
}
```

옵션을 추가하려면 `args` 배열에 그대로 이어붙이세요:

```json
"args": ["serve", "/abs/path", "--model", "fast", "--no-watch"]
```

또는 `wiki-search-mcp config <path> --model fast --no-watch` 한 줄로 자동 생성하면 됩니다.

## Ignore Patterns

설정 파일을 사용하지 않습니다. 다음 3가지로 무시 대상이 결정됩니다.

1. **자동**: 점(`.`)으로 시작하는 디렉토리/파일 (`.git`, `.obsidian`, `.vectordb`, `.DS_Store` 등)
2. **`.gitignore` 자동 활용**: 노트 루트의 `.gitignore`가 있으면 패턴 적용
3. **`--ignore` 옵션**: CLI에서 반복 지정 가능

```bash
wiki-search-mcp serve ~/notes --ignore "draft" --ignore "*.bak" --ignore "private"
```

## File Watching

MCP 서버가 실행되면 자동으로 노트 디렉토리를 감시합니다.

- `.md` 파일이 추가/수정/삭제되면 자동 인덱스 갱신
- 디바운스: 연속된 변경은 마지막 변경 후 2초 대기 후 처리
- 비활성화: `--no-watch`

```bash
wiki-search-mcp serve ~/notes --no-watch          # 감시 비활성화
wiki-search-mcp serve ~/notes --debounce 5.0      # 디바운스 5초
```

## Troubleshooting

### 모델 다운로드가 느린 경우

첫 실행 시 임베딩 모델(~400MB)을 다운로드합니다. HuggingFace 토큰을 설정하면 더 빠릅니다.

```bash
export HF_TOKEN=your_huggingface_token
```

### 인덱싱이 안 되는 경우

```bash
wiki-search-mcp index ~/my-notes --full
```

### MCP 서버가 연결되지 않는 경우

```bash
# 직접 실행하여 에러 확인
wiki-search-mcp serve ~/my-notes --log-level DEBUG
```

## Documentation

| 문서 | 설명 |
|------|------|
| [API Reference](docs/API.md) | MCP 도구 상세 사용법 (15개) |
| [Performance Tuning](docs/PERFORMANCE.md) | 대규모 노트 최적화 |
| [Writing Guide](docs/WRITING.md) | Frontmatter, State, Confidence |
| [Installation Guide](docs/INSTALLATION.md) | 시나리오별 상세 설치 |

## License

MIT License
