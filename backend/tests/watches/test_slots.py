from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.watches.models import Watch
from app.modules.watches.slots import (
    WATCH_LOCK_KEY,
    acquire_watch_lock,
    count_user_slots,
    decide_status,
    get_or_create_price_query,
    occupied_query_ids,
    rebalance,
)
from tests.conftest import create_user
from tests.watches.conftest import TODAY, conditions, fill_slots, insert_watch


async def _status(session: AsyncSession, watch: Watch) -> str:
    await session.refresh(watch)
    return watch.status


async def test_get_or_create_reuses(db_session: AsyncSession) -> None:
    a = await get_or_create_price_query(db_session, conditions())
    b = await get_or_create_price_query(db_session, conditions())
    assert a.id == b.id
    c = await get_or_create_price_query(db_session, conditions(adults=2))
    assert c.id != a.id


async def test_occupied_rules(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    active = await insert_watch(db_session, user, destination="KIX")
    await insert_watch(db_session, user, status="paused", destination="ICN")
    await insert_watch(db_session, user, status="queued", destination="HKG")
    await insert_watch(db_session, user, destination="BKK", is_demo=True)
    await insert_watch(db_session, user, destination="SIN", depart_date=TODAY + timedelta(days=2))
    edge = await insert_watch(
        db_session, user, destination="OKA", depart_date=TODAY + timedelta(days=3)
    )
    assert await occupied_query_ids(db_session, TODAY) == {
        active.price_query_id,
        edge.price_query_id,
    }


async def test_decide_status_full(db_session: AsyncSession) -> None:
    await fill_slots(db_session, 8)
    query = await get_or_create_price_query(db_session, conditions())
    assert await decide_status(db_session, query, TODAY) == "queued"


async def test_decide_status_free_slot(db_session: AsyncSession) -> None:
    await fill_slots(db_session, 7)
    query = await get_or_create_price_query(db_session, conditions())
    assert await decide_status(db_session, query, TODAY) == "active"


async def test_decide_status_query_already_occupied(db_session: AsyncSession) -> None:
    watches = await fill_slots(db_session, 8)
    assert await decide_status(db_session, watches[0].price_query, TODAY) == "active"


async def test_decide_status_near_departure(db_session: AsyncSession) -> None:
    query = await get_or_create_price_query(
        db_session, conditions(depart_date=TODAY + timedelta(days=2))
    )
    assert await decide_status(db_session, query, TODAY) == "queued"


async def test_decide_status_demo(db_session: AsyncSession) -> None:
    await fill_slots(db_session, 8)
    query = await get_or_create_price_query(db_session, conditions(is_demo=True))
    assert await decide_status(db_session, query, TODAY) == "active"


async def test_count_user_slots(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    for status, dest in [
        ("active", "KIX"),
        ("queued", "ICN"),
        ("paused", "HKG"),
        ("expired", "BKK"),
    ]:
        await insert_watch(db_session, user, status=status, destination=dest)
    assert await count_user_slots(db_session, user.id) == 2


async def test_rebalance_promotes_by_created_at(db_session: AsyncSession) -> None:
    filled = await fill_slots(db_session, 8)
    user = await create_user(db_session)
    base = datetime(2026, 10, 1, tzinfo=UTC)
    # A 的 id 較小但建立時間較晚
    a = await insert_watch(
        db_session, user, status="queued", destination="HND", created_at=base + timedelta(hours=1)
    )
    b = await insert_watch(db_session, user, status="queued", destination="PUS", created_at=base)
    filled[0].status = "paused"
    await db_session.flush()

    assert len(await rebalance(db_session, TODAY)) == 1
    assert await _status(db_session, b) == "active"
    assert await _status(db_session, a) == "queued"


async def test_rebalance_promotes_same_query_together(db_session: AsyncSession) -> None:
    filled = await fill_slots(db_session, 8)
    user1 = await create_user(db_session, email="u1@example.com")
    user2 = await create_user(db_session, email="u2@example.com")
    w1 = await insert_watch(db_session, user1, status="queued")
    w2 = await insert_watch(db_session, user2, status="queued")
    filled[0].status = "paused"
    await db_session.flush()

    assert len(await rebalance(db_session, TODAY)) == 2
    assert await _status(db_session, w1) == "active"
    assert await _status(db_session, w2) == "active"


async def test_rebalance_promotes_when_query_already_occupied(db_session: AsyncSession) -> None:
    filled = await fill_slots(db_session, 8)
    user = await create_user(db_session)
    q = await insert_watch(
        db_session, user, status="queued", destination=filled[0].price_query.destination
    )
    assert len(await rebalance(db_session, TODAY)) == 1
    assert await _status(db_session, q) == "active"


async def test_rebalance_skips_near_departure(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    near = await insert_watch(
        db_session, user, status="queued", depart_date=TODAY + timedelta(days=2)
    )
    assert len(await rebalance(db_session, TODAY)) == 0
    assert await _status(db_session, near) == "queued"


async def test_lock_is_held(db_session: AsyncSession) -> None:
    await acquire_watch_lock(db_session)
    held = await db_session.scalar(
        text(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
            "AND objid = :key AND pid = pg_backend_pid()"
        ),
        {"key": WATCH_LOCK_KEY},
    )
    assert held is not None and held >= 1
