from datetime import timedelta

import pytest

from app.modules.auth.security import (
    InvalidAccessToken,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)

SECRET = "unit-test-secret-0123456789abcdef0123"
OTHER_SECRET = "another-secret-0123456789abcdef01234"


def _token(expires_in: timedelta = timedelta(minutes=15)) -> str:
    return create_access_token("abc", secret=SECRET, expires_in=expires_in)


def test_password_roundtrip() -> None:
    h = hash_password("correct-horse")
    assert h != "correct-horse"
    assert verify_password("correct-horse", h)
    assert not verify_password("wrong-horse", h)


def test_access_token_roundtrip() -> None:
    assert decode_access_token(_token(), secret=SECRET) == "abc"


def test_expired_access_token_rejected() -> None:
    with pytest.raises(InvalidAccessToken):
        decode_access_token(_token(timedelta(minutes=-1)), secret=SECRET)


def test_wrong_secret_rejected() -> None:
    with pytest.raises(InvalidAccessToken):
        decode_access_token(_token(), secret=OTHER_SECRET)


def test_tampered_token_rejected() -> None:
    t = _token()
    tampered = t[:-1] + ("A" if t[-1] != "A" else "B")
    with pytest.raises(InvalidAccessToken):
        decode_access_token(tampered, secret=SECRET)


def test_garbage_token_rejected() -> None:
    with pytest.raises(InvalidAccessToken):
        decode_access_token("not-a-jwt", secret=SECRET)


def test_refresh_token_hash() -> None:
    t = new_refresh_token()
    assert len(t) >= 43
    assert hash_refresh_token(t) == hash_refresh_token(t)
    assert hash_refresh_token(t) != hash_refresh_token(new_refresh_token())
    assert len(hash_refresh_token(t)) == 64
