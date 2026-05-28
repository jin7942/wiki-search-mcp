"""OS 서비스 유닛 생성 — daemon 자동 재기동을 OS 에 위임.

daemon 프로세스가 죽었을 때 자동 재기동하는 책임을 OS 의 service manager 에 맡긴다.
- macOS: launchd LaunchAgent (``~/Library/LaunchAgents/``), ``KeepAlive`` 로 재기동.
- Linux: systemd user service (``~/.config/systemd/user/``), ``Restart=always``.

유닛은 ``<cli> daemon start <wiki> --foreground`` 를 실행한다 (OS 가 supervisor 이므로
daemon 자신은 포그라운드로 떠야 한다). vault 경로 해시로 유닛 이름을 격리해 여러 vault
를 동시에 등록할 수 있다.

이 모듈은 **순수 텍스트 생성 + 경로 계산**만 담당한다 (테스트 가능). 실제 ``launchctl`` /
``systemctl`` 호출은 CLI 계층에서 수행한다.
"""

from __future__ import annotations

import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from wiki_search_mcp.infrastructure.daemon.paths import _hash_wiki_path

# 유닛 이름 prefix — vault 해시를 붙여 인스턴스를 격리한다.
_LABEL_PREFIX = "com.wiki-search-mcp"


def resolve_cli_path() -> str:
    """현재 환경의 ``wiki-search-mcp`` 실행 경로를 반환.

    pipx venv 격리 환경에서도 동작하도록 콘솔 스크립트 절대경로를 우선 사용한다.
    못 찾으면 ``<python> -m wiki_search_mcp.adapters.cli.main`` 형태로 폴백한다.

    Returns:
        실행 가능한 명령 문자열 (공백으로 split 가능한 형태).
    """
    cli = shutil.which("wiki-search-mcp")
    if cli:
        return cli
    # 폴백: 현재 인터프리터로 모듈 실행
    return f"{sys.executable} -m wiki_search_mcp.adapters.cli.main"


def _program_arguments(cli: str, wiki_path: Path) -> list[str]:
    """유닛이 실행할 argv 리스트.

    ``cli`` 가 공백을 포함하면(폴백 형태) split 한다.
    """
    parts = cli.split()
    return [*parts, "daemon", "start", str(wiki_path), "--foreground"]


@dataclass(frozen=True)
class ServiceUnit:
    """생성될 유닛의 메타데이터."""

    label: str  # launchd Label / systemd 서비스 이름 (확장자 제외)
    unit_path: Path  # 유닛 파일 경로
    content: str  # 유닛 파일 내용
    kind: str  # "launchd" | "systemd"


def _label_for(wiki_path: Path) -> str:
    return f"{_LABEL_PREFIX}.{_hash_wiki_path(wiki_path)}"


def build_launchd_unit(wiki_path: Path, cli: str, log_path: Path) -> ServiceUnit:
    """macOS launchd LaunchAgent plist 생성."""
    label = _label_for(wiki_path)
    unit_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    argv = _program_arguments(cli, wiki_path)
    args_xml = "\n".join(f"        <string>{a}</string>" for a in argv)
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>{wiki_path}</string>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
</dict>
</plist>
"""
    return ServiceUnit(label=label, unit_path=unit_path, content=content, kind="launchd")


def build_systemd_unit(wiki_path: Path, cli: str, log_path: Path) -> ServiceUnit:
    """Linux systemd user service 생성."""
    label = _label_for(wiki_path)
    unit_path = Path.home() / ".config" / "systemd" / "user" / f"{label}.service"
    argv = _program_arguments(cli, wiki_path)
    exec_start = " ".join(argv)
    content = f"""[Unit]
Description=wiki-search-mcp auto-classify daemon ({wiki_path})
After=network.target

[Service]
Type=simple
ExecStart={exec_start}
WorkingDirectory={wiki_path}
StandardOutput=append:{log_path}
StandardError=append:{log_path}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
    return ServiceUnit(label=label, unit_path=unit_path, content=content, kind="systemd")


def build_unit(wiki_path: Path, cli: str, log_path: Path) -> ServiceUnit:
    """현재 OS 에 맞는 유닛을 생성.

    Raises:
        RuntimeError: 지원하지 않는 OS (Windows 등).
    """
    system = platform.system()
    if system == "Darwin":
        return build_launchd_unit(wiki_path, cli, log_path)
    if system == "Linux":
        return build_systemd_unit(wiki_path, cli, log_path)
    raise RuntimeError(
        f"자동 재기동 유닛은 macOS/Linux 만 지원합니다 (현재: {system}). "
        "daemon start 를 수동으로 사용하세요."
    )


__all__ = [
    "ServiceUnit",
    "build_launchd_unit",
    "build_systemd_unit",
    "build_unit",
    "resolve_cli_path",
]
