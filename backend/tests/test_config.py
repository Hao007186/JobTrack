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
