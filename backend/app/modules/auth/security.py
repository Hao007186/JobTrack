"""密碼雜湊、access token（JWT）與 refresh token 的純函式，不碰 DB。"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

_ALGORITHM = "HS256"
_password_hash = PasswordHash((Argon2Hasher(),))

# email 不存在時拿來比對，讓回應時間和密碼錯誤時相近
_DUMMY_HASH = _password_hash.hash(secrets.token_urlsafe(16))


class InvalidAccessToken(Exception):
    pass


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


def verify_dummy_password(password: str) -> None:
    _password_hash.verify(password, _DUMMY_HASH)


def create_access_token(
    subject: str, *, secret: str, expires_in: timedelta, now: datetime | None = None
) -> str:
    issued_at = now or datetime.now(UTC)
    payload = {"sub": subject, "iat": issued_at, "exp": issued_at + expires_in}
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_access_token(token: str, *, secret: str) -> str:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.InvalidTokenError as e:
        raise InvalidAccessToken from e
    sub = payload["sub"]
    if not isinstance(sub, str):
        raise InvalidAccessToken
    return sub


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    # refresh token 本身是高熵亂數，用 SHA-256 即可，不需要 Argon2 這種慢雜湊
    return hashlib.sha256(token.encode()).hexdigest()
