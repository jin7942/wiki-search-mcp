"""JSON meta store implementation.

core.protocols.MetaRepository 인터페이스의 구현체입니다.
meta.json 파일에서 인덱스 메타데이터를 관리합니다.

사용 예:
    from wiki_search_mcp.infrastructure.storage import JsonMetaStore

    store = JsonMetaStore(Path("/wiki/.vectordb"))
    last_indexed = store.get_last_indexed()
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonMetaStore:
    """JSON 기반 메타데이터 스토어 구현.

    MetaRepository 프로토콜을 구현합니다.
    meta.json 파일에서 인덱스 메타데이터를 로드합니다.

    Attributes:
        _meta: 메타데이터 dict
    """

    def __init__(self, db_path: Path):
        """JsonMetaStore 초기화.

        Args:
            db_path: 메타데이터 저장 경로 (.vectordb)
        """
        self._db_path = db_path
        self._meta: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """meta.json 로드."""
        meta_path = self._db_path / "meta.json"
        if meta_path.exists():
            self._meta = json.loads(meta_path.read_text(encoding="utf-8"))
        else:
            self._meta = {"files": {}, "last_indexed": None}

    def get_last_indexed(self) -> str | None:
        """마지막 인덱싱 시간.

        Returns:
            ISO 형식 시간 문자열 또는 None
        """
        return self._meta.get("last_indexed")

    def get_file_info(self, path: str) -> dict[str, Any] | None:
        """파일별 메타데이터 조회.

        Args:
            path: 파일 경로

        Returns:
            파일 메타데이터 또는 None
        """
        return self._meta.get("files", {}).get(path)

    def reload(self) -> None:
        """메타데이터 리로드.

        meta.json이 갱신된 후 호출합니다.
        """
        self._load()

    @property
    def file_count(self) -> int:
        """인덱싱된 파일 수.

        Returns:
            파일 수
        """
        return len(self._meta.get("files", {}))
