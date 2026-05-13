"""RollbackService — applied.jsonl의 마지막 N개 변경을 역재생.

각 entry는 ``AppliedRecord.to_dict()`` 형식이며, ``frontmatter_before``와 ``path_before``로
원복한다. 본문은 적용 후 사용자가 수정했을 수 있으므로 그대로 유지하고
frontmatter만 ``frontmatter_before``로 교체.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from wiki_search_mcp.infrastructure.frontmatter.writer import FrontmatterWriter
from wiki_search_mcp.infrastructure.jsonl.log import JsonlLog

logger = logging.getLogger(__name__)


class RollbackService:
    def __init__(self, *, applied_log: JsonlLog, pages_path: Path):
        self._applied = applied_log
        self._writer = FrontmatterWriter(pages_path)

    def rollback_last(self, n: int, *, dry_run: bool = False) -> list[dict[str, Any]]:
        """마지막 ``n``개 적용을 역순으로 되돌림.

        Returns:
            처리 결과 리스트. 각 항목 ``{path_after, path_before, status}``.
            status는 ``"would_restore"`` | ``"restored"`` | ``"skipped"``.
        """
        if n <= 0:
            return []
        entries = self._applied.tail(n)
        results: list[dict[str, Any]] = []
        for entry in reversed(entries):
            path_after = entry.get("path_after")
            path_before = entry.get("path_before")
            fm_before = entry.get("frontmatter_before") or {}
            if not isinstance(path_after, str) or not isinstance(path_before, str):
                results.append({"path_after": path_after, "status": "skipped", "reason": "invalid_entry"})
                continue
            if dry_run:
                results.append(
                    {"path_after": path_after, "path_before": path_before, "status": "would_restore"}
                )
                continue
            try:
                self._writer.restore(path_after, path_before, fm_before)
                results.append(
                    {"path_after": path_after, "path_before": path_before, "status": "restored"}
                )
                logger.info("rolled back %s -> %s", path_after, path_before)
            except FileNotFoundError:
                results.append(
                    {"path_after": path_after, "path_before": path_before, "status": "skipped", "reason": "file_missing"}
                )
            except OSError as e:
                results.append(
                    {
                        "path_after": path_after,
                        "path_before": path_before,
                        "status": "skipped",
                        "reason": f"os_error: {e}",
                    }
                )
        return results
