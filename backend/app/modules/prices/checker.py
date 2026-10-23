"""每日查價：找出要查的 query → 搶下 → 呼叫查價來源 → 記錄。每個 query 各自 commit。"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.core.clock import TAIPEI_TZ
from app.modules.prices.baseline import apply_result
from app.modules.prices.budget import daily_budget
from app.modules.prices.models import ApiUsage, PriceBaseline, PriceSnapshot
from app.modules.prices.providers.base import PriceProvider, ProviderError, SearchResult
from app.modules.watches.models import PriceQuery, Watch
from app.modules.watches.service import conditions_of
from app.modules.watches.slots import STOP_CHECK_DAYS

logger = logging.getLogger(__name__)

# 連續失敗這麼多次通常是 SerpApi 掛了或 key 有問題，不要一直撞
MAX_CONSECUTIVE_FAILURES = 3


@dataclass
class CheckSummary:
    checked: int = 0
    no_result: int = 0
    failed: int = 0
    skipped: int = 0
    remaining: int | None = None


def today_start(today: date) -> datetime:
    """台灣時間今天 00:00。"""
    return datetime.combine(today, time(0), tzinfo=TAIPEI_TZ)


def usage_month(now: datetime) -> str:
    return now.astimezone(TAIPEI_TZ).strftime("%Y-%m")


def _not_checked_today(today: date) -> ColumnElement[bool]:
    return or_(
        PriceQuery.last_checked_at.is_(None),
        PriceQuery.last_checked_at < today_start(today),
    )


async def due_queries(session: AsyncSession, today: date) -> list[PriceQuery]:
    has_active_watch = exists().where(
        Watch.price_query_id == PriceQuery.id, Watch.status == "active"
    )
    result = await session.scalars(
        select(PriceQuery)
        .where(
            has_active_watch,
            PriceQuery.is_demo.is_(False),
            PriceQuery.depart_date > today + timedelta(days=STOP_CHECK_DAYS),
            _not_checked_today(today),
        )
        .order_by(PriceQuery.last_checked_at.asc().nulls_first(), PriceQuery.id)
        .execution_options(populate_existing=True)
    )
    return list(result)


async def claim_query(
    session: AsyncSession, query_id: int, today: date, now: datetime
) -> tuple[bool, datetime | None]:
    """搶下這個 query：今天還沒被查過才搶得到。回傳（是否搶到、原本的 last_checked_at）。"""
    previous = await session.scalar(
        select(PriceQuery.last_checked_at)
        .where(PriceQuery.id == query_id)
        .execution_options(populate_existing=True)
    )
    claimed = await session.scalar(
        update(PriceQuery)
        .where(PriceQuery.id == query_id, _not_checked_today(today))
        .values(last_checked_at=now)
        .returning(PriceQuery.id)
    )
    await session.commit()
    return claimed is not None, previous


async def _restore(session: AsyncSession, query_id: int, previous: datetime | None) -> None:
    await session.execute(
        update(PriceQuery).where(PriceQuery.id == query_id).values(last_checked_at=previous)
    )
    await session.commit()


async def record_result(
    session: AsyncSession,
    query: PriceQuery,
    provider_name: str,
    result: SearchResult,
    now: datetime,
) -> None:
    if result.lowest is not None:
        session.add(
            PriceSnapshot(
                price_query_id=query.id,
                provider=provider_name,
                price=result.lowest.price,
                airline_iata=result.lowest.airline_iata,
                stops=result.lowest.stops,
                booking_url=result.booking_url,
                observed_at=now,
            )
        )
        baseline = await session.get(PriceBaseline, query.id, populate_existing=True)
        if baseline is None:
            baseline = PriceBaseline(price_query_id=query.id, history_seeded=False, sample_count=0)
            session.add(baseline)
        apply_result(baseline, result.lowest.price, result.insights)

    # 查不到航班也算一次呼叫（額度已花）
    stmt = insert(ApiUsage).values(provider=provider_name, month=usage_month(now), count=1)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[ApiUsage.provider, ApiUsage.month],
            set_={"count": ApiUsage.count + 1},
        )
    )
    await session.commit()


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def run_checks(
    session: AsyncSession,
    provider: PriceProvider,
    today: date,
    now: Callable[[], datetime] = _utcnow,
) -> CheckSummary:
    """remaining_quota 失敗時 ProviderError 往外拋，這次完全不查。"""
    queries = await due_queries(session, today)
    remaining = await provider.remaining_quota()
    summary = CheckSummary(remaining=remaining)

    if remaining is None:
        budget = len(queries)
    elif remaining == 0:
        logger.warning("本月額度已用完")
        budget = 0
    else:
        budget = daily_budget(remaining, today)

    consecutive_failures = 0
    for query in queries[:budget]:
        claimed, previous = await claim_query(session, query.id, today, now())
        if not claimed:
            summary.skipped += 1
            continue
        try:
            result = await provider.search(conditions_of(query))
        except ProviderError as e:
            logger.warning("查價失敗（query %s）：%s", query.id, e)
            await _restore(session, query.id, previous)
            summary.failed += 1
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.error("連續 %s 次失敗，停止這次查價", consecutive_failures)
                break
            continue

        consecutive_failures = 0
        await record_result(session, query, provider.name, result, now())
        if result.lowest is None:
            summary.no_result += 1
        else:
            summary.checked += 1
    return summary
