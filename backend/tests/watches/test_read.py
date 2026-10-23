import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User
from tests.watches.conftest import auth_headers, demo_headers, insert_watch

URL = "/api/v1/watches"


async def _user(session: AsyncSession, email: str = "alice@example.com") -> User:
    user = await session.scalar(select(User).where(User.email == email))
    assert user is not None
    return user


async def test_list_only_own(client: AsyncClient, db_session: AsyncSession) -> None:
    alice_headers = await auth_headers(client, db_session)
    await auth_headers(client, db_session, email="bob@example.com")
    mine = await insert_watch(db_session, await _user(db_session))
    await insert_watch(db_session, await _user(db_session, "bob@example.com"), destination="KIX")

    resp = await client.get(URL, headers=alice_headers)
    assert resp.status_code == 200
    assert [w["public_id"] for w in resp.json()] == [str(mine.public_id)]


async def test_list_status_filter(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    alice = await _user(db_session)
    await insert_watch(db_session, alice, status="active", destination="NRT")
    await insert_watch(db_session, alice, status="paused", destination="KIX")
    await insert_watch(db_session, alice, status="expired", destination="ICN")

    expired = await client.get(URL, params={"status": "expired"}, headers=headers)
    assert [w["status"] for w in expired.json()] == ["expired"]
    current = await client.get(
        URL, params=[("status", "active"), ("status", "paused")], headers=headers
    )
    assert sorted(w["status"] for w in current.json()) == ["active", "paused"]
    assert len((await client.get(URL, headers=headers)).json()) == 3
    bogus = await client.get(URL, params={"status": "bogus"}, headers=headers)
    assert bogus.status_code == 422


async def test_list_newest_first(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    alice = await _user(db_session)
    base = datetime(2026, 10, 1, tzinfo=UTC)
    old = await insert_watch(db_session, alice, destination="NRT", created_at=base)
    new = await insert_watch(
        db_session, alice, destination="KIX", created_at=base + timedelta(days=1)
    )
    resp = await client.get(URL, headers=headers)
    assert [w["public_id"] for w in resp.json()] == [str(new.public_id), str(old.public_id)]


async def test_get_other_users_watch_404(client: AsyncClient, db_session: AsyncSession) -> None:
    await auth_headers(client, db_session)
    bob_headers = await auth_headers(client, db_session, email="bob@example.com")
    alices = await insert_watch(db_session, await _user(db_session))

    resp = await client.get(f"{URL}/{alices.public_id}", headers=bob_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "找不到追蹤"
    assert (await client.get(f"{URL}/{uuid.uuid4()}", headers=bob_headers)).status_code == 404


async def test_get_own_watch(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    watch = await insert_watch(db_session, await _user(db_session))
    resp = await client.get(f"{URL}/{watch.public_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["destination"] == "NRT"


async def test_demo_can_read(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await demo_headers(client, db_session)
    assert (await client.get(URL, headers=headers)).status_code == 200
