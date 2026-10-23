"""建立示範帳號與示範追蹤，可重複執行：python -m app.seeds.demo（需先執行 app.seeds.reference）"""

import asyncio
import secrets
import sys
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.models  # noqa: F401  獨立執行時也要註冊所有表
from app.core.clock import taipei_today
from app.db.session import get_sessionmaker
from app.modules.auth.security import hash_password
from app.modules.auth.service import DEMO_EMAIL, get_user_by_email
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


async def _main() -> None:
    async with get_sessionmaker()() as session:
        user = await ensure_demo_user(session)
        await ensure_demo_watches(session, user, taipei_today())
        print(f"示範帳號已就緒：{user.email}（public_id={user.public_id}）")


if __name__ == "__main__":
    # psycopg async 不支援 Windows 預設的 ProactorEventLoop
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(_main(), loop_factory=loop_factory)
