# wiki-search-mcp 데모 GIF 스크립트
#
# 실행: tests/integration/record_demo.sh가 Docker 컨테이너 안에서 vhs로 처리.
# 결과: docs/assets/demo.gif (호스트로 자동 마운트됨)
#
# 시연 흐름 (~45초):
#   Part 1 (~15초): 설정 + 인덱싱
#     1. config 명령 (zero-config 진입)
#     2. ls로 카테고리 확인
#     3. index --full로 자동 인덱싱
#   Part 2 (~30초): 실제 검색 (MCP 핸들러 직접 호출)
#     4. wiki_search("SSL 인증서")  → 실제 응답
#     5. wiki_get_categories()       → 카테고리 자동 감지

Output "/out/demo.gif"

Set Shell "bash"
Set Width 1000
Set Height 620
Set FontSize 14
Set Padding 20
Set Theme "Dracula"
Set FontFamily "Noto Sans Mono CJK KR"
Set TypingSpeed 40ms

Hide
Type "clear" Enter
Show

# ─── Part 1: 설정 + 인덱싱 ───

Type "wiki-search-mcp config ~/demo-notes" Enter
Sleep 2500ms

Type "ls ~/demo-notes" Enter
Sleep 1500ms

Type "wiki-search-mcp index ~/demo-notes --full" Enter
Sleep 5s

# ─── Part 2: 실제 검색 ───

Type "clear" Enter
Sleep 500ms

# 사용자 질문 (시뮬레이션)
Type `echo '👤 SSL 인증서 적용 방법 찾아줘'` Enter
Sleep 1500ms

# 실제 MCP 핸들러 호출 → 진짜 검색 결과
Type `python3 -c "` Enter
Type `from wiki_search_mcp.adapters.mcp.container import ServiceContainer` Enter
Type `from wiki_search_mcp.adapters.mcp.handlers import handle_wiki_search` Enter
Type `c = ServiceContainer('/root/demo-notes')` Enter
Type `print(handle_wiki_search(c, query='SSL 인증서 적용', top_k=3))` Enter
Type `"` Enter
Sleep 6s

# 카테고리 자동 감지 확인
Type "clear" Enter
Sleep 500ms

Type `echo '👤 어떤 카테고리가 있는지 알려줘'` Enter
Sleep 1500ms

Type `python3 -c "` Enter
Type `from wiki_search_mcp.adapters.mcp.container import ServiceContainer` Enter
Type `from wiki_search_mcp.adapters.mcp.handlers import handle_wiki_get_categories` Enter
Type `c = ServiceContainer('/root/demo-notes')` Enter
Type `print(handle_wiki_get_categories(c))` Enter
Type `"` Enter
Sleep 4s

Sleep 1s
