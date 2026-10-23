from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User
from app.modules.watches.models import Watch
from app.modules.watches.slots import QueryConditions, get_or_create_price_query
from app.seeds.reference import seed_reference
from tests.conftest import create_user

TODAY = date(2026, 11, 1)
# 預設條件用 NRT，佈置其他 query 時從這裡取不同的目的地
OTHER_DESTINATIONS = ["KIX", "ICN", "HKG", "BKK", "SIN", "OKA", "FUK", "CTS", "HND", "PUS"]

_BASE = QueryConditions(
    origin="TPE",
    destination="NRT",
    depart_date=TODAY + timedelta(days=30),
    return_date=None,
    cabin="economy",
    adults=1,
    airlines=(),
    is_demo=False,
)


@pytest.fixture(autouse=True)
async def reference(db_session: AsyncSession) -> None:
    await seed_reference(db_session)


def conditions(**overrides: Any) -> QueryConditions:
    return replace(_BASE, **overrides)


async def insert_watch(
    session: AsyncSession,
    user: User,
    *,
    status: str = "active",
    created_at: datetime | None = None,
    target_price: int = 9000,
    **cond_overrides: Any,
) -> Watch:
    """直接寫 DB、不經過名額規則，用來佈置測試情境。"""
    query = await get_or_create_price_query(session, conditions(**cond_overrides))
    watch = Watch(
        user_id=user.id, price_query_id=query.id, target_price=target_price, status=status
    )
    if created_at is not None:
        watch.created_at = created_at
    session.add(watch)
    await session.flush()
    await session.refresh(watch)
    return watch


async def fill_slots(session: AsyncSession, count: int = 8) -> list[Watch]:
    """由另一位使用者佔滿 count 個不同 query 的名額。"""
    owner = await create_user(session, email=f"filler{count}@example.com")
    return [
        await insert_watch(session, owner, destination=dest) for dest in OTHER_DESTINATIONS[:count]
    ]
