from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.prices.models import PriceBaseline, PriceSnapshot
from app.modules.users.models import User
from app.modules.watches.models import PriceQuery, Watch
from app.seeds.demo import ensure_demo_user
from tests.conftest import create_user
from tests.prices.conftest import auth_headers, demo_headers, insert_watch

URL = "/api/v1/watches"


async def _alice(session: AsyncSession) -> User:
    user = await session.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    return user


def _snapshot(watch: Watch, days_ago: int, price: int) -> PriceSnapshot:
    return PriceSnapshot(
        price_query_id=watch.price_query_id,
        provider="mock",
        price=price,
        airline_iata="BR",
        stops=0,
        booking_url=None,
        observed_at=datetime.now(UTC) - timedelta(days=days_ago),
    )


async def test_prices_range(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(db_session, await _alice(db_session))
    db_session.add_all(
        [_snapshot(watch, 100, 9100), _snapshot(watch, 10, 8800), _snapshot(watch, 40, 9500)]
    )
    await db_session.flush()

    default = (await client.get(f"{URL}/{watch.public_id}/prices", headers=headers)).json()
    assert [p["price"] for p in default] == [9500, 8800]
    assert default[0]["airline_iata"] == "BR"
    month = await client.get(f"{URL}/{watch.public_id}/prices?range=30d", headers=headers)
    assert [p["price"] for p in month.json()] == [8800]
    everything = await client.get(f"{URL}/{watch.public_id}/prices?range=all", headers=headers)
    assert [p["price"] for p in everything.json()] == [9100, 9500, 8800]
    bad = await client.get(f"{URL}/{watch.public_id}/prices?range=7d", headers=headers)
    assert bad.status_code == 422


async def test_prices_only_own(client: AsyncClient, db_session: AsyncSession) -> None:
    await auth_headers(client, db_session)
    bob_headers = await auth_headers(client, db_session, email="bob@example.com")
    watch = await insert_watch(db_session, await _alice(db_session))
    for path in ("prices", "baseline"):
        resp = await client.get(f"{URL}/{watch.public_id}/{path}", headers=bob_headers)
        assert resp.status_code == 404


async def test_baseline(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(db_session, await _alice(db_session))
    checked_at = datetime(2026, 10, 31, 2, 0, tzinfo=UTC)
    await db_session.execute(
        update(PriceQuery)
        .where(PriceQuery.id == watch.price_query_id)
        .values(last_checked_at=checked_at)
    )
    db_session.add_all(
        [
            _snapshot(watch, 2, 9100),
            _snapshot(watch, 1, 8800),
            PriceBaseline(
                price_query_id=watch.price_query_id,
                typical_low=6400,
                typical_high=12500,
                record_low=8000,
                history_seeded=True,
                sample_count=1,
            ),
        ]
    )
    await db_session.flush()

    body = (await client.get(f"{URL}/{watch.public_id}/baseline", headers=headers)).json()
    assert body["latest_price"] == 8800
    assert body["latest_observed_at"] is not None
    assert datetime.fromisoformat(body["last_checked_at"]) == checked_at
    assert (body["typical_low"], body["typical_high"], body["record_low"]) == (6400, 12500, 8000)
    assert body["history_ready"] is True


async def test_baseline_empty(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(db_session, await _alice(db_session))
    body = (await client.get(f"{URL}/{watch.public_id}/baseline", headers=headers)).json()
    assert body == {
        "latest_price": None,
        "latest_observed_at": None,
        "last_checked_at": None,
        "typical_low": None,
        "typical_high": None,
        "record_low": None,
        "history_ready": False,
    }


async def test_demo_can_read_prices(client: AsyncClient, db_session: AsyncSession) -> None:
    demo = await ensure_demo_user(db_session)
    watch = await insert_watch(db_session, demo, is_demo=True)
    headers = await demo_headers(client, db_session)
    resp = await client.get(f"{URL}/{watch.public_id}/prices", headers=headers)
    assert resp.status_code == 200
    assert (
        await client.get(f"{URL}/{watch.public_id}/baseline", headers=headers)
    ).status_code == 200


async def test_prices_requires_login(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await create_user(db_session, email="owner@example.com")
    watch = await insert_watch(db_session, owner)
    assert (await client.get(f"{URL}/{watch.public_id}/prices")).status_code == 401
