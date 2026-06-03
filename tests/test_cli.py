"""CLI 명령어 테스트.

config, index, serve 명령어를 테스트합니다. ``init`` 명령은 zero-config
전환에 따라 제거되었습니다. 환경변수도 모두 제거되었으며 모든 설정은
CLI 위치 인자/옵션으로 전달됩니다.
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
        """MCP 설정 생성: env 없이 args에 path 직렬화."""
        from wiki_search_mcp.adapters.cli.main import main

        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir) / "wiki"
            wiki_path.mkdir()
            config_file = Path(tmpdir) / "claude_config.json"

            result = runner.invoke(
                main,
                ["config", str(wiki_path), "--config-path", str(config_file)],
            )

            assert result.exit_code == 0, result.output
            assert config_file.exists()

            config_data = json.loads(config_file.read_text())
            server = config_data["mcpServers"]["wiki-search"]

            # 환경변수 사용 안 함
            assert "env" not in server
            # args = ["serve", "/abs/path"]
            assert server["args"][0] == "serve"
            assert server["args"][1].endswith("/wiki")
            assert "wiki" in server["args"][1]
            # 비-기본값 옵션이 없으면 추가 args 없음
            assert len(server["args"]) == 2

    def test_config_serializes_options_to_args(self):
        """추가 옵션은 args에 직렬화."""
        from wiki_search_mcp.adapters.cli.main import main

        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir) / "wiki"
            wiki_path.mkdir()
            config_file = Path(tmpdir) / "claude_config.json"

            result = runner.invoke(
                main,
                [
                    "config",
                    str(wiki_path),
                    "--config-path",
                    str(config_file),
                    "--model",
                    "fast",
                    "--no-watch",
                    "--ignore",
                    "draft",
                    "--ignore",
                    "*.bak",
                    "--debounce",
                    "5.0",
                    "--log-level",
                    "DEBUG",
                ],
            )

            assert result.exit_code == 0, result.output

            config_data = json.loads(config_file.read_text())
            args = config_data["mcpServers"]["wiki-search"]["args"]

            assert args[0] == "serve"
            assert args[1].endswith("/wiki")
            # 옵션 직렬화 검증
            assert "--model" in args
            assert "fast" in args
            assert "--no-watch" in args
            assert args.count("--ignore") == 2
            assert "draft" in args
            assert "*.bak" in args
            assert "--debounce" in args
            assert "5.0" in args
            assert "--log-level" in args
            assert "DEBUG" in args

    def test_config_default_options_not_serialized(self):
        """기본값과 같은 옵션은 args에 포함되지 않음."""
        from wiki_search_mcp.adapters.cli.main import main

        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir) / "wiki"
            wiki_path.mkdir()
            config_file = Path(tmpdir) / "claude_config.json"

            # debounce 2.0(기본), log-level WARNING(기본) 명시 → 직렬화되지 않아야
            result = runner.invoke(
                main,
                [
                    "config",
                    str(wiki_path),
                    "--config-path",
                    str(config_file),
                    "--debounce",
                    "2.0",
                    "--log-level",
                    "WARNING",
                ],
            )

            assert result.exit_code == 0
            args = json.loads(config_file.read_text())["mcpServers"]["wiki-search"][
                "args"
            ]
            assert "--debounce" not in args
            assert "--log-level" not in args


class TestIndexCommand:
    """index 명령어 테스트."""

    def test_index_without_pages_shows_warning(self):
        """pages 디렉토리 없으면 경고 표시 (에러 아님)."""
        from wiki_search_mcp.adapters.cli.main import main

        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir) / "wiki"
            wiki_path.mkdir()

            result = runner.invoke(main, ["index", str(wiki_path)])

            assert result.exit_code == 0
            assert "경고" in result.output or ".md" in result.output

    def test_index_without_pages_with_md(self):
        """pages 없지만 .md 있으면 정상 인덱싱."""
        from wiki_search_mcp.adapters.cli.main import main

        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            wiki_path = Path(tmpdir) / "wiki"
            wiki_path.mkdir()
            (wiki_path / "test.md").write_text("# Test")

            result = runner.invoke(main, ["index", str(wiki_path)])

            assert result.exit_code == 0
            assert "pages/ 없음" in result.output or "루트로 사용" in result.output


class TestServeCommandSignature:
    """serve 명령의 인자/옵션 시그니처 검증.

    실제 MCP 서버를 띄우지 않고, --help로 옵션 노출만 확인합니다.
    """

    def test_serve_requires_wiki_path(self):
        from wiki_search_mcp.adapters.cli.main import main

        runner = CliRunner()
        # 인자 없이 호출 → 에러
        result = runner.invoke(main, ["serve"])
        assert result.exit_code != 0

    def test_serve_help_shows_runtime_options(self):
        from wiki_search_mcp.adapters.cli.main import main

        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        # 모든 런타임 옵션이 노출되어야 함
        assert "--model" in result.output
        assert "--ignore" in result.output
        assert "--no-watch" in result.output
        assert "--debounce" in result.output
        assert "--log-level" in result.output
        assert "--log-file" in result.output


class TestServePathValidation:
    """serve 명령의 vault 경로 검증 (연결 안정성 v0.5.0)."""

    def test_serve_missing_path_clear_message(self, tmp_path):
        """없는 경로면 친절한 안내 후 exit_code != 0 (click 기본 오류 아님)."""
        from wiki_search_mcp.adapters.cli.main import main

        runner = CliRunner()
        missing = str(tmp_path / "no_such_vault")
        result = runner.invoke(main, ["serve", missing])
        assert result.exit_code != 0
        assert "vault 경로를 찾을 수 없습니다" in result.output
        # click 의 기본 거부 메시지가 아니어야 함
        assert "Invalid value for" not in result.output

    def test_serve_file_not_dir(self, tmp_path):
        """경로가 파일이면 디렉토리 아님 안내."""
        from wiki_search_mcp.adapters.cli.main import main

        f = tmp_path / "a_file.md"
        f.write_text("x", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(main, ["serve", str(f)])
        assert result.exit_code != 0
        assert "디렉토리가 아닙니다" in result.output
