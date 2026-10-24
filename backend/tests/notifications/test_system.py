from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification
from app.modules.notifications.service import create_system_notification
from app.modules.prices.checker import run_checks
from app.modules.users.models import User
from app.modules.watches.service import delete_watch
from tests.conftest import create_user
from tests.notifications.conftest import TODAY, FakeProvider, fill_slots, insert_watch

NOW = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)


async def _notifications(session: AsyncSession, user: User) -> list[Notification]:
    result = await session.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    return list(result)


async def test_activation_notifies_owner(db_session: AsyncSession) -> None:
    fills = await fill_slots(db_session, 8)
    filler = await db_session.get(User, fills[0].user_id)
    assert filler is not None
    bob = await create_user(db_session, email="bob@example.com")
    waiting = await insert_watch(db_session, bob, status="queued")

    await delete_watch(db_session, filler, fills[0].public_id, TODAY)

    notes = await _notifications(db_session, bob)
    assert len(notes) == 1
    assert notes[0].type == "system"
    assert notes[0].title.endswith("已開始查價")
    assert notes[0].link == f"/watches/{waiting.public_id}"
    assert await _notifications(db_session, filler) == []


async def test_quota_exhausted_once_per_month(db_session: AsyncSession) -> None:
    alice = await create_user(db_session)
    bob = await create_user(db_session, email="bob@example.com")
    carol = await create_user(db_session, email="carol@example.com")
    await insert_watch(db_session, alice)
    await insert_watch(db_session, bob, destination="KIX")
    await insert_watch(db_session, carol, destination="ICN", status="paused")

    for _ in range(2):
        await run_checks(db_session, FakeProvider(remaining=0), TODAY, now=lambda: NOW)

    for user in (alice, bob):
        notes = await _notifications(db_session, user)
        assert len(notes) == 1
        assert notes[0].type == "system"
        assert notes[0].dedupe_key == "quota_exhausted:2026-11"
    assert await _notifications(db_session, carol) == []


async def test_quota_no_due_queries(db_session: AsyncSession) -> None:
    await run_checks(db_session, FakeProvider(remaining=0), TODAY, now=lambda: NOW)
    assert await db_session.scalar(select(Notification)) is None


async def test_create_system_notification_dedupe(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    assert await create_system_notification(db_session, user.id, "t", "b", dedupe_key="k")
    assert not await create_system_notification(db_session, user.id, "t", "b", dedupe_key="k")
    assert len(await _notifications(db_session, user)) == 1
