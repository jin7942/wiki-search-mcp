# API Reference

wiki-search-mcp MCP 도구 상세 사용법입니다.

Claude Code에서 자동으로 호출되는 도구들입니다.

---

## wiki_search

Wiki 페이지를 하이브리드(벡터+키워드) 검색합니다.

```python
wiki_search(
    query="SSL 인증서 적용",       # 검색 질의
    top_k=5,                       # 결과 수 (기본: 5)
    expand_graph=True,             # 그래프 확장 (기본: True)
    category="infra",              # 카테고리 필터 (선택)
    tags=["nginx", "ssl"],         # 태그 필터 (선택, OR 조건)
    states=["stable", "review"],   # 상태 필터 (선택)
    confidence_min=50,             # 최소 신뢰도 점수 (선택, 0-100)
    mode="hybrid",                 # 검색 모드: "hybrid", "vector", "keyword"
    sort_by="similarity",          # 정렬: "similarity", "confidence", "updated", "title"
    sort_order="desc",             # 정렬 순서: "asc", "desc"
    expand=False,                  # 동의어 확장 (선택)
)
```

**반환값:**

```json
{
  "results": [
    {
      "path": "infra/ssl-setup.md",
      "title": "SSL 인증서 적용",
      "category": "infra",
      "summary": "Nginx에서 Let's Encrypt...",
      "confidence": {"level": "high", "score": 80},
      "state": "stable",
      "similarity": 0.89,
      "related": ["infra/nginx.md", "infra/certbot.md"]
    }
  ],
  "total_pages": 76,
  "query": "SSL 인증서 적용",
  "mode": "hybrid"
}
```

---

## wiki_reindex

인덱스를 재구축합니다.

```python
wiki_reindex(full=False)  # 증분 업데이트
wiki_reindex(full=True)   # 전체 재구축
```

---

## wiki_stats

Wiki 통계를 조회합니다.

```python
wiki_stats()
```

**반환값:**

```json
{
  "total_pages": 76,
  "by_category": {"infra": 4, "devops": 5, ...},
  "by_state": {"stable": 65, "draft": 5, ...},
  "by_confidence": {"high": 30, "medium": 40, "low": 6},
  "last_indexed": "2024-01-01T10:30:00"
}
```

---

## wiki_get_document

특정 문서를 조회합니다. 기본적으로 메타데이터 + 500자 미리보기만 반환합니다.

```python
wiki_get_document(
    path="infra/nginx-setup.md",  # 문서 상대 경로
    include_content=False,         # 전체 본문 포함 여부 (기본값: False)
    preview_size=500               # 미리보기 크기 (기본값: 500자)
)
```

**반환값 (include_content=False):**

```json
{
  "path": "infra/nginx-setup.md",
  "title": "Nginx 설정 가이드",
  "category": "infra",
  "tags": ["nginx", "webserver"],
  "summary": "...",
  "confidence": {"level": "high", "score": 80},
  "state": "stable",
  "content_preview": "# Nginx 설정 가이드\n\nNginx 웹서버 설정 방법입니다...",
  "content_size": 5000
}
```

**반환값 (include_content=True):**

```json
{
  "path": "infra/nginx-setup.md",
  "title": "Nginx 설정 가이드",
  "category": "infra",
  "tags": ["nginx", "webserver"],
  "summary": "...",
  "confidence": {"level": "high", "score": 80},
  "state": "stable",
  "content": "# Nginx 설정 가이드\n\n전체 본문 내용..."
}
```

---

## wiki_list_documents

조건에 맞는 문서 목록을 조회합니다 (검색 없이 필터링).

```python
wiki_list_documents(
    category="infra",   # 카테고리 필터 (선택)
    tag="nginx",        # 태그 필터 (선택)
    state="stable",     # 상태 필터 (선택)
    limit=50            # 최대 결과 수 (기본: 50)
)
```

**반환값:**

```json
{
  "documents": [
    {
      "path": "infra/nginx.md",
      "title": "Nginx 설정",
      "category": "infra",
      "state": "stable",
      "tags": ["nginx", "webserver"]
    }
  ],
  "count": 10,
  "filters": {"category": "infra", "tag": null, "state": null}
}
```

---

## wiki_get_backlinks

특정 문서를 참조하는 역링크를 조회합니다.

```python
wiki_get_backlinks(
    path="infra/nginx.md"  # 대상 문서 경로
)
```

**반환값:**

```json
{
  "target": "infra/nginx.md",
  "backlinks": [
    {"path": "infra/ssl-setup.md", "title": "SSL 설정", "category": "infra"},
    {"path": "devops/deploy.md", "title": "배포 가이드", "category": "devops"}
  ],
  "count": 2
}
```

---

## wiki_watch_status

파일 감시 상태를 조회합니다.

```python
wiki_watch_status()
```

**반환값:**

```json
{
  "enabled": true,
  "running": true,
  "watching_path": "/path/to/wiki/pages",
  "debounce_seconds": 2.0
}
```

---

## wiki_find_orphans

연결되지 않은 고아 문서를 찾습니다.

```python
wiki_find_orphans()
```

**반환값:**

```json
{
  "orphans": [
    {"path": "misc/old-doc.md", "title": "정리 필요한 문서", "category": "misc"}
  ],
  "count": 1
}
```

---

## wiki_get_similar

특정 문서와 유사한 문서를 찾습니다.

```python
wiki_get_similar(
    path="infra/nginx-setup.md",  # 대상 문서 경로
    top_k=5                        # 유사 문서 수 (기본: 5)
)
```

**반환값:**

```json
{
  "source": "infra/nginx-setup.md",
  "similar": [
    {"path": "infra/nginx-config.md", "title": "Nginx 설정", "similarity": 0.85}
  ],
  "count": 1
}
```

---

## wiki_suggest_tags

문서에서 태그를 자동 추출합니다.

```python
wiki_suggest_tags(
    path="infra/nginx-setup.md",  # 대상 문서 경로
    top_n=5                        # 추출할 태그 수 (기본: 5)
)
```

**반환값:**

```json
{
  "path": "infra/nginx-setup.md",
  "suggested_tags": ["nginx", "webserver", "reverse-proxy"],
  "existing_tags": ["infra"]
}
```

---

## wiki_validate

Wiki 인덱스 품질을 검사합니다.

```python
wiki_validate()
```

frontmatter 필수 필드 누락, 깨진 wikilink 등을 감지합니다.

**반환값:**

```json
{
  "status": "warning",
  "total": 76,
  "stats": {
    "missing_title": 5,
    "missing_state": 3,
    "missing_tags": 10,
    "missing_confidence": 15,
    "missing_created": 20,
    "missing_updated": 25,
    "broken_links": 2
  },
  "summary": {
    "complete": 30,
    "partial": 40,
    "no_frontmatter": 6
  },
  "issues": [
    {"path": "misc/old-doc.md", "type": "missing_title", "message": "title 필드 없음"},
    {"path": "infra/nginx.md", "type": "broken_link", "message": "[[missing-doc]] 링크 대상 없음"}
  ]
}
```

**상태 레벨:**
- `valid`: 문제 없음
- `warning`: 깨진 링크 있거나 partial > 10%
- `error`: 빈 인덱스이거나 no_frontmatter > 30%

---

## wiki_get_categories

현재 wiki에서 사용 가능한 카테고리를 조회합니다. 폴더 자동 감지 결과를 반환하며, 설정 파일은 사용하지 않습니다.

```python
wiki_get_categories()
```

**반환값:**

```json
{
  "mode": "folder",
  "categories": ["Notes", "Projects", "infra"],
  "detected_at": "2026-04-27T15:00:00+00:00"
}
```

**mode:**
- `folder`: 디렉토리 ≥ 2개 자동 감지됨
- `empty`: 카테고리 없음. `wiki_suggest_categories()`로 AI 제안 받기

---

## wiki_suggest_categories

`mode == "empty"`일 때 인덱스 분석 기반으로 카테고리 후보를 제안합니다.

```python
wiki_suggest_categories(top_k=10)  # 1-20
```

**반환값:**

```json
{
  "suggestions": [
    {"name": "infra", "doc_count": 12, "keywords": ["nginx", "ssl"]},
    {"name": "dev", "doc_count": 8, "keywords": ["python", "api"]}
  ]
}
```

기존 인덱싱된 문서의 `category` 빈도 + 본문 키워드 빈도 기반.

---

## wiki_pending

미분류 / 정리 대기 파일 목록을 반환합니다. 인덱스 + 디스크 set 차집합 기반이며 60초 TTL 캐싱.

```python
wiki_pending(limit=20)  # 1-200
```

**반환값:**

```json
{
  "items": [
    {"path": "Notes/draft.md", "reason": "no_frontmatter", "mtime": "2026-04-27T14:00:00+00:00"},
    {"path": "memo.md", "reason": "not_indexed", "mtime": "2026-04-27T13:30:00+00:00"}
  ],
  "count": 2
}
```

**reason:**
- `not_indexed`: 디스크에는 있으나 인덱스에 없음
- `no_frontmatter`: frontmatter 자체가 빈약 (카테고리/태그 모두 없음)
- `no_category`: `category` 필드만 누락

---

## wiki_suggest_classification

단일 파일에 대한 카테고리/태그 추천을 받습니다. 폴더 기반 카테고리 + 유사 문서 카테고리 투표 + 본문 키워드 분석을 종합합니다. MCP는 read-only이므로 실제 파일 수정은 Claude가 Read/Write로 수행하세요.

```python
wiki_suggest_classification(path="Notes/memo.md")
```

**반환값:**

```json
{
  "path": "Notes/memo.md",
  "category_candidates": ["Notes", "Projects"],
  "tag_candidates": ["nginx", "ssl", "config"],
  "similar_paths": ["infra/nginx.md", "infra/ssl-setup.md"],
  "reasoning": "카테고리 후보: Notes, Projects | 태그 후보: nginx, ssl, config | 유사 문서 2건 참조"
}
```
