# 0.7.0 — 프로젝트 폴더 평면 누적 개선 (요청서 2026-07-20)

## P0. rate limiter 정책 (선행 전제)
- [x] rate acquire 를 LLM 호출 직전으로 이동 (guard/quiescence 스킵이 일일 예산을 소모하지 않게)
  - `ClassifierService(rate_acquire=...)` — provider.classify 직전에 await
  - `DaemonRunner._worker` 의 선행 `self._rate.acquire()` 제거
- [x] RateLimitError 시 cooldown = max(기본 600s, wait_seconds) — 3만초 대기를 600초마다 재시도하며 pending.jsonl 폭증하던 것 차단
- [x] pending.jsonl 중복 기록 dedup (path→reason 이 바뀔 때만 append)

## R1. 분류 목적지에 기존 서브폴더 포함 (필수)
- [x] `CategoryService.list_subfolders` 를 중첩 경로(카테고리 하위 2-depth, 예: `KT_ITPARK/인수인계`)까지 확장
- [x] `decide_target_path` 의 '제자리' 판정을 중첩 subcategory 에 맞게 일반화
- [x] 분류 프롬프트에 중첩 서브폴더 규칙 반영

## R3. 서브폴더 클러스터링 품질 개선 (필수)
- [x] 폴더명/카테고리명 동어반복 태그를 신호에서 제외 (`kt`, `kt-itpark` 등)
- [x] 문서 유형 축 1차 신호: 자격증명/회의록/보고서/가이드/메모 (파일명 휴리스틱, 날짜 prefix=회의록)
- [x] 넘버링 시리즈(`NN-` prefix, 날짜 아님) 분리 금지 — 한 그룹 유지
- [x] 우선순위: 시리즈 → 유형 → 잔여 태그 클러스터(기존 greedy)

## R2. 계층화 파이프라인 (필수)
- [x] `HierarchizationPlan` 모델 + LLM 검증 프롬프트/파서
- [x] `ClaudeCodeProvider.complete()` (범용 호출, classify 와 동일 재시도 정책)
- [x] `HierarchizationService`: plan(휴리스틱→LLM 정제→confidence) / apply(서브폴더 생성+이동+frontmatter+링크보정+applied.jsonl)
- [x] daemon 주기 태스크: health_check 임계 초과 폴더 → confidence ≥ threshold 자동 적용, 미만 pending.jsonl(`hierarchization`) 기록
- [x] CLI `daemon hierarchize` (수동 실행/승인 경로, --dry-run)

## R4. 파일명 정규화 적용 루프 (권장)
- [x] `FrontmatterWriter.rename()` — 원자적 rename + wikilink 보정 + AppliedRecord(rollback 호환)
- [x] CLI `daemon normalize-filenames` (--dry-run 기본 아님, reclassify 와 동일 UX)
- [x] daemon 주기 태스크에서 정규화 후보를 pending(`filename_normalization`) 으로 노출 (자동 적용은 안 함)

## 마무리
- [x] 테스트 (P0/R1/R2/R3/R4 각각)
- [x] 전체 테스트 통과
- [x] CHANGELOG 0.7.0
- [x] .claude-log 작업 로그
