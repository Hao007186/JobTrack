import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.modules.auth.security import InvalidAccessToken, decode_access_token
from app.modules.users.models import User

_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未登入或登入已過期",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    if credentials is None:
        raise _unauthorized()
    try:
        public_id = uuid.UUID(
            decode_access_token(credentials.credentials, secret=settings.jwt_secret)
        )
    except InvalidAccessToken, ValueError:
        raise _unauthorized() from None
    # 每次都查使用者：之後的端點需要內部 id 檢查資料擁有者，也讓停用帳號立即失效
    user = await session.scalar(select(User).where(User.public_id == public_id))
    if user is None or not user.is_active:
        raise _unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_writable_user(user: CurrentUser) -> User:
    if user.is_demo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="示範帳號為唯讀")
    return user


WritableUser = Annotated[User, Depends(require_writable_user)]
