"""Append-only JSON Lines log.

Daemon이 ``pending.jsonl`` / ``applied.jsonl`` 같이 멱등 append와 순회/꼬리/순환을 같이 필요로 하는
구조에서 사용합니다. 각 줄은 단일 JSON 객체이며, 라인 단위 ``json.loads``로 처리합니다.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any


class JsonlLog:
    """append-only JSON Lines 파일 래퍼.

    설계 원칙:
    - 동일 프로세스 내 동시 append는 ``threading.Lock``으로 직렬화한다.
    - 디스크 fsync는 매 append마다 수행하여 daemon 비정상 종료 시 손실 최소화.
    - 파일 회전(rotate)은 호출자가 명시적으로 트리거한다 (자동 회전 안 함).
    - 라인 단위 파싱 실패는 ``scan()``에서 ``ValueError``를 raise하지 않고 ``skip``한다
      (오염된 라인이 전체 순회를 막지 않도록).
    """

    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = threading.Lock()
        # 부모 디렉토리 보장 — daemon 시작 시 state_dir이 생성되지만 방어적으로 한 번 더.
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def append(self, obj: dict[str, Any]) -> None:
        """객체 한 개를 한 줄로 append + fsync.

        ``ensure_ascii=False``: 한글/CJK 문자를 그대로 저장.
        """
        line = json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n"
        with self._lock, open(self._path, "ab") as fp:
            fp.write(line)
            fp.flush()
            os.fsync(fp.fileno())

    def scan(self) -> Iterator[dict[str, Any]]:
        """앞에서부터 모든 라인을 순회. 파일이 없으면 빈 이터레이터."""
        if not self._path.exists():
            return
        with open(self._path, "r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # 오염된 라인은 무시 (로그에는 남기지 않음 - 호출자가 알 필요 없음)
                    continue

    def tail(self, n: int) -> list[dict[str, Any]]:
        """마지막 n개 객체를 리스트로 반환 (오래된 순서 유지)."""
        if n <= 0 or not self._path.exists():
            return []
        # 작은 파일에서는 전체 읽기가 가장 단순. 50MB 이하 권장.
        items = list(self.scan())
        return items[-n:]

    def rotate(self, suffix: str) -> Path | None:
        """현재 파일을 ``<name>.<suffix>``로 rename하고 새 파일 시작.

        Args:
            suffix: 회전 파일 접미사 (예: ``"2026-05-13"``).

        Returns:
            회전된 파일 경로 (없으면 None).
        """
        if not self._path.exists():
            return None
        rotated = self._path.with_name(f"{self._path.name}.{suffix}")
        with self._lock:
            os.replace(self._path, rotated)
        return rotated
