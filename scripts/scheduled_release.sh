#!/usr/bin/env bash
# 예약 릴리즈 스크립트 (v0.6.0)
#
# KST 18:30 (= UTC 09:30) 에 systemd-run 타이머로 실행된다.
# 자기완결: 안전 검사 → CHANGELOG 확정 → 커밋 → 태그 → 푸시.
# CI(release.yml + publish.yml)가 태그 push 를 받아 GitHub Release 생성 +
# PyPI 배포를 자동 수행한다(v0.5.0 과 동일 흐름).
#
# 실패 시 즉시 중단(set -e). 어느 단계든 실패하면 태그/푸시를 진행하지 않는다.

set -euo pipefail

REPO="/factory/wiki-search-mcp"
VERSION="0.6.0"
TAG="v${VERSION}"
TODAY="$(date -u +%Y-%m-%d)"
LOG="${REPO}/.claude-log/release-${TAG}.log"

cd "$REPO"

{
  echo "===== scheduled release ${TAG} ====="
  echo "started: $(date -u '+%Y-%m-%d %H:%M:%S %z')"

  # --- 0. 이미 릴리즈됐으면 중단(중복 실행 방지) ---
  if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "ABORT: tag ${TAG} already exists"
    exit 1
  fi

  # --- 1. 브랜치 확인 ---
  BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  echo "branch: ${BRANCH}"
  if [ "$BRANCH" != "main" ]; then
    echo "ABORT: not on main (on ${BRANCH})"
    exit 1
  fi

  # --- 2. 전체 테스트 통과 확인(실패 시 릴리즈 중단) ---
  echo "--- running test suite ---"
  ./.venv/bin/pytest -q
  echo "tests passed"

  # --- 3. CHANGELOG: [Unreleased] -> [0.6.0] - DATE 확정 ---
  if grep -q "## \[Unreleased\]" CHANGELOG.md; then
    sed -i "s/## \[Unreleased\]/## [${VERSION}] - ${TODAY}/" CHANGELOG.md
    echo "CHANGELOG: Unreleased -> ${VERSION} (${TODAY})"
  else
    echo "WARN: [Unreleased] section not found; CHANGELOG left as-is"
  fi

  # --- 4. 변경사항 스테이징 + 커밋 ---
  git add -A
  if git diff --cached --quiet; then
    echo "WARN: nothing to commit"
  else
    git commit -m "$(cat <<EOF
feat: 구조 진단/제안 도구 4종 + 분류 닭-달걀 해소 (${VERSION})

개선보고서 8개 갭 처리. read-only 제안 도구 추가:
- wiki_suggest_subfolders / wiki_health_check
- wiki_suggest_filename_normalization
- get_similar 본문 임베딩 fallback (미인덱싱 분류 신호 확보)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
    echo "committed"
  fi

  # --- 5. 태그 + 푸시(커밋 먼저, 그다음 태그) ---
  git tag -a "$TAG" -m "Release ${TAG}"
  echo "tagged ${TAG}"

  git push origin main
  echo "pushed main"
  git push origin "$TAG"
  echo "pushed ${TAG} — CI will create GitHub Release + publish to PyPI"

  echo "finished: $(date -u '+%Y-%m-%d %H:%M:%S %z')"
  echo "===== done ====="
} >> "$LOG" 2>&1
