"""帳號流程的業務規則。失敗時丟出本模組的例外，由 router 轉成 HTTP 狀態碼。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
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
