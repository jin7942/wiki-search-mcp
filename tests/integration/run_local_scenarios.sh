#!/usr/bin/env bash
#
# Zero-Config 사용자 시나리오 - 로컬 격리 검증 (B안)
#
# 임시 venv + tmpdir로 빠른 회귀 검증을 수행합니다.
# 호스트 Python에 영향 없이 격리된 환경에서 실행됩니다.
#
# 사용법:
#   bash tests/integration/run_local_scenarios.sh
#
# 종료 코드:
#   0: 모든 시나리오 PASS
#   1: 하나 이상 FAIL
#

set -u  # set -e는 에러 트랩 제어를 위해 사용 안 함

# ──────────────────────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_DIR="$(mktemp -d -t wsm-integration-XXXXXX)"
VENV_DIR="$WORK_DIR/venv"
LOG_FILE="$WORK_DIR/test.log"

PASS=0
FAIL=0
FAILURES=()

# 색상 (TTY일 때만)
if [[ -t 1 ]]; then
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    YELLOW='\033[1;33m'
    NC='\033[0m'
else
    GREEN=''
    RED=''
    YELLOW=''
    NC=''
fi

# ──────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────
log() {
    echo "$@" | tee -a "$LOG_FILE"
}

run_step() {
    local name="$1"
    shift
    log ""
    log "▶ $name"
    if "$@" >>"$LOG_FILE" 2>&1; then
        log "  ${GREEN}OK${NC}"
        return 0
    else
        log "  ${RED}FAIL${NC} (see $LOG_FILE)"
        return 1
    fi
}

assert() {
    local description="$1"
    local condition="$2"
    if eval "$condition"; then
        log "  ${GREEN}PASS${NC}: $description"
        PASS=$((PASS + 1))
    else
        log "  ${RED}FAIL${NC}: $description"
        log "       (condition: $condition)"
        FAIL=$((FAIL + 1))
        FAILURES+=("$description")
    fi
}

cleanup() {
    log ""
    log "Cleaning up: $WORK_DIR"
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT

# ──────────────────────────────────────────────────────────────
# 0. venv 격리 환경 준비
# ──────────────────────────────────────────────────────────────
log "════════════════════════════════════════════"
log "wiki-search-mcp Zero-Config 시나리오 테스트"
log "════════════════════════════════════════════"
log "Project: $PROJECT_ROOT"
log "Work:    $WORK_DIR"

if ! python3 -m venv "$VENV_DIR" >>"$LOG_FILE" 2>&1; then
    log "${RED}venv 생성 실패. python3-venv 패키지가 필요합니다.${NC}"
    exit 1
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

log ""
log "▶ pip install (격리 venv에 설치)"
if pip install --quiet --upgrade pip >>"$LOG_FILE" 2>&1 \
    && pip install --quiet "$PROJECT_ROOT" >>"$LOG_FILE" 2>&1; then
    log "  ${GREEN}OK${NC}"
else
    log "  ${RED}FAIL${NC} (see $LOG_FILE)"
    exit 1
fi

# ──────────────────────────────────────────────────────────────
# 시나리오 1: 빈 디렉토리 + config
# ──────────────────────────────────────────────────────────────
log ""
log "── 시나리오 1: 빈 디렉토리 + config ──"
EMPTY_DIR="$WORK_DIR/empty-notes"
mkdir -p "$EMPTY_DIR"
CONFIG_FILE="$WORK_DIR/claude_config.json"

run_step "config 명령 실행" \
    wiki-search-mcp config "$EMPTY_DIR" --config-path "$CONFIG_FILE"

assert "config 파일 생성됨" "[[ -f '$CONFIG_FILE' ]]"
assert "wiki-search 서버 등록됨" \
    "grep -q 'wiki-search' '$CONFIG_FILE'"
assert "WIKI_PATH 정확함" \
    "grep -q '\"WIKI_PATH\"' '$CONFIG_FILE' && grep -q '$EMPTY_DIR' '$CONFIG_FILE'"

# ──────────────────────────────────────────────────────────────
# 시나리오 2: 폴더 구조 + index
# ──────────────────────────────────────────────────────────────
log ""
log "── 시나리오 2: 폴더 구조 + index ──"
FOLDER_DIR="$WORK_DIR/folder-notes"
mkdir -p "$FOLDER_DIR/Notes" "$FOLDER_DIR/Projects"
cat > "$FOLDER_DIR/Notes/memo.md" <<'MD'
---
title: Memo
category: Notes
tags: [test]
---
# Memo
content body
MD
cat > "$FOLDER_DIR/Projects/alpha.md" <<'MD'
---
title: Alpha
category: Projects
tags: [project]
---
# Alpha
content body
MD
# 미분류 파일
echo "# Draft" > "$FOLDER_DIR/Notes/draft.md"

run_step "전체 인덱싱" \
    wiki-search-mcp index "$FOLDER_DIR" --full

assert ".vectordb 디렉토리 생성됨" \
    "[[ -d '$FOLDER_DIR/.vectordb' ]]"

# ──────────────────────────────────────────────────────────────
# 시나리오 3: wiki_get_categories
# ──────────────────────────────────────────────────────────────
log ""
log "── 시나리오 3: wiki_get_categories ──"
CAT_OUT="$WORK_DIR/categories.json"
WIKI_PATH="$FOLDER_DIR" python -c "
from wiki_search_mcp.adapters.mcp.container import ServiceContainer
from wiki_search_mcp.adapters.mcp.handlers import handle_wiki_get_categories
c = ServiceContainer('$FOLDER_DIR')
print(handle_wiki_get_categories(c))
" > "$CAT_OUT" 2>>"$LOG_FILE"

assert "wiki_get_categories 응답 생성됨" "[[ -s '$CAT_OUT' ]]"
assert "mode=folder 반환" \
    "grep -q '\"mode\": \"folder\"' '$CAT_OUT'"
assert "Notes 카테고리 포함" \
    "grep -q '\"Notes\"' '$CAT_OUT'"
assert "Projects 카테고리 포함" \
    "grep -q '\"Projects\"' '$CAT_OUT'"

# ──────────────────────────────────────────────────────────────
# 시나리오 4: wiki_pending
# ──────────────────────────────────────────────────────────────
log ""
log "── 시나리오 4: wiki_pending ──"
PENDING_OUT="$WORK_DIR/pending.json"
WIKI_PATH="$FOLDER_DIR" python -c "
from wiki_search_mcp.adapters.mcp.container import ServiceContainer
from wiki_search_mcp.adapters.mcp.handlers import handle_wiki_pending
c = ServiceContainer('$FOLDER_DIR')
print(handle_wiki_pending(c, limit=20))
" > "$PENDING_OUT" 2>>"$LOG_FILE"

assert "wiki_pending 응답 생성됨" "[[ -s '$PENDING_OUT' ]]"
assert "items 키 존재" "grep -q '\"items\"' '$PENDING_OUT'"
assert "draft.md 감지됨 (frontmatter 없음)" \
    "grep -q 'draft.md' '$PENDING_OUT'"

# ──────────────────────────────────────────────────────────────
# 시나리오 5: wiki_suggest_classification
# ──────────────────────────────────────────────────────────────
log ""
log "── 시나리오 5: wiki_suggest_classification ──"
SUGGEST_OUT="$WORK_DIR/suggest.json"
WIKI_PATH="$FOLDER_DIR" python -c "
from wiki_search_mcp.adapters.mcp.container import ServiceContainer
from wiki_search_mcp.adapters.mcp.handlers import handle_wiki_suggest_classification
c = ServiceContainer('$FOLDER_DIR')
print(handle_wiki_suggest_classification(c, path='Notes/draft.md'))
" > "$SUGGEST_OUT" 2>>"$LOG_FILE"

assert "suggest 응답 생성됨" "[[ -s '$SUGGEST_OUT' ]]"
assert "category_candidates 키 존재" \
    "grep -q '\"category_candidates\"' '$SUGGEST_OUT'"
assert "Notes 카테고리 추천 (폴더 기반)" \
    "grep -q '\"Notes\"' '$SUGGEST_OUT'"
assert "tag_candidates 키 존재" \
    "grep -q '\"tag_candidates\"' '$SUGGEST_OUT'"
assert "reasoning 키 존재" \
    "grep -q '\"reasoning\"' '$SUGGEST_OUT'"

# ──────────────────────────────────────────────────────────────
# 시나리오 6: .gitignore 자동 무시
# ──────────────────────────────────────────────────────────────
log ""
log "── 시나리오 6: .gitignore 자동 무시 ──"
GIT_DIR="$WORK_DIR/git-notes"
mkdir -p "$GIT_DIR/Notes" "$GIT_DIR/draft"
echo "draft/" > "$GIT_DIR/.gitignore"
echo "# OK" > "$GIT_DIR/Notes/ok.md"
echo "# Draft" > "$GIT_DIR/draft/wip.md"
mkdir -p "$GIT_DIR/Projects"
echo "# Proj" > "$GIT_DIR/Projects/p.md"

run_step "전체 인덱싱 (.gitignore 적용)" \
    wiki-search-mcp index "$GIT_DIR" --full

# lancedb 직접 조회 (LanceVectorStore 캐시 race 회피)
python << PY > "$WORK_DIR/indexed.json" 2>>"$LOG_FILE"
import lancedb, json
db = lancedb.connect("$GIT_DIR/.vectordb")
# list_tables()는 버전에 따라 객체 또는 list 반환 → list()로 정규화
table_names = []
try:
    table_names = list(db.table_names())
except Exception:
    try:
        table_names = list(db.list_tables())
    except Exception:
        pass
rows = []
if "wiki" in table_names:
    rows = db.open_table("wiki").to_arrow().to_pylist()
print(json.dumps({"paths": [r.get("path") for r in rows]}))
PY

assert "ok.md 인덱싱됨" \
    "grep -q 'ok.md' '$WORK_DIR/indexed.json'"
assert "draft/wip.md는 무시됨" \
    "! grep -q 'wip.md' '$WORK_DIR/indexed.json'"

# ──────────────────────────────────────────────────────────────
# 시나리오 7: WIKI_IGNORE 환경변수
# ──────────────────────────────────────────────────────────────
log ""
log "── 시나리오 7: WIKI_IGNORE 환경변수 ──"
ENV_DIR="$WORK_DIR/env-notes"
mkdir -p "$ENV_DIR/Notes" "$ENV_DIR/scratch"
mkdir -p "$ENV_DIR/Projects"
echo "# Keep" > "$ENV_DIR/Notes/keep.md"
echo "# Tmp" > "$ENV_DIR/scratch/tmp.md"
echo "# P" > "$ENV_DIR/Projects/p.md"

WIKI_IGNORE="scratch" wiki-search-mcp index "$ENV_DIR" --full >>"$LOG_FILE" 2>&1

# lancedb 직접 조회
python << PY > "$WORK_DIR/env-indexed.json" 2>>"$LOG_FILE"
import lancedb, json
db = lancedb.connect("$ENV_DIR/.vectordb")
table_names = []
try:
    table_names = list(db.table_names())
except Exception:
    try:
        table_names = list(db.list_tables())
    except Exception:
        pass
rows = []
if "wiki" in table_names:
    rows = db.open_table("wiki").to_arrow().to_pylist()
print(json.dumps({"paths": [r.get("path") for r in rows]}))
PY

assert "keep.md 인덱싱됨" \
    "grep -q 'keep.md' '$WORK_DIR/env-indexed.json'"
assert "scratch/tmp.md는 WIKI_IGNORE로 무시됨" \
    "! grep -q 'tmp.md' '$WORK_DIR/env-indexed.json'"

# ──────────────────────────────────────────────────────────────
# 시나리오 8: init 명령 부재
# ──────────────────────────────────────────────────────────────
log ""
log "── 시나리오 8: init 명령 부재 ──"
INIT_OUT="$WORK_DIR/init-out.txt"
wiki-search-mcp init /tmp/should-not-work >"$INIT_OUT" 2>&1
INIT_EXIT=$?

assert "init 명령 실행 실패 (exit != 0)" "[[ $INIT_EXIT -ne 0 ]]"
assert "Unknown command 또는 No such command 메시지" \
    "grep -qiE 'no such command|unknown command|usage' '$INIT_OUT'"

# wiki-template 디렉토리가 패키지에 없음
PKG_DIR="$(python -c 'import wiki_search_mcp, os; print(os.path.dirname(wiki_search_mcp.__file__))')"
assert "패키지에 wiki-template 디렉토리 없음" \
    "[[ ! -d '$PKG_DIR/wiki-template' ]]"

# ──────────────────────────────────────────────────────────────
# 결과 요약
# ──────────────────────────────────────────────────────────────
log ""
log "════════════════════════════════════════════"
log "결과: ${GREEN}PASS=$PASS${NC}, ${RED}FAIL=$FAIL${NC}"

if [[ $FAIL -gt 0 ]]; then
    log ""
    log "${RED}실패한 검증:${NC}"
    for f in "${FAILURES[@]}"; do
        log "  - $f"
    done
    log ""
    log "전체 로그: $LOG_FILE"
    exit 1
fi

log ""
log "${GREEN}모든 시나리오 PASS${NC}"
log "전체 로그: $LOG_FILE"
exit 0
