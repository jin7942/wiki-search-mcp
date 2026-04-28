#!/usr/bin/env bash
#
# wiki-search-mcp 데모 GIF 녹화 진입점
#
# 호스트 의존: docker만 필요 (vhs/ttyd/ffmpeg는 컨테이너 안에서 처리)
#
# 사용법:
#   bash tests/integration/record_demo.sh
#
# 옵션:
#   INSTALL_FROM=pypi bash tests/integration/record_demo.sh   # PyPI에서 설치
#

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TAPE="$PROJECT_ROOT/docs/demo.tape"
OUT_DIR="$PROJECT_ROOT/docs/assets"
IMAGE="wsm-vhs:local"

if [ ! -f "$TAPE" ]; then
    echo "ERROR: $TAPE not found" >&2
    exit 1
fi

mkdir -p "$OUT_DIR"

echo "▶ Building vhs image (한글 폰트 + 임베딩 모델 캐싱 포함)"
echo "  첫 빌드는 5-10분 소요 (vhs base + apt + pip + 모델 ~400MB 다운로드)"
echo "  두 번째부터는 Docker 캐시로 1-2분"
docker build \
    -t "$IMAGE" \
    -f "$PROJECT_ROOT/tests/integration/Dockerfile.vhs" \
    --build-arg INSTALL_FROM="${INSTALL_FROM:-local}" \
    "$PROJECT_ROOT"

echo ""
echo "▶ Recording demo.gif (~25초)"
# 공식 vhs 이미지의 ENTRYPOINT가 이미 'vhs'이므로 인자만 전달
docker run --rm \
    -v "$TAPE":/work/demo.tape:ro \
    -v "$OUT_DIR":/out \
    "$IMAGE" \
    /work/demo.tape

echo ""
echo "✔ GIF 생성 완료: $OUT_DIR/demo.gif"
ls -lh "$OUT_DIR/demo.gif"

# 5MB 가드
SIZE=$(stat -c%s "$OUT_DIR/demo.gif")
LIMIT=$((5 * 1024 * 1024))
if [ "$SIZE" -gt "$LIMIT" ]; then
    echo ""
    echo "⚠ 경고: demo.gif 크기 $SIZE bytes > 5MB"
    echo "  GitHub 로딩 속도와 저장소 부담을 위해 줄이는 것 권장."
    echo "  방법:"
    echo "    1) docs/demo.tape의 Width/Height 축소"
    echo "    2) FontSize 축소 (16 → 14)"
    echo "    3) TypingSpeed 증가 (50ms → 80ms)"
    echo "    4) Sleep 감소"
fi
