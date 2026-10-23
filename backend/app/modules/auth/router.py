from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.modules.auth import service
from app.modules.auth.schemas import LoginRequest, RegisterRequest, TokenResponse

REFRESH_COOKIE = "refresh_token"
# 只有呼叫 auth 端點時瀏覽器才會送出 refresh cookie
REFRESH_COOKIE_PATH = "/api/v1/auth"

router = APIRouter(tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        path=REFRESH_COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    # 屬性要和設定時相同，瀏覽器才會刪掉同一個 cookie
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _token_response(
    response: Response, pair: service.TokenPair, settings: Settings
) -> TokenResponse:
    set_refresh_cookie(response, pair.refresh_token, settings)
    return TokenResponse(access_token=pair.access_token)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    try:
        pair = await service.register(
            session,
            settings,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
        )
    except service.EmailAlreadyRegistered:
        raise HTTPException(status.HTTP_409_CONFLICT, "此 Email 已註冊") from None
    return _token_response(response, pair, settings)


@router.post("/login")
async def login(
    body: LoginRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    try:
        pair = await service.login(session, settings, email=body.email, password=body.password)
    except service.InvalidCredentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email 或密碼錯誤") from None
    except service.AccountLocked:
        raise HTTPException(status.HTTP_423_LOCKED, "登入失敗次數過多，請稍後再試") from None
    return _token_response(response, pair, settings)
