from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.rules import AlertState, Decision
from app.modules.alerts.service import create_alert
from app.modules.notifications.models import Notification
from app.modules.prices.models import PriceSnapshot
from app.modules.users.models import User
from app.modules.watches.models import Watch
from tests.conftest import create_user
from tests.notifications.conftest import auth_headers, demo_headers, insert_watch

URL = "/api/v1/notifications"
SETTINGS_URL = "/api/v1/me/notification-settings"
NOW = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)


async def _user(session: AsyncSession, email: str = "alice@example.com") -> User:
    user = await session.scalar(select(User).where(User.email == email))
    assert user is not None
    return user


async def _note(
    session: AsyncSession,
    user: User,
    *,
    created_at: datetime = NOW,
    is_read: bool = False,
    title: str = "t",
) -> Notification:
    note = Notification(
        user_id=user.id,
        type="system",
        title=title,
        body="b",
        is_read=is_read,
        created_at=created_at,
    )
    session.add(note)
    await session.flush()
    return note


async def _price_alert(session: AsyncSession, user: User) -> Watch:
    watch = await insert_watch(session, user, target_price=9500)
    snapshot = PriceSnapshot(
        price_query_id=watch.price_query_id,
        provider="mock",
        price=9000,
        stops=0,
        booking_url="https://example.test",
        observed_at=NOW,
    )
    session.add(snapshot)
    await session.flush()
    decision = Decision(notify=True, reasons=("below_target",), new_state=AlertState())
    await create_alert(session, watch, snapshot.id, 9000, decision, created_at=NOW, deliver=False)
    return watch


async def test_list_order_and_unread_count(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    alice = await _user(db_session)
    for i, read in enumerate([False, True, False]):
        await _note(
            db_session, alice, created_at=NOW + timedelta(minutes=i), is_read=read, title=f"n{i}"
        )

    resp = await client.get(URL, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert [n["title"] for n in body["items"]] == ["n2", "n1", "n0"]
    assert body["unread_count"] == 2
    assert set(body["items"][0]) == {
        "id",
        "type",
        "title",
        "body",
        "link",
        "booking_url",
        "is_read",
        "created_at",
    }


async def test_pagination_with_same_created_at(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await auth_headers(client, db_session)
    alice = await _user(db_session)
    for _ in range(5):
        await _note(db_session, alice)

    seen: list[str] = []
    sizes: list[int] = []
    before: str | None = None
    for _ in range(3):
        params: dict[str, str | int] = {"limit": 2}
        if before is not None:
            params["before"] = before
        items = (await client.get(URL, headers=headers, params=params)).json()["items"]
        sizes.append(len(items))
        seen += [n["id"] for n in items]
        before = items[-1]["id"]
    assert sizes == [2, 2, 1]
    assert len(set(seen)) == 5


async def test_unread_only(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    alice = await _user(db_session)
    await _note(db_session, alice, is_read=True)
    unread = await _note(db_session, alice)
    items = (await client.get(URL, headers=headers, params={"unread_only": True})).json()["items"]
    assert [n["id"] for n in items] == [str(unread.public_id)]


async def test_before_of_other_user_422(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    bob = await create_user(db_session, email="bob@example.com")
    others = await _note(db_session, bob)
    resp = await client.get(URL, headers=headers, params={"before": str(others.public_id)})
    assert resp.status_code == 422
    for limit in (0, 101):
        assert (await client.get(URL, headers=headers, params={"limit": limit})).status_code == 422


async def test_booking_url(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    alice = await _user(db_session)
    await _note(db_session, alice, created_at=NOW - timedelta(days=1))
    watch = await _price_alert(db_session, alice)

    items = (await client.get(URL, headers=headers)).json()["items"]
    assert items[0]["type"] == "price_alert"
    assert items[0]["booking_url"] == "https://example.test"
    assert items[0]["link"] == f"/watches/{watch.public_id}"
    assert items[1]["booking_url"] is None

    # 刪除追蹤後通知仍在，只是查不到訂票連結
    await db_session.delete(watch)
    await db_session.flush()
    db_session.expunge_all()
    items = (await client.get(URL, headers=headers)).json()["items"]
    assert len(items) == 2
    assert items[0]["booking_url"] is None
    assert items[0]["link"] == f"/watches/{watch.public_id}"


async def test_mark_read(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    mine = await _note(db_session, await _user(db_session))
    others = await _note(db_session, await create_user(db_session, email="bob@example.com"))

    resp = await client.patch(f"{URL}/{mine.public_id}/read", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_read"] is True
    assert (
        await client.patch(f"{URL}/{others.public_id}/read", headers=headers)
    ).status_code == 404
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.patch(f"{URL}/{missing}/read", headers=headers)).status_code == 404


async def test_read_all(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    alice = await _user(db_session)
    await _note(db_session, alice)
    await _note(db_session, alice)
    others = await _note(db_session, await create_user(db_session, email="bob@example.com"))

    assert (await client.post(f"{URL}/read-all", headers=headers)).status_code == 204
    assert (await client.get(URL, headers=headers)).json()["unread_count"] == 0
    await db_session.refresh(others)
    assert others.is_read is False


async def test_settings_default_and_update(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    assert (await client.get(SETTINGS_URL, headers=headers)).json() == {"email_enabled": True}
    resp = await client.patch(SETTINGS_URL, headers=headers, json={"email_enabled": False})
    assert resp.status_code == 200
    assert resp.json() == {"email_enabled": False}
    assert (await client.get(SETTINGS_URL, headers=headers)).json() == {"email_enabled": False}


async def test_demo_read_only(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await demo_headers(client, db_session)
    demo = await db_session.scalar(select(User).where(User.is_demo.is_(True)))
    assert demo is not None
    note = await _note(db_session, demo)

    assert (await client.get(URL, headers=headers)).status_code == 200
    assert (await client.get(SETTINGS_URL, headers=headers)).status_code == 200
    assert (await client.patch(f"{URL}/{note.public_id}/read", headers=headers)).status_code == 403
    assert (await client.post(f"{URL}/read-all", headers=headers)).status_code == 403
    resp = await client.patch(SETTINGS_URL, headers=headers, json={"email_enabled": False})
    assert resp.status_code == 403


async def test_requires_auth(client: AsyncClient) -> None:
    assert (await client.get(URL)).status_code == 401
    assert (await client.get(SETTINGS_URL)).status_code == 401
