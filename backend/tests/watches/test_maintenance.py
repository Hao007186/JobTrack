from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.watches.models import Watch
from app.modules.watches.service import expire_watches
from tests.conftest import create_user
from tests.watches.conftest import TODAY, fill_slots, insert_watch


async def _status(session: AsyncSession, watch: Watch) -> str:
    await session.refresh(watch)
    return watch.status


async def test_expire_past_departures(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    yesterday = TODAY - timedelta(days=1)
    past = [
        await insert_watch(db_session, user, status=s, destination=d, depart_date=yesterday)
        for s, d in [("active", "NRT"), ("queued", "KIX"), ("paused", "ICN")]
    ]
    today_watch = await insert_watch(db_session, user, destination="HKG", depart_date=TODAY)

    expired, _ = await expire_watches(db_session, TODAY)
    assert expired == 3
    assert [await _status(db_session, w) for w in past] == ["expired"] * 3
    assert await _status(db_session, today_watch) == "active"


async def test_expire_promotes(db_session: AsyncSession) -> None:
    filled = await fill_slots(db_session, 8)
    # 把其中一個佔名額的 query 改成昨天出發
    filled[0].price_query.depart_date = TODAY - timedelta(days=1)
    user = await create_user(db_session)
    queued = await insert_watch(db_session, user, status="queued", destination="PUS")
    await db_session.flush()

    assert await expire_watches(db_session, TODAY) == (1, 1)
    assert await _status(db_session, queued) == "active"


async def test_expire_idempotent(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    await insert_watch(db_session, user, depart_date=TODAY - timedelta(days=1))
    await expire_watches(db_session, TODAY)
    assert await expire_watches(db_session, TODAY) == (0, 0)
