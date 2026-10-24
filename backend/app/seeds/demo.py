"""建立示範帳號與示範追蹤，可重複執行：python -m app.seeds.demo（需先執行 app.seeds.reference）"""

import asyncio
import secrets
import sys
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.models  # noqa: F401  獨立執行時也要註冊所有表
from app.core.clock import TAIPEI_TZ, taipei_today
from app.db.session import get_sessionmaker
from app.modules.alerts.rules import AlertState, BaselineView, evaluate
from app.modules.alerts.service import create_alert, save_state
from app.modules.auth.security import hash_password
from app.modules.auth.service import DEMO_EMAIL, get_user_by_email
from app.modules.notifications.messages import ACTIVATED_BODY, activated_title, watch_link
from app.modules.notifications.models import Notification
from app.modules.prices.baseline import apply_result, history_ready
from app.modules.prices.models import PriceBaseline, PriceSnapshot
from app.modules.prices.providers.mock import mock_insights, mock_price
from app.modules.users.models import User
from app.modules.watches.models import Watch
from app.modules.watches.slots import QueryConditions, get_or_create_price_query


async def ensure_demo_user(session: AsyncSession) -> User:
    existing = await get_user_by_email(session, DEMO_EMAIL)
    if existing is not None:
        return existing
    # 密碼是不公開的隨機值，示範帳號只能走 POST /auth/demo
    user = User(
        email=DEMO_EMAIL,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        display_name="示範帳號",
        is_demo=True,
    )
    session.add(user)
    await session.commit()
    return user


def _demo_watches(today: date) -> list[tuple[QueryConditions, int, str]]:
    def d(days: int) -> date:
        return today + timedelta(days=days)

    return [
        (
            QueryConditions("TPE", "NRT", d(60), d(65), "economy", 1, (), is_demo=True),
            9000,
            "active",
        ),
        (
            QueryConditions("TPE", "BKK", d(90), None, "economy", 1, (), is_demo=True),
            4500,
            "paused",
        ),
        (
            QueryConditions("KHH", "KIX", d(-30), d(-26), "economy", 2, (), is_demo=True),
            15000,
            "expired",
        ),
    ]


async def ensure_demo_watches(session: AsyncSession, user: User, today: date) -> None:
    has_watches = await session.scalar(
        select(func.count()).select_from(Watch).where(Watch.user_id == user.id)
    )
    if has_watches:
        return
    # 直接寫 DB、不經過 API 驗證：需要一個出發日已過的追蹤來展示「歷史紀錄」
    for cond, target_price, status in _demo_watches(today):
        query = await get_or_create_price_query(session, cond)
        session.add(
            Watch(
                user_id=user.id, price_query_id=query.id, target_price=target_price, status=status
            )
        )
    await session.commit()


DEMO_PRICE_DAYS = 30


def _demo_price_days(watch: Watch, today: date) -> list[date]:
    if watch.status == "active":
        last = today
    else:
        # 已過期的追蹤：出發日前 32 天到前 3 天
        last = watch.price_query.depart_date - timedelta(days=3)
    return [last - timedelta(days=offset) for offset in range(DEMO_PRICE_DAYS - 1, -1, -1)]


async def ensure_demo_prices(session: AsyncSession, user: User, today: date) -> None:
    """示範 query 不會被查價，直接用 mock 的價格規則產生 30 天的價格歷史與基準。"""
    watches = (
        await session.scalars(
            select(Watch).where(Watch.user_id == user.id, Watch.status.in_(("active", "expired")))
        )
    ).unique()
    for watch in watches:
        query = watch.price_query
        has_prices = await session.scalar(
            select(func.count())
            .select_from(PriceSnapshot)
            .where(PriceSnapshot.price_query_id == query.id)
        )
        if has_prices:
            continue
        baseline = PriceBaseline(price_query_id=query.id, history_seeded=False, sample_count=0)
        insights = mock_insights(query.query_hash)
        for day in _demo_price_days(watch, today):
            price = mock_price(query.query_hash, day)
            session.add(
                PriceSnapshot(
                    price_query_id=query.id,
                    provider="mock",
                    price=price,
                    airline_iata=None,
                    stops=0,
                    booking_url=None,
                    observed_at=datetime.combine(day, time(9), tzinfo=TAIPEI_TZ),
                )
            )
            apply_result(baseline, price, insights)
        session.add(baseline)
    await session.commit()


async def _demo_snapshots(session: AsyncSession, watch: Watch) -> list[PriceSnapshot]:
    result = await session.scalars(
        select(PriceSnapshot)
        .where(PriceSnapshot.price_query_id == watch.price_query_id)
        .order_by(PriceSnapshot.observed_at, PriceSnapshot.id)
    )
    return list(result)


async def _replay_alerts(session: AsyncSession, watch: Watch) -> None:
    """把示範快照依時間順序逐筆餵給真正的觸發規則，產生和正式流程一致的通知。"""
    # 不加入 session，只用來模擬基準逐筆累積
    baseline = PriceBaseline(history_seeded=False, sample_count=0)
    insights = mock_insights(watch.price_query.query_hash)
    state = AlertState()
    notified_at: datetime | None = None
    for snapshot in await _demo_snapshots(session, watch):
        record_low_before = baseline.record_low
        ready_before = history_ready(baseline)
        apply_result(baseline, snapshot.price, insights)
        view = BaselineView(baseline.typical_low, record_low_before, ready_before)
        decision = evaluate(state, snapshot.price, watch.target_price, view)
        state = decision.new_state
        if decision.notify:
            await create_alert(
                session,
                watch,
                snapshot.id,
                snapshot.price,
                decision,
                created_at=snapshot.observed_at,
                deliver=False,
            )
            notified_at = snapshot.observed_at
    await save_state(session, watch.id, state, notified_at)


async def ensure_demo_notifications(session: AsyncSession, user: User, today: date) -> None:
    has_notifications = await session.scalar(
        select(func.count()).select_from(Notification).where(Notification.user_id == user.id)
    )
    if has_notifications:
        return
    watches = list(
        (
            await session.scalars(
                select(Watch)
                .where(Watch.user_id == user.id, Watch.status.in_(("active", "expired")))
                .order_by(Watch.id)
            )
        ).unique()
    )
    for watch in watches:
        await _replay_alerts(session, watch)

    active = next(w for w in watches if w.status == "active")
    first_snapshot = (await _demo_snapshots(session, active))[0]
    session.add(
        Notification(
            user_id=user.id,
            type="system",
            title=activated_title(active.price_query),
            body=ACTIVATED_BODY,
            link=watch_link(active),
            created_at=first_snapshot.observed_at - timedelta(days=1),
        )
    )
    await session.flush()

    # 只留最新一則價格通知未讀，讓鈴鐺有未讀數可以展示
    await session.execute(
        update(Notification).where(Notification.user_id == user.id).values(is_read=True)
    )
    latest = await session.scalar(
        select(Notification.id)
        .where(Notification.user_id == user.id, Notification.type == "price_alert")
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(1)
    )
    if latest is not None:
        await session.execute(
            update(Notification).where(Notification.id == latest).values(is_read=False)
        )
    await session.commit()


async def _main() -> None:
    async with get_sessionmaker()() as session:
        user = await ensure_demo_user(session)
        await ensure_demo_watches(session, user, taipei_today())
        await ensure_demo_prices(session, user, taipei_today())
        await ensure_demo_notifications(session, user, taipei_today())
        print(f"示範帳號已就緒：{user.email}（public_id={user.public_id}）")


if __name__ == "__main__":
    # psycopg async 不支援 Windows 預設的 ProactorEventLoop
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(_main(), loop_factory=loop_factory)
