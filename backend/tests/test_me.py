import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.auth.security import create_access_token
from tests.conftest import create_user

URL = "/api/v1/me"
NOT_LOGGED_IN = "未登入或登入已過期"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token(sub: str, *, secret: str | None = None, minutes: int = 15) -> str:
    return create_access_token(
        sub,
        secret=secret or get_settings().jwt_secret,
        expires_in=timedelta(minutes=minutes),
    )


async def test_me_returns_user(client: AsyncClient) -> None:
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "correct-horse", "display_name": "Bob"},
    )
    resp = await client.get(URL, headers=_bearer(reg.json()["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "bob@example.com"
    assert body["display_name"] == "Bob"
    assert body["role"] == "user"
    assert body["is_demo"] is False
    uuid.UUID(body["public_id"])
    assert "id" not in body
    assert "password_hash" not in body


@pytest.mark.parametrize(
    "headers",
    [
        {},
        _bearer("garbage"),
        _bearer(_token(str(uuid.uuid4()), minutes=-1)),
        _bearer(_token(str(uuid.uuid4()), secret="some-other-secret-0123456789abcdef0123")),
    ],
    ids=["no-header", "garbage", "expired", "other-secret"],
)
async def test_me_requires_token(client: AsyncClient, headers: dict[str, str]) -> None:
    resp = await client.get(URL, headers=headers)
    assert resp.status_code == 401
    assert resp.json()["detail"] == NOT_LOGGED_IN
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_me_non_uuid_sub(client: AsyncClient) -> None:
    assert (await client.get(URL, headers=_bearer(_token("abc")))).status_code == 401


async def test_me_unknown_user(client: AsyncClient) -> None:
    resp = await client.get(URL, headers=_bearer(_token(str(uuid.uuid4()))))
    assert resp.status_code == 401


async def test_me_inactive_user(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    token = _token(str(user.public_id))
    user.is_active = False
    await db_session.flush()
    assert (await client.get(URL, headers=_bearer(token))).status_code == 401
