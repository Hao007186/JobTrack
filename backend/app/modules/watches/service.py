"""追蹤的操作流程。每個寫入操作：拿全站鎖 → 改資料 → 補位 → commit 一次。"""

import uuid
from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reference.models import ORIGIN_COUNTRY, Airline, Airport
from app.modules.users.models import User
from app.modules.watches import slots
from app.modules.watches.models import PriceQuery, Watch
from app.modules.watches.schemas import WatchCreate
from app.modules.watches.slots import QueryConditions

MIN_DAYS_AHEAD = 3
MAX_DAYS_AHEAD = 330


class WatchNotFound(Exception):
    pass


class WatchLimitReached(Exception):
    pass


class WatchExpired(Exception):
    pass


class InvalidWatchInput(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def conditions_of(query: PriceQuery) -> QueryConditions:
    return QueryConditions(
        origin=query.origin,
        destination=query.destination,
        depart_date=query.depart_date,
        return_date=query.return_date,
        cabin=query.cabin,
        adults=query.adults,
        airlines=tuple(query.airlines),
        is_demo=query.is_demo,
    )


async def validate_conditions(session: AsyncSession, cond: QueryConditions, today: date) -> None:
    earliest = today + timedelta(days=MIN_DAYS_AHEAD)
    latest = today + timedelta(days=MAX_DAYS_AHEAD)
    if not earliest <= cond.depart_date <= latest:
        raise InvalidWatchInput(f"depart_date：出發日必須在 {earliest} 到 {latest} 之間")
    if cond.return_date is not None:
        if cond.return_date < cond.depart_date:
            raise InvalidWatchInput("return_date：回程日不能早於出發日")
        if cond.return_date > latest:
            raise InvalidWatchInput(f"return_date：回程日不能晚於 {latest}")
    if cond.origin == cond.destination:
        raise InvalidWatchInput("destination：目的地不能和出發地相同")

    origin = await session.get(Airport, cond.origin)
    if origin is None or origin.country != ORIGIN_COUNTRY:
        raise InvalidWatchInput("origin：出發地必須是台灣的機場")
    if await session.get(Airport, cond.destination) is None:
        raise InvalidWatchInput("destination：不支援這個目的地")
    if cond.airlines:
        found = await session.scalar(
            select(func.count()).select_from(Airline).where(Airline.iata.in_(cond.airlines))
        )
        if found != len(cond.airlines):
            raise InvalidWatchInput("airlines：包含不支援的航空公司")


async def create_watch(session: AsyncSession, user: User, data: WatchCreate, today: date) -> Watch:
    await slots.acquire_watch_lock(session)
    if await slots.count_user_slots(session, user.id) >= slots.MAX_WATCHES_PER_USER:
        raise WatchLimitReached
    cond = QueryConditions(
        origin=data.origin,
        destination=data.destination,
        depart_date=data.depart_date,
        return_date=data.return_date,
        cabin=data.cabin,
        adults=data.adults,
        airlines=tuple(data.airlines),
        is_demo=user.is_demo,
    )
    await validate_conditions(session, cond, today)
    query = await slots.get_or_create_price_query(session, cond)
    watch = Watch(
        user_id=user.id,
        price_query_id=query.id,
        target_price=data.target_price,
        status=await slots.decide_status(session, query, today),
    )
    session.add(watch)
    await session.flush()
    await slots.rebalance(session, today)
    await session.commit()
    return await get_watch(session, user, watch.public_id)


async def list_watches(
    session: AsyncSession, user: User, statuses: Sequence[str] | None
) -> list[Watch]:
    stmt = select(Watch).where(Watch.user_id == user.id)
    if statuses:
        stmt = stmt.where(Watch.status.in_(statuses))
    stmt = stmt.order_by(Watch.created_at.desc(), Watch.id.desc()).execution_options(
        populate_existing=True
    )
    return list((await session.scalars(stmt)).unique())


async def get_watch(session: AsyncSession, user: User, public_id: uuid.UUID) -> Watch:
    watch = await session.scalar(
        select(Watch)
        .where(Watch.public_id == public_id, Watch.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    # 別人的追蹤也回「找不到」，不透露它存在
    if watch is None:
        raise WatchNotFound
    return watch
