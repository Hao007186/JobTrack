import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User
from app.modules.watches.models import PriceQuery, Watch
from tests.conftest import create_user
from tests.watches.conftest import conditions


def _query(**overrides: Any) -> PriceQuery:
    cond = conditions()
    fields: dict[str, Any] = {
        "query_hash": cond.query_hash(),
        "origin": cond.origin,
        "destination": cond.destination,
        "depart_date": cond.depart_date,
        "return_date": cond.return_date,
        "cabin": cond.cabin,
        "adults": cond.adults,
    }
    fields.update(overrides)
    return PriceQuery(**fields)


async def _watch(session: AsyncSession, user: User, **overrides: Any) -> Watch:
    query = _query()
    session.add(query)
    await session.flush()
    fields: dict[str, Any] = {
        "user_id": user.id,
        "price_query_id": query.id,
        "target_price": 9000,
        "status": "active",
    }
    fields.update(overrides)
    watch = Watch(**fields)
    session.add(watch)
    await session.flush()
    return watch


async def test_watch_defaults(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    watch = await _watch(db_session, user)
    await db_session.refresh(watch)
    assert isinstance(watch.public_id, uuid.UUID)
    assert watch.price_query.origin == "TPE"
    assert watch.price_query.airlines == []
    assert watch.price_query.is_demo is False


@pytest.mark.parametrize(
    ("query_fields", "watch_fields"),
    [
        ({"cabin": "vip"}, {}),
        ({"adults": 0}, {}),
        ({"adults": 10}, {}),
        ({}, {"target_price": 0}),
        ({}, {"status": "deleted"}),
    ],
    ids=["cabin", "adults-0", "adults-10", "target-price", "status"],
)
async def test_check_constraints(
    db_session: AsyncSession, query_fields: dict[str, Any], watch_fields: dict[str, Any]
) -> None:
    user = await create_user(db_session)
    query = _query(**query_fields)
    db_session.add(query)
    with pytest.raises(IntegrityError):
        await db_session.flush()
        fields: dict[str, Any] = {
            "user_id": user.id,
            "price_query_id": query.id,
            "target_price": 9000,
            "status": "active",
        }
        fields.update(watch_fields)
        db_session.add(Watch(**fields))
        await db_session.flush()


async def test_query_hash_unique(db_session: AsyncSession) -> None:
    db_session.add(_query())
    await db_session.flush()
    db_session.add(_query())
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_user_delete_cascades_watches(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    await _watch(db_session, user)
    await db_session.delete(user)
    await db_session.flush()
    db_session.expunge_all()
    assert (await db_session.scalars(select(Watch))).all() == []
