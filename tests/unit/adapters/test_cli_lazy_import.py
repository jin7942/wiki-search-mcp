"""CLI 진입 시 무거운 ML 의존성이 로드되지 않는지 보장."""

from __future__ import annotations

import subprocess
import sys


def _modules_loaded_after_cli_import() -> set[str]:
    """별도 파이썬 프로세스에서 CLI 모듈만 import 후 적재된 모듈 집합 반환.

    같은 프로세스에서 측정하면 다른 테스트가 미리 로드한 모듈이 섞이므로
    subprocess로 격리해야 정확하다.
    """
    code = (
        "import sys, json\n"
        "import wiki_search_mcp.adapters.cli.main  # noqa: F401\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    out = subprocess.check_output([sys.executable, "-c", code], text=True)
    import json as _json

    return set(_json.loads(out))


def test_cli_import_does_not_load_torch_or_sentence_transformers() -> None:
    """``--version`` / ``--help`` 같은 경량 명령이 즉시 동작하려면
    CLI 모듈 진입 시점에 torch / sentence_transformers / lancedb 같은
    무거운 ML 의존성이 로드되지 않아야 한다.
    """
    loaded = _modules_loaded_after_cli_import()
    forbidden = {
        "torch",
        "sentence_transformers",
        "lancedb",
        "transformers",
    }
    leaked = forbidden & loaded
    assert not leaked, f"무거운 ML 모듈이 CLI 진입 시 로드됨: {sorted(leaked)}"


def test_cli_import_does_not_eagerly_load_indexer() -> None:
    """WikiIndexer는 lazy attribute여야 한다 (PEP 562)."""
    loaded = _modules_loaded_after_cli_import()
    assert "wiki_search_mcp.infrastructure.indexing.indexer" not in loaded
