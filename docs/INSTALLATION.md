# Installation Guide

zero-config 정책에 따라 설치 시나리오는 단순합니다. `init` 명령은 제거되었고, 사용자는 빈 디렉토리든 기존 노트 디렉토리든 그대로 가리키기만 하면 됩니다.

---

## Scenario 1: 신규 사용자 - 빈 디렉토리에서 시작

```bash
# 1. 설치
pipx install wiki-search-mcp

# 2. 빈 노트 디렉토리 준비
mkdir -p ~/my-notes

# 3. Claude Desktop에 등록
wiki-search-mcp config ~/my-notes

# 4. Claude Desktop 재시작
```

이후 Claude Desktop에서 자유롭게 메모를 작성하면 됩니다. 카테고리가 필요해지면 Claude가 `wiki_suggest_categories()`로 제안해줍니다.

---

## Scenario 2: 기존 Markdown 사용자 - 마이그레이션

이미 사용 중인 노트 디렉토리에 검색 기능을 부착합니다.

```bash
# 1. 설치
pipx install wiki-search-mcp

# 2. 기존 디렉토리를 그대로 등록
wiki-search-mcp config ~/my-existing-notes

# 3. (선택) 사전 인덱싱
wiki-search-mcp index ~/my-existing-notes --full

# 4. Claude Desktop 재시작
```

### Compatibility Notes

- **frontmatter 없는 문서**: 파일명이 title, `uncategorized` 카테고리로 자동 분류
- **기존 구조 유지**: `.vectordb/` 폴더만 추가됨 (삭제해도 원본 영향 없음)
- **카테고리**: wiki 루트(또는 `pages/`) 하위 디렉토리가 자동으로 카테고리가 됩니다

---

## Scenario 3: Obsidian Vault

Obsidian Vault를 그대로 가리킬 수 있습니다.

```bash
pipx install wiki-search-mcp
wiki-search-mcp config ~/Obsidian/MyVault
```

`.obsidian/`, `.trash/` 등 점(`.`)으로 시작하는 디렉토리는 자동으로 무시됩니다.

---

## Scenario 4: 개발자 - Local Development

MCP 서버를 수정하거나 기여하려는 경우입니다.

```bash
# 1. 저장소 클론
git clone https://github.com/jin7942/wiki-search-mcp.git
cd wiki-search-mcp

# 2. 개발 의존성 포함 설치
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. 테스트 실행
pytest tests/ -v

# 4. MCP 서버 직접 실행 (디버깅용)
wiki-search-mcp serve ~/my-notes --log-level DEBUG
```

---

## 무시 패턴 / Ignore Patterns

설정 파일은 없습니다. 다음 3가지로 무시 대상이 결정됩니다.

1. **dot-prefix 자동**: `.git`, `.obsidian`, `.vectordb`, `.DS_Store` 등 모든 dotfile/dotdir
2. **`.gitignore` 자동**: 루트의 `.gitignore`가 있으면 패턴 적용
   ```bash
   # 예: ~/my-notes/.gitignore
   draft/
   *.bak
   private/
   ```
3. **`--ignore` CLI 옵션** (반복 가능):
   ```bash
   wiki-search-mcp serve ~/my-notes --ignore "scratch" --ignore "*.tmp"
   ```

---

## 권장 디렉토리 구조 (선택)

zero-config라 강제는 없지만, 다음과 같은 구조를 만들면 카테고리 자동 감지가 잘 동작합니다.

```
~/my-notes/
├── infra/         # 카테고리 "infra"
│   └── nginx-ssl.md
├── projects/      # 카테고리 "projects"
│   └── alpha.md
├── personal/      # 카테고리 "personal"
└── inbox/         # 카테고리 "inbox" (정리 전 임시 저장소)
```

빈 디렉토리에서 시작해도 무방합니다. Claude가 메모를 정리하면서 자연스럽게 카테고리가 생깁니다.
