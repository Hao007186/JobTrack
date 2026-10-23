from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.prices.checker import (
    CheckSummary,
    claim_query,
    due_queries,
    run_checks,
    usage_month,
)
from app.modules.prices.models import ApiUsage, PriceBaseline, PriceSnapshot
from app.modules.prices.providers.base import ProviderError, SearchResult
from app.modules.users.models import User
from app.modules.watches.models import PriceQuery, Watch
from tests.conftest import create_user
from tests.prices.conftest import TODAY, FakeProvider, insert_watch

# 台灣時間 2026-11-01 10:00
NOW = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)
DESTS = ["NRT", "KIX", "ICN", "HKG", "BKK"]


def taipei(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=UTC) - timedelta(hours=8)


async def _user(session: AsyncSession) -> User:
    return await create_user(session)


async def _set_checked(session: AsyncSession, query_id: int, at: datetime | None) -> None:
    await session.execute(
        update(PriceQuery).where(PriceQuery.id == query_id).values(last_checked_at=at)
    )


async def _query(session: AsyncSession, query_id: int) -> PriceQuery:
    q = await session.scalar(
        select(PriceQuery)
        .where(PriceQuery.id == query_id)
        .execution_options(populate_existing=True)
    )
    assert q is not None
    return q


async def _run(session: AsyncSession, provider: FakeProvider) -> CheckSummary:
    return await run_checks(session, provider, TODAY, now=lambda: NOW)


async def test_due_queries_filters(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    due = await insert_watch(db_session, user, destination="NRT")
    await insert_watch(db_session, user, status="paused", destination="KIX")
    await insert_watch(db_session, user, status="queued", destination="ICN")
    await insert_watch(db_session, user, destination="HKG", is_demo=True)
    await insert_watch(db_session, user, destination="BKK", depart_date=TODAY + timedelta(days=2))
    checked = await insert_watch(db_session, user, destination="SIN")
    await _set_checked(db_session, checked.price_query_id, taipei(2026, 11, 1, 8))

    assert [q.id for q in await due_queries(db_session, TODAY)] == [due.price_query_id]


async def test_due_queries_order(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    older = await insert_watch(db_session, user, destination="NRT")
    never = await insert_watch(db_session, user, destination="KIX")
    newer = await insert_watch(db_session, user, destination="ICN")
    await _set_checked(db_session, older.price_query_id, taipei(2026, 10, 29, 10))
    await _set_checked(db_session, newer.price_query_id, taipei(2026, 10, 31, 10))

    ids = [q.id for q in await due_queries(db_session, TODAY)]
    assert ids == [never.price_query_id, older.price_query_id, newer.price_query_id]


async def test_checked_today_boundary(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    yesterday_late = await insert_watch(db_session, user, destination="NRT")
    today_early = await insert_watch(db_session, user, destination="KIX")
    await _set_checked(db_session, yesterday_late.price_query_id, taipei(2026, 10, 31, 23, 50))
    await _set_checked(db_session, today_early.price_query_id, taipei(2026, 11, 1, 0, 10))

    ids = [q.id for q in await due_queries(db_session, TODAY)]
    assert ids == [yesterday_late.price_query_id]


async def test_run_checks_records(db_session: AsyncSession) -> None:
    watch = await insert_watch(db_session, await _user(db_session))
    summary = await _run(db_session, FakeProvider(remaining=None))
    assert summary.checked == 1

    snapshots = (await db_session.scalars(select(PriceSnapshot))).all()
    assert [(s.price, s.provider, s.airline_iata) for s in snapshots] == [(9000, "fake", "BR")]
    baseline = await db_session.get(PriceBaseline, watch.price_query_id)
    assert baseline is not None and baseline.sample_count == 1
    assert (await _query(db_session, watch.price_query_id)).last_checked_at == NOW
    usage = await db_session.get(ApiUsage, ("fake", "2026-11"))
    assert usage is not None and usage.count == 1


async def test_budget_limits_checks(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    for dest in DESTS:
        await insert_watch(db_session, user, destination=dest)
    provider = FakeProvider(remaining=10)  # 11 月剩 30 天 → ceil(10/30) = 1
    summary = await _run(db_session, provider)
    assert len(provider.calls) == 1
    assert summary.checked == 1
    assert summary.remaining == 10


async def test_mock_unlimited(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    for dest in DESTS[:3]:
        await insert_watch(db_session, user, destination=dest)
    provider = FakeProvider(remaining=None)
    await _run(db_session, provider)
    assert len(provider.calls) == 3


async def test_zero_remaining(db_session: AsyncSession) -> None:
    await insert_watch(db_session, await _user(db_session))
    provider = FakeProvider(remaining=0)
    summary = await _run(db_session, provider)
    assert provider.calls == []
    assert summary.checked == 0


async def test_remaining_failure_raises(db_session: AsyncSession) -> None:
    await insert_watch(db_session, await _user(db_session))
    provider = FakeProvider(remaining=ProviderError("account down"))
    with pytest.raises(ProviderError):
        await _run(db_session, provider)
    assert provider.calls == []


async def test_claim_query(db_session: AsyncSession) -> None:
    watch = await insert_watch(db_session, await _user(db_session))
    assert await claim_query(db_session, watch.price_query_id, TODAY, NOW) == (True, None)
    later = NOW + timedelta(minutes=5)
    assert await claim_query(db_session, watch.price_query_id, TODAY, later) == (False, NOW)


async def test_claim_conflict_skips(db_session: AsyncSession) -> None:
    watch = await insert_watch(db_session, await _user(db_session))

    async def other_process_claims() -> None:
        await _set_checked(db_session, watch.price_query_id, taipei(2026, 11, 1, 8))

    provider = FakeProvider(remaining=None, on_remaining=other_process_claims)
    summary = await _run(db_session, provider)
    assert summary.skipped == 1
    assert provider.calls == []


async def test_failure_restores_last_checked(db_session: AsyncSession) -> None:
    watch = await insert_watch(db_session, await _user(db_session))
    before = taipei(2026, 10, 30, 10)
    await _set_checked(db_session, watch.price_query_id, before)
    provider = FakeProvider(remaining=None, default=ProviderError("timeout"))

    summary = await _run(db_session, provider)
    assert summary.failed == 1
    assert (await _query(db_session, watch.price_query_id)).last_checked_at == before
    assert await db_session.get(ApiUsage, ("fake", "2026-11")) is None
    assert (await db_session.scalars(select(PriceSnapshot))).all() == []


async def test_stops_after_three_failures(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    for dest in DESTS:
        await insert_watch(db_session, user, destination=dest)
    provider = FakeProvider(remaining=None, default=ProviderError("down"))
    summary = await _run(db_session, provider)
    assert len(provider.calls) == 3
    assert summary.failed == 3


async def test_no_result_counts_usage(db_session: AsyncSession) -> None:
    watch = await insert_watch(db_session, await _user(db_session))
    provider = FakeProvider(remaining=None, default=SearchResult(None, None, None))
    summary = await _run(db_session, provider)
    assert summary.no_result == 1
    assert (await db_session.scalars(select(PriceSnapshot))).all() == []
    assert await db_session.get(PriceBaseline, watch.price_query_id) is None
    usage = await db_session.get(ApiUsage, ("fake", "2026-11"))
    assert usage is not None and usage.count == 1
    assert (await _query(db_session, watch.price_query_id)).last_checked_at == NOW


async def test_usage_month_taipei() -> None:
    assert usage_month(datetime(2026, 10, 31, 16, 10, tzinfo=UTC)) == "2026-11"
    assert usage_month(datetime(2026, 10, 31, 15, 50, tzinfo=UTC)) == "2026-10"


async def test_watch_rows_untouched(db_session: AsyncSession) -> None:
    watch = await insert_watch(db_session, await _user(db_session))
    await _run(db_session, FakeProvider(remaining=None))
    await db_session.refresh(watch)
    assert isinstance(watch, Watch) and watch.status == "active"
