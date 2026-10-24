from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.models import Alert, AlertDelivery, WatchAlertState
from app.modules.alerts.rules import BaselineView
from app.modules.alerts.service import evaluate_watches, reset_state
from app.modules.notifications.models import Notification, NotificationSetting
from app.modules.prices.checker import run_checks
from app.modules.prices.models import PriceBaseline, PriceSnapshot
from app.modules.prices.providers.base import SearchResult
from app.modules.users.models import User
from app.modules.watches.models import Watch
from tests.alerts.conftest import TODAY, FakeProvider, insert_watch
from tests.conftest import create_user

NOW = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)


async def _run(session: AsyncSession, provider: FakeProvider | None = None) -> None:
    await run_checks(session, provider or FakeProvider(), TODAY, now=lambda: NOW)


async def _count(session: AsyncSession, model: type[object]) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def _state(session: AsyncSession, watch: Watch) -> WatchAlertState | None:
    return await session.get(WatchAlertState, watch.id, populate_existing=True)


async def _disable_email(session: AsyncSession, user: User) -> None:
    session.add(NotificationSetting(user_id=user.id, email_enabled=False))
    await session.flush()


async def test_check_creates_alert_notification_delivery(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    watch = await insert_watch(db_session, user, target_price=9500)
    await _run(db_session)

    snapshot = await db_session.scalar(select(PriceSnapshot))
    alert = await db_session.scalar(select(Alert))
    assert snapshot is not None and alert is not None
    assert (alert.watch_id, alert.reason, alert.price) == (watch.id, "below_target", 9000)
    assert alert.snapshot_id == snapshot.id

    notification = await db_session.scalar(select(Notification))
    assert notification is not None
    assert notification.type == "price_alert"
    assert notification.user_id == user.id
    assert notification.alert_id == alert.id
    assert "跌破目標價" in notification.title
    assert notification.link == f"/watches/{watch.public_id}"

    delivery = await db_session.scalar(select(AlertDelivery))
    assert delivery is not None
    assert (delivery.alert_id, delivery.channel, delivery.status) == (alert.id, "email", "pending")

    state = await _state(db_session, watch)
    assert state is not None
    assert state.below_target is True
    assert state.last_notified_price == 9000
    assert state.last_notified_at == NOW


async def test_no_alert_above_target(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    watch = await insert_watch(db_session, user, target_price=8000)
    await _run(db_session)

    assert await _count(db_session, Alert) == 0
    state = await _state(db_session, watch)
    assert state is not None
    assert state.below_target is False
    assert state.last_notified_price is None


async def test_rerun_same_snapshot_no_duplicate(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    watch = await insert_watch(db_session, user, target_price=9500)
    await _run(db_session)
    snapshot = await db_session.scalar(select(PriceSnapshot))
    assert snapshot is not None

    # 重置後規則會再次判定要通知，但同一筆快照不能產生第二則
    await reset_state(db_session, watch.id)
    view = BaselineView(typical_low=None, record_low_before=None, history_ready_before=False)
    created = await evaluate_watches(db_session, watch.price_query, snapshot, view, NOW)

    assert created == 0
    assert await _count(db_session, Alert) == 1
    assert await _count(db_session, Notification) == 1


async def test_paused_watch_ignored(db_session: AsyncSession) -> None:
    alice = await create_user(db_session)
    bob = await create_user(db_session, email="bob@example.com")
    active = await insert_watch(db_session, alice, target_price=9500)
    await insert_watch(db_session, bob, target_price=9500, status="paused")
    await _run(db_session)

    alerts = (await db_session.scalars(select(Alert))).all()
    assert [a.watch_id for a in alerts] == [active.id]


async def test_email_disabled_no_delivery(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    await _disable_email(db_session, user)
    await insert_watch(db_session, user, target_price=9500)
    await _run(db_session)

    assert await _count(db_session, Alert) == 1
    assert await _count(db_session, Notification) == 1
    assert await _count(db_session, AlertDelivery) == 0


async def test_two_users_one_email_off(db_session: AsyncSession) -> None:
    alice = await create_user(db_session)
    bob = await create_user(db_session, email="bob@example.com")
    await _disable_email(db_session, bob)
    alice_watch = await insert_watch(db_session, alice, target_price=9500)
    await insert_watch(db_session, bob, target_price=9500)
    await _run(db_session)

    notified = set((await db_session.scalars(select(Notification.user_id))).all())
    assert notified == {alice.id, bob.id}
    deliveries = (
        await db_session.scalars(
            select(Alert.watch_id).join(AlertDelivery, AlertDelivery.alert_id == Alert.id)
        )
    ).all()
    assert deliveries == [alice_watch.id]


async def test_no_result_no_evaluation(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    watch = await insert_watch(db_session, user, target_price=9500)
    await _run(db_session, FakeProvider(default=SearchResult(None, None, None)))

    assert await _count(db_session, Alert) == 0
    assert await _state(db_session, watch) is None


async def test_record_low_uses_value_before_price(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    watch = await insert_watch(db_session, user, target_price=5000)
    db_session.add(
        PriceBaseline(
            price_query_id=watch.price_query_id,
            record_low=9500,
            history_seeded=True,
            sample_count=0,
        )
    )
    await db_session.flush()
    await _run(db_session)

    alert = await db_session.scalar(select(Alert))
    assert alert is not None
    assert alert.reason == "record_low"
    baseline = await db_session.get(PriceBaseline, watch.price_query_id, populate_existing=True)
    assert baseline is not None
    assert baseline.record_low == 9000
