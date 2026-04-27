"""CLI 명령어 테스트.

config, index 명령어를 테스트합니다. ``init`` 명령은 zero-config
전환에 따라 제거되었습니다.
"""

import json
import tempfile
from pathlib import Path

from click.testing import CliRunner


class TestInitCommandRemoved:
    """init 명령은 더 이상 존재하지 않음을 검증."""

    def test_init_command_not_registered(self):
        from wiki_search_mcp.adapters.cli.main import main

        runner = CliRunner()
        result = runner.invoke(main, ["init", "./somewhere"])
        # Click이 알 수 없는 명령으로 처리 → exit code != 0
        assert result.exit_code != 0


class TestConfigCommand:
    """config 명령어 테스트."""

    def test_config_creates_mcp_config(self):
        """MCP 설정 생성."""
        from wiki_search_mcp.adapters.cli.main import main

        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            # wiki 디렉토리 생성
            wiki_path = Path(tmpdir) / "wiki"
            wiki_path.mkdir()

            # 설정 파일 경로
            config_file = Path(tmpdir) / "claude_config.json"

            result = runner.invoke(
                main,
                ["config", str(wiki_path), "--config-path", str(config_file)],
            )

            assert result.exit_code == 0
            assert config_file.exists()

            # 설정 내용 확인
            config_data = json.loads(config_file.read_text())
            assert "mcpServers" in config_data
            assert "wiki-search" in config_data["mcpServers"]
            # macOS에서 /var -> /private/var 심볼릭 링크 고려
            saved_path = config_data["mcpServers"]["wiki-search"]["env"]["WIKI_PATH"]
            assert saved_path.endswith("/wiki")
            assert "wiki" in saved_path


class TestIndexCommand:
    """index 명령어 테스트."""

    def test_index_without_pages_shows_warning(self):
        """pages 디렉토리 없으면 경고 표시 (에러 아님)."""
        from wiki_search_mcp.adapters.cli.main import main

        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            # pages 없는 wiki 디렉토리
            wiki_path = Path(tmpdir) / "wiki"
            wiki_path.mkdir()

            result = runner.invoke(main, ["index", str(wiki_path)])

            # pages 없어도 성공 (경고만 표시)
            assert result.exit_code == 0
            # .md 파일 없으면 경고 메시지
            assert "경고" in result.output or ".md" in result.output

    def test_index_without_pages_with_md(self):
        """pages 없지만 .md 있으면 정상 인덱싱."""
        from wiki_search_mcp.adapters.cli.main import main

        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir) / "wiki"
            wiki_path.mkdir()
            # 루트에 직접 .md 파일 생성
            (wiki_path / "test.md").write_text("# Test")

            result = runner.invoke(main, ["index", str(wiki_path)])

            assert result.exit_code == 0
            assert "pages/ 없음" in result.output or "루트로 사용" in result.output
