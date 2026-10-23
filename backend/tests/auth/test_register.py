import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import service
from app.modules.users.models import User
from tests.conftest import create_user

URL = "/api/v1/auth/register"


async def test_register_success(client: AsyncClient, db_session: AsyncSession) -> None:
    resp = await client.post(URL, json={"email": "Bob@Example.com", "password": "correct-horse"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    cookie = resp.headers["set-cookie"]
    assert "refresh_token=" in cookie
    assert "httponly" in cookie.lower()
    assert "samesite=strict" in cookie.lower()
    assert "secure" in cookie.lower()
    assert "Path=/api/v1/auth" in cookie
    assert "Max-Age=604800" in cookie
    emails = (await db_session.scalars(select(User.email))).all()
    assert emails == ["bob@example.com"]


async def test_register_duplicate_email_case_insensitive(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await create_user(db_session, email="bob@example.com")
    resp = await client.post(URL, json={"email": "BOB@example.com", "password": "correct-horse"})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "此 Email 已註冊"


async def test_register_integrity_error_maps_to_409(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 模擬兩個請求同時通過「email 是否存在」的檢查，第二筆撞上 DB 的 unique constraint
    await create_user(db_session, email="bob@example.com")

    async def _not_found(session: AsyncSession, email: str) -> None:
        return None

    monkeypatch.setattr(service, "get_user_by_email", _not_found)
    resp = await client.post(URL, json={"email": "BOB@example.com", "password": "correct-horse"})
    assert resp.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "a@example.com", "password": "1234567"},
        {"email": "a@example.com", "password": "x" * 129},
        {"email": "not-an-email", "password": "correct-horse"},
        # 示範帳號用保留網域 .local，任何人都無法註冊同一個 email
        {"email": "demo@farewatch.local", "password": "correct-horse"},
        {"email": "a@example.com", "password": "correct-horse", "display_name": "x" * 51},
    ],
    ids=[
        "password-too-short",
        "password-too-long",
        "bad-email",
        "demo-email",
        "display-name-too-long",
    ],
)
async def test_register_validation(client: AsyncClient, payload: dict[str, str]) -> None:
    resp = await client.post(URL, json=payload)
    assert resp.status_code == 422
