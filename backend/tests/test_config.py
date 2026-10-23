import pytest
from pydantic import ValidationError

from app.core.config import Settings

URL = "postgresql+psycopg://u:p@h:5432/db"


def test_missing_database_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    s = Settings(_env_file=None)
    assert s.env == "local"
    assert s.log_level == "INFO"


@pytest.mark.parametrize("raw", ["postgresql://u:p@h:5432/db", "postgres://u:p@h:5432/db"])
def test_plain_postgres_url_gets_psycopg_driver(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("DATABASE_URL", raw)
    assert Settings(_env_file=None).database_url == URL


def test_invalid_env_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("ENV", "staging")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_missing_jwt_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_auth_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    for name in ("ACCESS_TOKEN_MINUTES", "REFRESH_TOKEN_DAYS", "COOKIE_SECURE"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert s.access_token_minutes == 15
    assert s.refresh_token_days == 7
    assert s.cookie_secure is True


def test_price_provider_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.delenv("PRICE_PROVIDER", raising=False)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.price_provider == "mock"
    assert s.serpapi_key is None


def test_serpapi_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("PRICE_PROVIDER", "serpapi")
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)

    monkeypatch.setenv("SERPAPI_KEY", "secret-serpapi-key")
    s = Settings(_env_file=None)
    assert s.serpapi_key is not None
    assert s.serpapi_key.get_secret_value() == "secret-serpapi-key"
    assert "secret-serpapi-key" not in str(s)
    assert "secret-serpapi-key" not in repr(s)
