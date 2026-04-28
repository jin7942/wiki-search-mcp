# wiki-search-mcp 데모 GIF 스크립트
#
# 실행: tests/integration/record_demo.sh가 Docker 컨테이너 안에서 vhs로 처리.
# 결과: docs/assets/demo.gif (호스트로 자동 마운트됨)
#
# 시연 흐름 (~25초):
#   1. config 명령 (zero-config 진입)
#   2. claude_desktop_config.json 출력 (env 없음, args에 path)
#   3. ls로 카테고리(폴더) 구조 확인
#   4. index --full로 자동 인덱싱

Output "/out/demo.gif"

Set Shell "bash"
Set Width 1100
Set Height 700
Set FontSize 16
Set Padding 20
Set Theme "Dracula"
Set FontFamily "Noto Sans Mono CJK KR"
Set TypingSpeed 50ms

Hide
Type "clear" Enter
Show

# 1. zero-config 진입
Type "wiki-search-mcp config ~/demo-notes" Enter
Sleep 3s

# 2. 생성된 args 확인 (env 섹션 없음)
Type "cat /root/.claude/claude_desktop_config.json" Enter
Sleep 3s

# 3. 폴더 구조 (카테고리)
Type "ls ~/demo-notes" Enter
Sleep 1500ms

# 4. 자동 인덱싱 (모델 사전 캐싱으로 빠름)
Type "wiki-search-mcp index ~/demo-notes --full" Enter
Sleep 8s

Sleep 2s
