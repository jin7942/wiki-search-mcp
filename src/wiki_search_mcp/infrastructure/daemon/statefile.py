"""Daemon 상태 파일 (원자적 JSON read/write).

Daemon은 자신의 상태(``state``, ``started_at``, ``applied_count`` 등)를 이 파일에 기록하고,
MCP 서버 / CLI ``daemon status`` 가 읽어간다. 다중 read와 단일 write가 안전하도록
``os.replace`` 기반 원자 교체를 사용한다.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StatusFile:
    """원자적 JSON 상태 파일 핸들러."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._cache: dict[str, Any] = {}
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> dict[str, Any]:
        """디스크에서 마지막 상태를 읽어 반환. 파일 없거나 파싱 실패 시 ``{}``."""
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def write(self, state: dict[str, Any]) -> None:
        """전체 상태를 원자적으로 덮어쓰기."""
        with self._lock:
            self._cache = dict(state)
            self._flush_locked()

    def update(self, **fields: Any) -> dict[str, Any]:
        """일부 필드만 갱신 + 디스크 쓰기. 갱신 후 dict 반환."""
        with self._lock:
            if not self._cache:
                self._cache = self.read()
            self._cache.update(fields)
            self._flush_locked()
            return dict(self._cache)

    def increment(self, key: str, delta: int = 1, **fields: Any) -> dict[str, Any]:
        """카운터 키를 ``delta`` 만큼 증가 + 추가 필드 갱신."""
        with self._lock:
            if not self._cache:
                self._cache = self.read()
            self._cache[key] = int(self._cache.get(key, 0)) + delta
            if fields:
                self._cache.update(fields)
            self._flush_locked()
            return dict(self._cache)

    def _flush_locked(self) -> None:
        """tmp → fsync → replace 원자적 쓰기.

        디스크 풀/권한 오류로 쓰기가 실패하면, 잔여 ``.tmp`` 를 정리한 뒤
        예외를 올린다(writer.py 와 동일 패턴). 정리하지 않으면 orphan tmp
        파일이 디스크에 남는다. 원본은 ``os.replace`` 전까지 건드리지 않으므로
        실패해도 손상되지 않는다(이전 상태 유지).
        """
        tmp = self._path.with_name(self._path.name + ".tmp")
        payload = json.dumps(self._cache, ensure_ascii=False, indent=2)
        try:
            with open(tmp, "w", encoding="utf-8") as fp:
                fp.write(payload)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp, self._path)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def clear(self) -> None:
        """상태 파일 삭제 (graceful shutdown 시)."""
        with self._lock:
            self._cache = {}
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass
