"""追蹤的操作流程。每個寫入操作：拿全站鎖 → 改資料 → 補位 → commit 一次。"""

import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reference.models import ORIGIN_COUNTRY, Airline, Airport
from app.modules.users.models import User
from app.modules.watches import slots
from app.modules.watches.models import PriceQuery, Watch
from app.modules.watches.schemas import WatchCreate, WatchUpdate
from app.modules.watches.slots import QueryConditions

MIN_DAYS_AHEAD = 3
MAX_DAYS_AHEAD = 330
# WatchUpdate 中屬於查價條件的欄位
_CONDITION_FIELDS = ("origin", "destination", "depart_date", "return_date", "cabin", "adults")


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


def _merged_conditions(old: QueryConditions, data: WatchUpdate) -> QueryConditions:
    sent = data.model_fields_set
    changes: dict[str, object] = {}
    for field in _CONDITION_FIELDS:
        value = getattr(data, field)
        # return_date 送 null 代表改成單程；其他欄位送 null 視為不改
        if field in sent and (value is not None or field == "return_date"):
            changes[field] = value
    if "airlines" in sent and data.airlines is not None:
        changes["airlines"] = tuple(data.airlines)
    return replace(old, **changes)  # type: ignore[arg-type]


async def update_watch(
    session: AsyncSession, user: User, public_id: uuid.UUID, data: WatchUpdate, today: date
) -> Watch:
    await slots.acquire_watch_lock(session)
    watch = await get_watch(session, user, public_id)
    if watch.status == "expired":
        raise WatchExpired

    old = conditions_of(watch.price_query)
    new = _merged_conditions(old, data)
    # 比較值而不是看有沒有送：前端可能把整份表單原封不動送回
    if new != old:
        await validate_conditions(session, new, today)
        query = await slots.get_or_create_price_query(session, new)
        watch.price_query = query
        if watch.status != "paused":
            # 先視為不佔名額，再依新條件決定狀態
            watch.status = "queued"
            await session.flush()
            watch.status = await slots.decide_status(session, query, today)

    if data.target_price is not None:
        watch.target_price = data.target_price

    if data.status == "paused" and watch.status in ("active", "queued"):
        watch.status = "paused"
    elif data.status == "active" and watch.status == "paused":
        if await slots.count_user_slots(session, user.id) >= slots.MAX_WATCHES_PER_USER:
            raise WatchLimitReached
        watch.status = await slots.decide_status(session, watch.price_query, today)

    await session.flush()
    await slots.rebalance(session, today)
    await session.commit()
    return await get_watch(session, user, public_id)


async def delete_watch(
    session: AsyncSession, user: User, public_id: uuid.UUID, today: date
) -> None:
    await slots.acquire_watch_lock(session)
    watch = await get_watch(session, user, public_id)
    # price_query 保留，之後的價格歷史會掛在它上面
    await session.delete(watch)
    await session.flush()
    await slots.rebalance(session, today)
    await session.commit()


async def expire_watches(session: AsyncSession, today: date) -> tuple[int, int]:
    """每日維護：出發日已過的追蹤標成 expired 再補位。回傳（過期數、啟用數）。"""
    await slots.acquire_watch_lock(session)
    past_queries = select(PriceQuery.id).where(PriceQuery.depart_date < today)
    expired = await session.scalars(
        update(Watch)
        .where(Watch.status != "expired", Watch.price_query_id.in_(past_queries))
        .values(status="expired")
        .returning(Watch.id)
    )
    expired_count = len(expired.all())
    activated = await slots.rebalance(session, today)
    await session.commit()
    return expired_count, activated
