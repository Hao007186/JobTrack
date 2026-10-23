from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User
from app.modules.watches.models import PriceQuery, Watch
from tests.conftest import create_user
from tests.watches.conftest import auth_headers, demo_headers, fill_slots, insert_watch

URL = "/api/v1/watches"


async def _alice(session: AsyncSession) -> User:
    user = await session.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    return user


async def test_delete(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(db_session, await _alice(db_session))
    query_id = watch.price_query_id
    resp = await client.delete(f"{URL}/{watch.public_id}", headers=headers)
    assert resp.status_code == 204
    assert (await client.get(f"{URL}/{watch.public_id}", headers=headers)).status_code == 404
    assert await db_session.get(PriceQuery, query_id) is not None


async def test_delete_promotes_queued(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    alice = await _alice(db_session)
    mine = await insert_watch(db_session, alice)
    await fill_slots(db_session, 7)
    queued = await insert_watch(db_session, alice, status="queued", destination="PUS")

    assert (await client.delete(f"{URL}/{mine.public_id}", headers=headers)).status_code == 204
    status = await db_session.scalar(
        select(Watch.status).where(Watch.id == queued.id).execution_options(populate_existing=True)
    )
    assert status == "active"


async def test_delete_expired_allowed(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(db_session, await _alice(db_session), status="expired")
    assert (await client.delete(f"{URL}/{watch.public_id}", headers=headers)).status_code == 204


async def test_delete_other_users_404(client: AsyncClient, db_session: AsyncSession) -> None:
    await auth_headers(client, db_session)
    bob_headers = await auth_headers(client, db_session, email="bob@example.com")
    watch = await insert_watch(db_session, await _alice(db_session))
    resp = await client.delete(f"{URL}/{watch.public_id}", headers=bob_headers)
    assert resp.status_code == 404


async def test_demo_cannot_delete(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await create_user(db_session, email="owner@example.com")
    watch = await insert_watch(db_session, owner)
    headers = await demo_headers(client, db_session)
    assert (await client.delete(f"{URL}/{watch.public_id}", headers=headers)).status_code == 403
