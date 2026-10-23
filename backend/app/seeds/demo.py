"""建立示範帳號與示範追蹤，可重複執行：python -m app.seeds.demo（需先執行 app.seeds.reference）"""

import asyncio
import secrets
import sys
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.models  # noqa: F401  獨立執行時也要註冊所有表
from app.core.clock import TAIPEI_TZ, taipei_today
from app.db.session import get_sessionmaker
from app.modules.auth.security import hash_password
from app.modules.auth.service import DEMO_EMAIL, get_user_by_email
from app.modules.prices.baseline import apply_result
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


async def _main() -> None:
    async with get_sessionmaker()() as session:
        user = await ensure_demo_user(session)
        await ensure_demo_watches(session, user, taipei_today())
        await ensure_demo_prices(session, user, taipei_today())
        print(f"示範帳號已就緒：{user.email}（public_id={user.public_id}）")


if __name__ == "__main__":
    # psycopg async 不支援 Windows 預設的 ProactorEventLoop
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(_main(), loop_factory=loop_factory)
