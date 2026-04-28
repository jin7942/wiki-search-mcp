# wiki-search-mcp 데모 GIF 녹화용 컨테이너
#
# 베이스: charmbracelet/vhs 공식 이미지 (vhs + ttyd + ffmpeg 포함)
# 추가:   한글 폰트 (Noto CJK) + wiki-search-mcp + 시연 데이터 + 임베딩 모델 캐시
#
# 빌드:
#   docker build -t wsm-vhs:local -f tests/integration/Dockerfile.vhs .
#
# 실행 (record_demo.sh가 자동 처리):
#   docker run --rm -v $PWD/docs/demo.tape:/work/demo.tape:ro \
#                   -v $PWD/docs/assets:/out wsm-vhs:local \
#                   vhs /work/demo.tape

FROM ghcr.io/charmbracelet/vhs:latest

USER root

# 한글 monospace 폰트 + Python + 빌드 도구
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-noto-cjk \
        fonts-noto-cjk-extra \
        python3 \
        python3-venv \
        python3-pip \
        ca-certificates \
        git \
        unzip \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# wiki-search-mcp 설치 (로컬 소스 우선; ARG로 PyPI 토글 가능)
ARG INSTALL_FROM=local
COPY . /src
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && if [ "$INSTALL_FROM" = "pypi" ]; then \
           /opt/venv/bin/pip install wiki-search-mcp ; \
       else \
           /opt/venv/bin/pip install /src ; \
       fi
ENV PATH="/opt/venv/bin:$PATH"

# 시연용 데이터 미리 생성
# - Notes/, Projects/ 두 카테고리
# - frontmatter 있는 .md 2개 + 미분류 draft.md 1개
RUN mkdir -p /root/demo-notes/Notes /root/demo-notes/Projects \
    && printf '%s\n' \
       '---' \
       'title: Memo' \
       'category: Notes' \
       'tags: [test]' \
       '---' \
       '# Memo' \
       '간단한 메모 본문.' \
       > /root/demo-notes/Notes/memo.md \
    && printf '%s\n' \
       '---' \
       'title: Alpha Project' \
       'category: Projects' \
       'tags: [project]' \
       '---' \
       '# Alpha' \
       '프로젝트 메모 본문.' \
       > /root/demo-notes/Projects/alpha.md \
    && printf '%s\n' \
       '# Draft' \
       'frontmatter 없는 미분류 파일.' \
       > /root/demo-notes/Notes/draft.md

# 임베딩 모델 사전 다운로드
# 시연 GIF에 'Loading weights: ...' 진행률이 노출되지 않도록 빌드 시점에 캐싱.
RUN python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('jhgan/ko-sroberta-multitask')"

WORKDIR /work
