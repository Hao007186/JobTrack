import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.auth.deps import CurrentUser
from app.modules.prices.baseline import history_ready
from app.modules.prices.models import PriceBaseline, PriceSnapshot
from app.modules.prices.schemas import BaselineOut, PricePoint, PriceRange
from app.modules.users.models import User
from app.modules.watches import service as watch_service
from app.modules.watches.models import Watch

router = APIRouter(prefix="/watches", tags=["prices"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
_RANGE_DAYS = {"30d": 30, "90d": 90}


async def _own_watch(session: AsyncSession, user: User, public_id: uuid.UUID) -> Watch:
    try:
        return await watch_service.get_watch(session, user, public_id)
    except watch_service.WatchNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到追蹤") from None


@router.get("/{public_id}/prices")
async def list_prices(
    public_id: uuid.UUID, user: CurrentUser, session: SessionDep, range: PriceRange = "90d"
) -> list[PricePoint]:
    watch = await _own_watch(session, user, public_id)
    stmt = select(PriceSnapshot).where(PriceSnapshot.price_query_id == watch.price_query_id)
    if range in _RANGE_DAYS:
        since = datetime.now(UTC) - timedelta(days=_RANGE_DAYS[range])
        stmt = stmt.where(PriceSnapshot.observed_at >= since)
    snapshots = await session.scalars(stmt.order_by(PriceSnapshot.observed_at, PriceSnapshot.id))
    return [
        PricePoint(observed_at=s.observed_at, price=s.price, airline_iata=s.airline_iata)
        for s in snapshots
    ]


@router.get("/{public_id}/baseline")
async def get_baseline(public_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> BaselineOut:
    watch = await _own_watch(session, user, public_id)
    query_id = watch.price_query_id
    latest = await session.scalar(
        select(PriceSnapshot)
        .where(PriceSnapshot.price_query_id == query_id)
        .order_by(PriceSnapshot.observed_at.desc(), PriceSnapshot.id.desc())
        .limit(1)
    )
    baseline = await session.get(PriceBaseline, query_id, populate_existing=True)
    return BaselineOut(
        latest_price=latest.price if latest else None,
        latest_observed_at=latest.observed_at if latest else None,
        last_checked_at=watch.price_query.last_checked_at,
        typical_low=baseline.typical_low if baseline else None,
        typical_high=baseline.typical_high if baseline else None,
        record_low=baseline.record_low if baseline else None,
        history_ready=history_ready(baseline),
    )
