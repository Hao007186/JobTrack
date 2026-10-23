from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.deps import WritableUser
from app.seeds.demo import ensure_demo_user
from tests.auth.conftest import cookie_token, refresh_with
from tests.conftest import create_user

URL = "/api/v1/auth/demo"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_demo_missing(client: AsyncClient) -> None:
    resp = await client.post(URL)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "示範帳號尚未建立"


async def test_demo_login(client: AsyncClient, db_session: AsyncSession) -> None:
    await ensure_demo_user(db_session)
    resp = await client.post(URL)
    assert resp.status_code == 200
    assert "refresh_token=" in resp.headers["set-cookie"]
    me = await client.get("/api/v1/me", headers=_bearer(resp.json()["access_token"]))
    assert me.json()["is_demo"] is True


async def test_demo_logout_only_affects_self(client: AsyncClient, db_session: AsyncSession) -> None:
    await ensure_demo_user(db_session)
    a = cookie_token(await client.post(URL))
    b = cookie_token(await client.post(URL))
    client.cookies.clear()
    await client.post("/api/v1/auth/logout", headers={"Cookie": f"refresh_token={a}"})
    assert (await refresh_with(client, b)).status_code == 200


async def test_require_writable_user(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    @app.post("/_test/write")
    async def _write(user: WritableUser) -> dict[str, bool]:
        return {"ok": True}

    await ensure_demo_user(db_session)
    demo_token = (await client.post(URL)).json()["access_token"]
    resp = await client.post("/_test/write", headers=_bearer(demo_token))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "示範帳號為唯讀"

    await create_user(db_session)
    login = await client.post(
        "/api/v1/auth/login", json={"email": "alice@example.com", "password": "correct-horse"}
    )
    resp = await client.post("/_test/write", headers=_bearer(login.json()["access_token"]))
    assert resp.status_code == 200
