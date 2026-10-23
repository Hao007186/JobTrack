"""名額規則：全站鎖、query_hash、佔名額判斷、決定狀態與補位。"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.modules.watches.models import PriceQuery, Watch

MAX_ACTIVE_QUERIES = 8
MAX_WATCHES_PER_USER = 3
# 出發前 2 天停止查價
STOP_CHECK_DAYS = 2
# pg_advisory_xact_lock 的鍵，"FARE" 的 ASCII
WATCH_LOCK_KEY = 0x46415245


@dataclass(frozen=True)
class QueryConditions:
    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    cabin: str
    adults: int
    airlines: tuple[str, ...]
    is_demo: bool

    def query_hash(self) -> str:
        payload = {
            "origin": self.origin,
            "destination": self.destination,
            "depart_date": self.depart_date.isoformat(),
            "return_date": self.return_date.isoformat() if self.return_date else None,
            "cabin": self.cabin,
            "adults": self.adults,
            "airlines": sorted(self.airlines),
            "is_demo": self.is_demo,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


async def acquire_watch_lock(session: AsyncSession) -> None:
    """全站鎖：會影響名額的操作一次只處理一個，transaction 結束時自動釋放。"""
    await session.execute(select(func.pg_advisory_xact_lock(WATCH_LOCK_KEY)))


async def get_or_create_price_query(session: AsyncSession, cond: QueryConditions) -> PriceQuery:
    query_hash = cond.query_hash()
    existing = await session.scalar(select(PriceQuery).where(PriceQuery.query_hash == query_hash))
    if existing is not None:
        return existing
    query = PriceQuery(
        query_hash=query_hash,
        origin=cond.origin,
        destination=cond.destination,
        depart_date=cond.depart_date,
        return_date=cond.return_date,
        cabin=cond.cabin,
        adults=cond.adults,
        airlines=sorted(cond.airlines),
        is_demo=cond.is_demo,
    )
    session.add(query)
    await session.flush()
    return query


def _last_stop_date(today: date) -> date:
    # 出發日 <= 這天的 query 已經停止查價，不佔名額
    return today + timedelta(days=STOP_CHECK_DAYS)


async def occupied_query_ids(session: AsyncSession, today: date) -> set[int]:
    result = await session.scalars(
        select(Watch.price_query_id)
        .join(PriceQuery, Watch.price_query_id == PriceQuery.id)
        .where(
            Watch.status == "active",
            PriceQuery.is_demo.is_(False),
            PriceQuery.depart_date > _last_stop_date(today),
        )
        .distinct()
    )
    return set(result)


async def count_user_slots(session: AsyncSession, user_id: int) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(Watch)
        .where(Watch.user_id == user_id, Watch.status.in_(("active", "queued")))
    )
    return count or 0


async def decide_status(
    session: AsyncSession, query: PriceQuery, today: date
) -> Literal["active", "queued"]:
    occupied = await occupied_query_ids(session, today)
    if query.id in occupied:
        return "active"
    if query.depart_date <= _last_stop_date(today):
        # 啟用了也查不到，等著被標成過期
        return "queued"
    if query.is_demo or len(occupied) < MAX_ACTIVE_QUERIES:
        return "active"
    return "queued"


async def _activate_queued(session: AsyncSession, *conditions: ColumnElement[bool]) -> int:
    ids = await session.scalars(
        update(Watch)
        .where(Watch.status == "queued", *conditions)
        .values(status="active")
        .returning(Watch.id)
    )
    return len(ids.all())


async def rebalance(session: AsyncSession, today: date) -> int:
    """補位：回傳啟用的追蹤數。只 flush，由呼叫端 commit。"""
    occupied = await occupied_query_ids(session, today)
    activated = 0
    if occupied:
        # 對應的 query 已經佔名額（例如別人剛建了相同條件），不用多佔就能啟用
        activated += await _activate_queued(session, Watch.price_query_id.in_(occupied))

    while len(occupied) < MAX_ACTIVE_QUERIES:
        next_query_id = await session.scalar(
            select(Watch.price_query_id)
            .join(PriceQuery, Watch.price_query_id == PriceQuery.id)
            .where(Watch.status == "queued", PriceQuery.depart_date > _last_stop_date(today))
            .order_by(Watch.created_at, Watch.id)
            .limit(1)
        )
        if next_query_id is None:
            break
        # 同一個 query 的排隊者一起啟用
        activated += await _activate_queued(session, Watch.price_query_id == next_query_id)
        occupied = await occupied_query_ids(session, today)
    return activated
