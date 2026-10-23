from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.auth import service
from app.modules.auth.models import RefreshToken
from app.modules.auth.security import hash_refresh_token
from app.modules.users.models import User
from tests.auth.conftest import REFRESH_URL, cookie_token, refresh_with
from tests.conftest import create_user

LOGIN = {"email": "alice@example.com", "password": "correct-horse"}


@pytest.fixture
async def user(db_session: AsyncSession) -> User:
    return await create_user(db_session)


async def _login_token(client: AsyncClient) -> str:
    resp = await client.post("/api/v1/auth/login", json=LOGIN)
    assert resp.status_code == 200
    return cookie_token(resp)


def _assert_rejected_and_cleared(resp_status: int, detail: str, set_cookie: str) -> None:
    assert resp_status == 401
    assert detail == "請重新登入"
    assert "refresh_token=" in set_cookie
    assert "Max-Age=0" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie


async def test_refresh_rotates(client: AsyncClient, user: User) -> None:
    t1 = await _login_token(client)
    resp = await refresh_with(client, t1)
    assert resp.status_code == 200
    assert resp.json()["access_token"]
    assert cookie_token(resp) != t1


async def test_reused_token_revokes_all(
    client: AsyncClient, user: User, db_session: AsyncSession
) -> None:
    a = await _login_token(client)
    b = await _login_token(client)
    a2 = cookie_token(await refresh_with(client, a))

    reused = await refresh_with(client, a)
    # 正式環境請求結束時會丟棄沒 commit 的變更；這裡模擬它，確認作廢結果真的有 commit
    await db_session.rollback()
    _assert_rejected_and_cleared(
        reused.status_code, reused.json()["detail"], reused.headers["set-cookie"]
    )
    # 重用偵測會作廢同一使用者的所有 token，包括輪換後拿到的新 token
    assert (await refresh_with(client, b)).status_code == 401
    assert (await refresh_with(client, a2)).status_code == 401


async def test_demo_reuse_does_not_revoke_others(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    demo = await create_user(db_session, email=service.DEMO_EMAIL, is_demo=True)
    a = (await service.issue_tokens(db_session, get_settings(), demo)).refresh_token
    b = (await service.issue_tokens(db_session, get_settings(), demo)).refresh_token

    assert (await refresh_with(client, a)).status_code == 200
    assert (await refresh_with(client, a)).status_code == 401
    assert (await refresh_with(client, b)).status_code == 200


async def test_expired_refresh_rejected(
    client: AsyncClient, user: User, db_session: AsyncSession
) -> None:
    t = await _login_token(client)
    await db_session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(t))
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    resp = await refresh_with(client, t)
    _assert_rejected_and_cleared(
        resp.status_code, resp.json()["detail"], resp.headers["set-cookie"]
    )


async def test_inactive_user_refresh_rejected(
    client: AsyncClient, user: User, db_session: AsyncSession
) -> None:
    t = await _login_token(client)
    user.is_active = False
    await db_session.flush()
    assert (await refresh_with(client, t)).status_code == 401


async def test_unknown_token_rejected(client: AsyncClient) -> None:
    resp = await refresh_with(client, "nope")
    _assert_rejected_and_cleared(
        resp.status_code, resp.json()["detail"], resp.headers["set-cookie"]
    )


async def test_missing_cookie_rejected(client: AsyncClient) -> None:
    resp = await client.post(REFRESH_URL)
    _assert_rejected_and_cleared(
        resp.status_code, resp.json()["detail"], resp.headers["set-cookie"]
    )


async def test_concurrent_refresh_only_one_wins(
    client: AsyncClient, user: User, db_session: AsyncSession
) -> None:
    a = await _login_token(client)
    b = await _login_token(client)
    # 這個請求先讀到「a 尚未作廢」（保留參照，session 才不會重新從 DB 讀取）
    stale = await db_session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(a))
    )
    # 同時另一個請求搶先輪換了 a：直接改 DB，不更新 session 裡已讀到的物件
    await db_session.execute(
        text("UPDATE refresh_tokens SET revoked_at = now() WHERE token_hash = :h"),
        {"h": hash_refresh_token(a)},
    )
    # 慢的那個請求不能再拿到新 token，而且要當成重用處理
    assert (await refresh_with(client, a)).status_code == 401
    assert (await refresh_with(client, b)).status_code == 401
    assert stale is not None
