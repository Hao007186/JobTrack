from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.prices.models import ApiUsage, PriceBaseline, PriceSnapshot
from app.modules.watches.models import PriceQuery
from app.modules.watches.slots import get_or_create_price_query
from tests.prices.conftest import conditions

NOW = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)


async def _query(session: AsyncSession) -> PriceQuery:
    return await get_or_create_price_query(session, conditions())


async def test_snapshot_and_baseline_defaults(db_session: AsyncSession) -> None:
    query = await _query(db_session)
    db_session.add(
        PriceSnapshot(
            price_query_id=query.id,
            provider="mock",
            price=9000,
            airline_iata=None,
            stops=0,
            booking_url=None,
            observed_at=NOW,
        )
    )
    baseline = PriceBaseline(price_query_id=query.id)
    db_session.add(baseline)
    await db_session.flush()
    await db_session.refresh(baseline)
    await db_session.refresh(query)
    assert baseline.history_seeded is False
    assert baseline.sample_count == 0
    assert baseline.record_low is None
    assert query.last_checked_at is None


async def test_snapshot_price_positive(db_session: AsyncSession) -> None:
    query = await _query(db_session)
    db_session.add(
        PriceSnapshot(price_query_id=query.id, provider="mock", price=0, stops=0, observed_at=NOW)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_api_usage_pk(db_session: AsyncSession) -> None:
    db_session.add(ApiUsage(provider="serpapi", month="2026-11", count=1))
    await db_session.flush()
    db_session.add(ApiUsage(provider="serpapi", month="2026-11", count=1))
    with pytest.raises(IntegrityError):
        await db_session.flush()
