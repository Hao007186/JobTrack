from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.auth.conftest import cookie_token, refresh_with
from tests.conftest import create_user

URL = "/api/v1/auth/logout"


async def test_logout_revokes(client: AsyncClient, db_session: AsyncSession) -> None:
    await create_user(db_session)
    login = await client.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": "correct-horse"}
    )
    t = cookie_token(login)

    resp = await client.post(URL)  # client 自動帶上登入時拿到的 cookie
    assert resp.status_code == 204
    assert "Max-Age=0" in resp.headers["set-cookie"]
    assert (await refresh_with(client, t)).status_code == 401


async def test_logout_without_cookie(client: AsyncClient) -> None:
    assert (await client.post(URL)).status_code == 204


async def test_logout_unknown_token(client: AsyncClient) -> None:
    resp = await client.post(URL, headers={"Cookie": "refresh_token=nope"})
    assert resp.status_code == 204
