from datetime import date

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import TAIPEI_TZ
from app.modules.alerts.models import Alert, AlertDelivery
from app.modules.alerts.rules import AlertState, BaselineView, evaluate
from app.modules.auth.service import DEMO_EMAIL
from app.modules.notifications.models import Notification
from app.modules.prices.baseline import apply_result, history_ready
from app.modules.prices.models import PriceBaseline, PriceSnapshot
from app.modules.prices.providers.mock import mock_insights
from app.modules.users.models import User
from app.modules.watches.models import Watch
from app.seeds.demo import (
    ensure_demo_notifications,
    ensure_demo_prices,
    ensure_demo_user,
    ensure_demo_watches,
)
from app.seeds.reference import seed_reference

TODAY = date(2026, 11, 1)


async def test_seed_idempotent(db_session: AsyncSession) -> None:
    first = await ensure_demo_user(db_session)
    second = await ensure_demo_user(db_session)
    assert first.id == second.id
    assert first.is_demo is True
    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.email == DEMO_EMAIL)
    )
    assert count == 1


async def test_demo_watches_seeded(db_session: AsyncSession) -> None:
    await seed_reference(db_session)
    demo = await ensure_demo_user(db_session)
    await ensure_demo_watches(db_session, demo, TODAY)
    await ensure_demo_watches(db_session, demo, TODAY)

    watches = (await db_session.scalars(select(Watch).where(Watch.user_id == demo.id))).unique()
    watches_list = list(watches)
    assert len(watches_list) == 3
    assert {w.status for w in watches_list} == {"active", "paused", "expired"}
    assert all(w.price_query.is_demo for w in watches_list)


async def test_demo_watches_visible(client: AsyncClient, db_session: AsyncSession) -> None:
    await seed_reference(db_session)
    demo = await ensure_demo_user(db_session)
    await ensure_demo_watches(db_session, demo, TODAY)
    token = (await client.post("/api/v1/auth/demo")).json()["access_token"]
    resp = await client.get("/api/v1/watches", headers={"Authorization": f"Bearer {token}"})
    assert len(resp.json()) == 3


async def test_demo_prices_seeded(db_session: AsyncSession) -> None:
    await seed_reference(db_session)
    demo = await ensure_demo_user(db_session)
    await ensure_demo_watches(db_session, demo, TODAY)
    await ensure_demo_prices(db_session, demo, TODAY)
    await ensure_demo_prices(db_session, demo, TODAY)

    watches = list(
        (await db_session.scalars(select(Watch).where(Watch.user_id == demo.id))).unique()
    )
    by_status = {w.status: w for w in watches}
    for status in ("active", "expired"):
        query_id = by_status[status].price_query_id
        prices = (
            await db_session.scalars(
                select(PriceSnapshot)
                .where(PriceSnapshot.price_query_id == query_id)
                .order_by(PriceSnapshot.observed_at)
            )
        ).all()
        assert len(prices) == 30
        baseline = await db_session.get(PriceBaseline, query_id)
        assert baseline is not None
        assert baseline.sample_count == 30
        assert baseline.history_seeded is True
        assert baseline.record_low is not None
        assert baseline.record_low <= min(p.price for p in prices)
        if status == "active":
            last = prices[-1].observed_at.astimezone(TAIPEI_TZ)
            assert (last.date(), last.hour) == (TODAY, 9)
    paused_query = by_status["paused"].price_query_id
    paused_count = await db_session.scalar(
        select(func.count())
        .select_from(PriceSnapshot)
        .where(PriceSnapshot.price_query_id == paused_query)
    )
    assert paused_count == 0


async def test_demo_prices_visible(client: AsyncClient, db_session: AsyncSession) -> None:
    await seed_reference(db_session)
    demo = await ensure_demo_user(db_session)
    await ensure_demo_watches(db_session, demo, TODAY)
    await ensure_demo_prices(db_session, demo, TODAY)
    active = await db_session.scalar(
        select(Watch).where(Watch.user_id == demo.id, Watch.status == "active")
    )
    assert active is not None
    token = (await client.post("/api/v1/auth/demo")).json()["access_token"]
    resp = await client.get(
        f"/api/v1/watches/{active.public_id}/prices?range=all",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert len(resp.json()) == 30


async def _seed_all(session: AsyncSession) -> User:
    await seed_reference(session)
    demo = await ensure_demo_user(session)
    await ensure_demo_watches(session, demo, TODAY)
    await ensure_demo_prices(session, demo, TODAY)
    await ensure_demo_notifications(session, demo, TODAY)
    return demo


async def _expected_alerts(session: AsyncSession, demo: User) -> set[tuple[int, int, str]]:
    """照時間順序把示範快照逐筆餵給觸發規則，算出應該產生的 alert。"""
    expected: set[tuple[int, int, str]] = set()
    watches = (
        await session.scalars(
            select(Watch).where(Watch.user_id == demo.id, Watch.status.in_(("active", "expired")))
        )
    ).unique()
    for watch in watches:
        snapshots = (
            await session.scalars(
                select(PriceSnapshot)
                .where(PriceSnapshot.price_query_id == watch.price_query_id)
                .order_by(PriceSnapshot.observed_at)
            )
        ).all()
        baseline = PriceBaseline(history_seeded=False, sample_count=0)
        insights = mock_insights(watch.price_query.query_hash)
        state = AlertState()
        for s in snapshots:
            before = (baseline.record_low, history_ready(baseline))
            apply_result(baseline, s.price, insights)
            decision = evaluate(
                state, s.price, watch.target_price, BaselineView(baseline.typical_low, *before)
            )
            state = decision.new_state
            if decision.notify:
                expected.add((watch.id, s.id, decision.reasons[0]))
    return expected


async def test_demo_notifications_match_rules(db_session: AsyncSession) -> None:
    demo = await _seed_all(db_session)
    await ensure_demo_notifications(db_session, demo, TODAY)

    alerts = (await db_session.scalars(select(Alert))).all()
    actual = {(a.watch_id, a.snapshot_id, a.reason) for a in alerts}
    assert actual == await _expected_alerts(db_session, demo)
    assert actual

    notes = (
        await db_session.scalars(
            select(Notification)
            .where(Notification.user_id == demo.id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
        )
    ).all()
    price_notes = [n for n in notes if n.type == "price_alert"]
    assert len(price_notes) == len(alerts)
    assert len([n for n in notes if n.type == "system"]) == 1
    assert [n for n in notes if not n.is_read] == [price_notes[0]]
    assert await db_session.scalar(select(func.count()).select_from(AlertDelivery)) == 0


async def test_demo_notifications_visible(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed_all(db_session)
    price_alerts = await db_session.scalar(select(func.count()).select_from(Alert))
    token = (await client.post("/api/v1/auth/demo")).json()["access_token"]
    resp = await client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == (price_alerts or 0) + 1
