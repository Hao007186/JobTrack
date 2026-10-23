"""帳號流程的業務規則。失敗時丟出本模組的例外，由 router 轉成 HTTP 狀態碼。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.auth import security
from app.modules.auth.models import RefreshToken
from app.modules.users.models import User

MAX_FAILED_LOGINS = 5
LOCKOUT_DURATION = timedelta(minutes=15)
DEMO_EMAIL = "demo@farewatch.local"


class EmailAlreadyRegistered(Exception):
    pass


class InvalidCredentials(Exception):
    pass


class AccountLocked(Exception):
    pass


class InvalidRefreshToken(Exception):
    pass


class DemoUserMissing(Exception):
    pass


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result: User | None = await session.scalar(select(User).where(User.email == email))
    return result


async def issue_tokens(session: AsyncSession, settings: Settings, user: User) -> TokenPair:
    refresh_token = security.new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=security.hash_refresh_token(refresh_token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        )
    )
    await session.commit()
    access_token = security.create_access_token(
        str(user.public_id),
        secret=settings.jwt_secret,
        expires_in=timedelta(minutes=settings.access_token_minutes),
    )
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


async def register(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    password: str,
    display_name: str | None,
) -> TokenPair:
    email = normalize_email(email)
    if await get_user_by_email(session, email) is not None:
        raise EmailAlreadyRegistered
    user = User(
        email=email,
        password_hash=security.hash_password(password),
        display_name=display_name,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as e:
        # 兩個請求同時通過上面的檢查時，由 DB 的 unique constraint 擋下第二筆
        await session.rollback()
        raise EmailAlreadyRegistered from e
    return await issue_tokens(session, settings, user)


async def login(
    session: AsyncSession, settings: Settings, *, email: str, password: str
) -> TokenPair:
    user = await get_user_by_email(session, normalize_email(email))
    if user is None:
        security.verify_dummy_password(password)
        raise InvalidCredentials

    now = datetime.now(UTC)
    if user.locked_until is not None and user.locked_until > now:
        raise AccountLocked

    if not security.verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = now + LOCKOUT_DURATION
            user.failed_login_count = 0
        await session.commit()
        raise InvalidCredentials

    # 示範帳號只能走 POST /auth/demo
    if not user.is_active or user.is_demo:
        raise InvalidCredentials

    user.failed_login_count = 0
    user.locked_until = None
    return await issue_tokens(session, settings, user)


async def refresh(session: AsyncSession, settings: Settings, *, refresh_token: str) -> TokenPair:
    row = await session.execute(
        select(RefreshToken, User)
        .join(User, RefreshToken.user_id == User.id)
        .where(RefreshToken.token_hash == security.hash_refresh_token(refresh_token))
    )
    found = row.one_or_none()
    if found is None:
        raise InvalidRefreshToken
    token, user = found
    now = datetime.now(UTC)

    if token.revoked_at is not None:
        # 正常使用者手上只會有最新的 token；舊 token 被重用代表可能被偷，作廢該使用者全部 token。
        # 示範帳號由多位訪客共用，只拒絕這一次，避免一人重用就把所有人踢出
        if not user.is_demo:
            await session.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            # 先 commit 再丟例外，否則 router 回 401 時作廢結果會跟著 session 被丟棄
            await session.commit()
        raise InvalidRefreshToken

    if token.expires_at <= now or not user.is_active:
        raise InvalidRefreshToken

    token.revoked_at = now
    # issue_tokens 會 commit，作廢舊 token 和發新 token 在同一個 transaction
    return await issue_tokens(session, settings, user)


async def logout(session: AsyncSession, *, refresh_token: str | None) -> None:
    if refresh_token is None:
        return
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == security.hash_refresh_token(refresh_token),
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()


async def demo_login(session: AsyncSession, settings: Settings) -> TokenPair:
    user = await session.scalar(select(User).where(User.email == DEMO_EMAIL, User.is_demo))
    if user is None:
        raise DemoUserMissing
    return await issue_tokens(session, settings, user)
