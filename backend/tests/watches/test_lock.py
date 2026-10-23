from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User
from app.modules.watches.service import expire_watches
from app.modules.watches.slots import WATCH_LOCK_KEY
from tests.watches.conftest import TODAY, auth_headers, insert_watch

URL = "/api/v1/watches"


async def _lock_count(session: AsyncSession) -> int:
    # 測試整個包在外層 transaction 裡，操作內的 commit 只會釋放 savepoint，
    # 所以 xact lock 會留到測試結束，可以在操作之後檢查
    count = await session.scalar(
        text(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
            "AND objid = :key AND pid = pg_backend_pid()"
        ),
        {"key": WATCH_LOCK_KEY},
    )
    return count or 0


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
async def test_write_operations_take_lock(
    client: AsyncClient, db_session: AsyncSession, operation: str
) -> None:
    headers = await auth_headers(client, db_session)
    alice = await db_session.scalar(select(User).where(User.email == "alice@example.com"))
    assert alice is not None
    watch = await insert_watch(db_session, alice)
    assert await _lock_count(db_session) == 0

    if operation == "create":
        payload = {
            "origin": "TPE",
            "destination": "KIX",
            "depart_date": (TODAY + timedelta(days=30)).isoformat(),
            "target_price": 9000,
        }
        resp = await client.post(URL, json=payload, headers=headers)
    elif operation == "update":
        resp = await client.patch(
            f"{URL}/{watch.public_id}", json={"target_price": 8000}, headers=headers
        )
    else:
        resp = await client.delete(f"{URL}/{watch.public_id}", headers=headers)
    assert resp.is_success
    assert await _lock_count(db_session) >= 1


async def test_expire_takes_lock(db_session: AsyncSession) -> None:
    assert await _lock_count(db_session) == 0
    await expire_watches(db_session, TODAY)
    assert await _lock_count(db_session) >= 1
