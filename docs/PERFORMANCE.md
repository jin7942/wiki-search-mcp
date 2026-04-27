# Performance Tuning

대규모 Wiki(1000+ 페이지)에서 최적의 성능을 위한 가이드입니다.

---

## Embedding Model Selection

| 프리셋 | 모델 | 메모리 | 속도 | 정확도 | 권장 상황 |
|--------|------|--------|------|--------|----------|
| `fast` | `all-MiniLM-L6-v2` | 100MB | 빠름 | 중 | 영어 문서, 빠른 응답 우선 |
| `accurate` | `ko-sroberta-multitask` | 400MB | 보통 | 높음 | 한국어 문서, 정확도 우선 |

```bash
# 빠른 모델 사용 (영어 Wiki)
EMBEDDING_MODEL=fast wiki-search-mcp index ./wiki --full

# 정확한 모델 사용 (한국어 Wiki, 기본값)
EMBEDDING_MODEL=accurate wiki-search-mcp index ./wiki --full
```

---

## Memory Optimization

### 증분 인덱싱 활용

전체 재구축 대신 변경분만 업데이트하여 메모리 사용량을 줄입니다:

```python
wiki_reindex(full=False)  # 변경된 파일만 처리
wiki_reindex(full=True)   # 전체 재구축 (메모리 많이 사용)
```

### 불필요한 파일 제외

설정 파일을 사용하지 않습니다. 다음 3가지로 무시 대상을 제어합니다.

1. **dot-prefix 자동**: `.obsidian`, `.git` 등 모든 dotfile/dotdir
2. **`.gitignore`**: wiki 루트에 `.gitignore`를 두면 자동 적용
   ```bash
   # ~/my-notes/.gitignore
   *.tmp
   drafts/
   templates/
   ```
3. **`WIKI_IGNORE` 환경변수**: 콤마 구분 추가 패턴
   ```bash
   WIKI_IGNORE="*.tmp,drafts,templates" wiki-search-mcp serve
   ```

---

## Search Performance

### top_k 최소화

필요한 만큼만 결과를 요청하여 처리 시간을 줄입니다:

```python
# 빠른 검색 (적은 결과)
wiki_search(query="nginx", top_k=3)

# 더 많은 결과 필요 시
wiki_search(query="nginx", top_k=10)
```

### 그래프 확장 비활성화

관련 문서 탐색이 불필요하면 비활성화하여 속도를 높입니다:

```python
# 빠른 검색 (그래프 확장 없음)
wiki_search(query="nginx", expand_graph=False)

# 관련 문서 포함 (기본값)
wiki_search(query="nginx", expand_graph=True)
```

### 검색 모드 선택

상황에 맞는 검색 모드를 선택합니다:

| 모드 | 특징 | 권장 상황 |
|------|------|----------|
| `hybrid` | 벡터 + 키워드 결합 | 일반적인 검색 (기본값) |
| `vector` | 의미 기반 검색 | 유사 개념 찾기 |
| `keyword` | 정확한 텍스트 매칭 | 특정 용어 검색 |

```python
wiki_search(query="SSL 인증서", mode="hybrid")   # 의미 + 키워드
wiki_search(query="nginx.conf", mode="keyword")  # 정확한 파일명
wiki_search(query="웹서버 보안", mode="vector")  # 유사 문서
```

---

## Benchmark

| 페이지 수 | 인덱싱 시간 | 검색 시간 | 메모리 |
|----------|------------|----------|--------|
| 100 | ~10초 | <50ms | ~200MB |
| 500 | ~1분 | <100ms | ~500MB |
| 1000 | ~2분 | <150ms | ~800MB |
| 5000+ | ~10분 | <200ms | ~2GB |

*측정 환경: M1 Mac, accurate 모델, hybrid 검색*
