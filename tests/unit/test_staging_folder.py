"""``is_staging_folder`` 헬퍼 단위 테스트.

inbox 변형 폴더 식별 패턴이 의도한 매치/비매치 케이스만 잡는지 검증.
"""

from __future__ import annotations

import pytest

from wiki_search_mcp.core.config import is_staging_folder


@pytest.mark.parametrize(
    "name",
    [
        "inbox",
        "Inbox",
        "INBOX",
        "_inbox",
        ".inbox",
        "0.Inbox",
        "00.inbox",
        "1inbox",
        "0inbox",
    ],
)
def test_recognized_as_staging(name: str) -> None:
    assert is_staging_folder(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "inbox-archive",
        "my-inbox",
        "inbox_old",
        "inboxing",
        "infra",
        "devops",
        "notes",
        "",
        "in",
        "box",
    ],
)
def test_not_staging(name: str) -> None:
    assert is_staging_folder(name) is False
