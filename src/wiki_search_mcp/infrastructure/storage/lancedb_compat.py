"""LanceDB 버전 호환 헬퍼.

lancedb는 0.13 전후로 ``list_tables()``의 반환을 ``list[str]``에서
``ListTablesResponse(tables=[...], page_token=...)`` 객체로 변경했다(pagination 도입).
이로 인해 ``"wiki" in db.list_tables()``가 신버전에서 항상 ``False``가 되는
회귀가 발생했다 (객체를 ``(field_name, value)`` 쌍으로 순회하기 때문).

이 모듈은 두 버전 모두에서 동작하는 단일 진실 헬퍼를 제공한다.
"""

from __future__ import annotations

from typing import Any


def list_table_names(db: Any) -> list[str]:
    """LanceDB 연결의 테이블 이름 목록을 버전 무관하게 반환.

    Args:
        db: ``lancedb.connect(...)`` 가 반환한 연결 객체

    Returns:
        테이블 이름 ``list[str]``. 없으면 빈 리스트.

    Note:
        - 신버전(0.13+): ``list_tables()`` → ``ListTablesResponse``.
          ``.tables`` 속성에서 실제 이름 목록을 꺼낸다.
        - 구버전: ``list_tables()`` → ``list[str]`` 직접 반환.
        - ``table_names()``는 구버전에서 동일 기능이지만 신버전에서 deprecated이므로
          사용하지 않는다.
    """
    result = db.list_tables()
    tables = getattr(result, "tables", None)
    if tables is not None:
        return list(tables)
    return list(result)


def has_table(db: Any, name: str) -> bool:
    """LanceDB 연결에 주어진 이름의 테이블이 존재하는지 버전 무관하게 확인.

    Args:
        db: ``lancedb.connect(...)`` 연결 객체
        name: 테이블 이름

    Returns:
        존재하면 True
    """
    return name in list_table_names(db)
