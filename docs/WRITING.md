# Document Writing Guide

Wiki 문서 작성 규칙입니다.

---

## Frontmatter (Optional)

YAML frontmatter를 추가하면 더 정확한 검색이 가능합니다:

```yaml
---
title: 문서 제목
category: infra | devops | domain | projects | personal | troubleshooting
tags: [태그1, 태그2]
created: 2024-01-01
updated: 2024-01-01
state: draft | review | stable | deprecated | archived
confidence:
  tested: true | false
  production: true | false
  sources: primary | secondary | inference
  freshness: current | recent | stale
---
```

**frontmatter 없는 경우:**
- `title`: 파일명 사용
- `category`: `uncategorized`
- `state`: `stable`
- `confidence`: `low`

---

## 5-State Lifecycle

| State | 의미 | 검색 포함 |
|-------|------|----------|
| `draft` | 작성 중 | X |
| `review` | 검토 중 | O |
| `stable` | 안정 | O |
| `deprecated` | 폐기 예정 | O (경고) |
| `archived` | 보관 | X |

---

## 4-Factor Confidence

신뢰도는 4가지 요소의 점수 합으로 계산됩니다:

| 요소 | 값 | 점수 |
|------|-----|------|
| tested | true | +30 |
| production | true | +30 |
| sources | primary | +20 |
| sources | secondary | +10 |
| freshness | current (<3개월) | +20 |
| freshness | recent (<1년) | +10 |

**신뢰도 레벨:**
- **high**: 70점 이상
- **medium**: 40~69점
- **low**: 40점 미만

---

## Wikilink

문서 간 연결로 Graph RAG를 활용합니다:

```markdown
이 문서는 [[infra/nginx-config]]와 관련됩니다.
```

검색 시 wikilink로 연결된 문서도 `related`에 포함됩니다.

---

## Sensitive Information

비밀번호, API 키, IP 주소 등은 본문에 직접 작성하지 않습니다.

**저장 위치:**
```
wiki/.secrets/credentials.md  # .gitignore에 포함
```

**참조 방법:**
```markdown
서버 IP: [[.secrets/credentials#server-ip]]
```

옵시디언에서 wikilink를 클릭하면 해당 항목으로 바로 이동합니다.
