from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User
from app.modules.watches.models import PriceQuery, Watch
from tests.conftest import create_user
from tests.watches.conftest import (
    TODAY,
    auth_headers,
    demo_headers,
    fill_slots,
    insert_watch,
)

URL = "/api/v1/watches"


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


async def _alice(session: AsyncSession) -> User:
    user = await session.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    return user


async def _patch(
    client: AsyncClient, headers: dict[str, str], watch: Watch, **payload: Any
) -> Response:
    return await client.patch(f"{URL}/{watch.public_id}", json=payload, headers=headers)


async def _reload(session: AsyncSession, watch: Watch) -> Watch:
    await session.refresh(watch)
    return watch


async def test_update_target_price_only(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(db_session, await _alice(db_session))
    query_id = watch.price_query_id
    resp = await _patch(client, headers, watch, target_price=8000)
    assert resp.status_code == 200
    assert resp.json()["target_price"] == 8000
    assert resp.json()["status"] == "active"
    assert (await _reload(db_session, watch)).price_query_id == query_id


async def test_update_conditions_moves_query(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(db_session, await _alice(db_session))
    old_query_id = watch.price_query_id
    resp = await _patch(client, headers, watch, destination="KIX")
    assert resp.status_code == 200
    assert resp.json()["destination"] == "KIX"
    assert (await _reload(db_session, watch)).price_query_id != old_query_id
    assert await db_session.get(PriceQuery, old_query_id) is not None


async def test_update_conditions_queues_when_full(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(db_session, await _alice(db_session))
    other = await create_user(db_session, email="other@example.com")
    await insert_watch(db_session, other)  # W 移走後 TPE→NRT 仍佔名額
    await fill_slots(db_session, 7)
    resp = await _patch(client, headers, watch, destination="PUS")
    assert resp.json()["status"] == "queued"


async def test_paused_stays_paused_on_edit(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(db_session, await _alice(db_session), status="paused")
    resp = await _patch(client, headers, watch, destination="KIX")
    assert resp.json()["status"] == "paused"


async def test_change_to_one_way(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(
        db_session, await _alice(db_session), return_date=TODAY + timedelta(days=35)
    )
    resp = await _patch(client, headers, watch, return_date=None)
    assert resp.status_code == 200
    assert resp.json()["trip_type"] == "one_way"


async def test_partial_edit_validated_as_whole(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(db_session, await _alice(db_session))  # 單程 TODAY+30
    resp = await _patch(client, headers, watch, return_date=day(10))
    assert resp.status_code == 422


async def test_unchanged_values_skip_date_check(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(
        db_session, await _alice(db_session), depart_date=TODAY + timedelta(days=2)
    )
    resp = await _patch(client, headers, watch, depart_date=day(2), target_price=8000)
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


async def test_edit_queued_keeps_position(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    await fill_slots(db_session, 8)
    watch = await insert_watch(
        db_session, await _alice(db_session), status="queued", destination="PUS"
    )
    created_at = watch.created_at
    resp = await _patch(client, headers, watch, target_price=8000)
    assert resp.json()["status"] == "queued"
    assert (await _reload(db_session, watch)).created_at == created_at


async def test_pause_frees_slot(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    alice = await _alice(db_session)
    mine = await insert_watch(db_session, alice)
    await fill_slots(db_session, 7)
    queued = await insert_watch(db_session, alice, status="queued", destination="PUS")

    resp = await _patch(client, headers, mine, status="paused")
    assert resp.json()["status"] == "paused"
    assert (await _reload(db_session, queued)).status == "active"


async def test_resume_with_free_slot(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(db_session, await _alice(db_session), status="paused")
    assert (await _patch(client, headers, watch, status="active")).json()["status"] == "active"


async def test_resume_when_full(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    await fill_slots(db_session, 8)
    watch = await insert_watch(
        db_session, await _alice(db_session), status="paused", destination="PUS"
    )
    assert (await _patch(client, headers, watch, status="active")).json()["status"] == "queued"


async def test_resume_over_user_limit(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    alice = await _alice(db_session)
    for dest in ["KIX", "ICN", "HKG"]:
        await insert_watch(db_session, alice, destination=dest)
    watch = await insert_watch(db_session, alice, status="paused")
    resp = await _patch(client, headers, watch, status="active")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "每人最多 3 個追蹤"


async def test_status_active_on_queued_is_noop(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await auth_headers(client, db_session)
    await fill_slots(db_session, 8)
    watch = await insert_watch(
        db_session, await _alice(db_session), status="queued", destination="PUS"
    )
    assert (await _patch(client, headers, watch, status="active")).json()["status"] == "queued"


@pytest.mark.parametrize("value", ["expired", "queued"])
async def test_invalid_status(client: AsyncClient, db_session: AsyncSession, value: str) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(db_session, await _alice(db_session))
    assert (await _patch(client, headers, watch, status=value)).status_code == 422


async def test_edit_expired_409(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(db_session, await _alice(db_session), status="expired")
    resp = await _patch(client, headers, watch, target_price=8000)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "已過期的追蹤不能修改"


async def test_update_other_users_404(client: AsyncClient, db_session: AsyncSession) -> None:
    await auth_headers(client, db_session)
    bob_headers = await auth_headers(client, db_session, email="bob@example.com")
    watch = await insert_watch(db_session, await _alice(db_session))
    assert (await _patch(client, bob_headers, watch, target_price=8000)).status_code == 404


async def test_demo_cannot_update(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await create_user(db_session, email="owner@example.com")
    watch = await insert_watch(db_session, owner)
    headers = await demo_headers(client, db_session)
    assert (await _patch(client, headers, watch, target_price=8000)).status_code == 403


async def test_resume_does_not_jump_queue(client: AsyncClient, db_session: AsyncSession) -> None:
    await fill_slots(db_session, 7)
    other = await create_user(db_session, email="early@example.com")
    waiting = await insert_watch(db_session, other, status="queued", destination="PUS")
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(db_session, await _alice(db_session), status="paused")

    assert (await _patch(client, headers, watch, status="active")).json()["status"] == "queued"
    assert (await _reload(db_session, waiting)).status == "active"
