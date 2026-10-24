from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.models import Alert, AlertDelivery, WatchAlertState
from app.modules.notifications.models import Notification
from app.modules.prices.models import PriceSnapshot
from app.modules.users.models import User
from app.modules.watches.models import Watch
from tests.alerts.conftest import insert_watch
from tests.conftest import create_user

NOW = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)


async def _snapshot(session: AsyncSession, watch: Watch) -> PriceSnapshot:
    snapshot = PriceSnapshot(
        price_query_id=watch.price_query_id, provider="mock", price=9000, stops=0, observed_at=NOW
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def _alert(session: AsyncSession, watch: Watch, snapshot: PriceSnapshot) -> Alert:
    alert = Alert(watch_id=watch.id, snapshot_id=snapshot.id, reason="below_target", price=9000)
    session.add(alert)
    await session.flush()
    return alert


async def _setup(session: AsyncSession) -> tuple[User, Watch, PriceSnapshot]:
    user = await create_user(session)
    watch = await insert_watch(session, user)
    return user, watch, await _snapshot(session, watch)


async def test_alert_unique_per_snapshot(db_session: AsyncSession) -> None:
    _, watch, snapshot = await _setup(db_session)
    await _alert(db_session, watch, snapshot)
    db_session.add(Alert(watch_id=watch.id, snapshot_id=snapshot.id, reason="record_low", price=1))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_delivery_defaults_and_unique(db_session: AsyncSession) -> None:
    _, watch, snapshot = await _setup(db_session)
    alert = await _alert(db_session, watch, snapshot)
    delivery = AlertDelivery(alert_id=alert.id, channel="email")
    db_session.add(delivery)
    await db_session.flush()
    await db_session.refresh(delivery)
    assert delivery.status == "pending"
    assert delivery.attempts == 0

    db_session.add(AlertDelivery(alert_id=alert.id, channel="email"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_notification_dedupe(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    first = Notification(user_id=user.id, type="system", title="t", body="b")
    db_session.add_all([first, Notification(user_id=user.id, type="system", title="t", body="b")])
    await db_session.flush()
    await db_session.refresh(first)
    assert first.is_read is False

    db_session.add(
        Notification(user_id=user.id, type="system", title="t", body="b", dedupe_key="k")
    )
    await db_session.flush()
    db_session.add(
        Notification(user_id=user.id, type="system", title="t", body="b", dedupe_key="k")
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_delete_watch_cascades(db_session: AsyncSession) -> None:
    user, watch, snapshot = await _setup(db_session)
    alert = await _alert(db_session, watch, snapshot)
    db_session.add_all(
        [
            WatchAlertState(watch_id=watch.id, below_target=True, last_notified_price=9000),
            AlertDelivery(alert_id=alert.id, channel="email"),
        ]
    )
    notification = Notification(
        user_id=user.id, type="price_alert", title="t", body="b", alert_id=alert.id
    )
    db_session.add(notification)
    await db_session.flush()

    await db_session.delete(watch)
    await db_session.flush()
    db_session.expunge_all()

    assert await db_session.get(WatchAlertState, watch.id) is None
    assert await db_session.scalar(select(Alert)) is None
    assert await db_session.scalar(select(AlertDelivery)) is None
    kept = await db_session.get(Notification, notification.id)
    assert kept is not None
    assert kept.alert_id is None


async def test_delete_snapshot_keeps_alert(db_session: AsyncSession) -> None:
    _, watch, snapshot = await _setup(db_session)
    alert = await _alert(db_session, watch, snapshot)
    await db_session.delete(snapshot)
    await db_session.flush()
    db_session.expunge_all()

    kept = await db_session.get(Alert, alert.id)
    assert kept is not None
    assert kept.snapshot_id is None
