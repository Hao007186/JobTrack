from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Neon 主控台複製出來的連線字串沒有指定 driver，SQLAlchemy 預設會找 psycopg2
_PLAIN_PREFIXES = ("postgresql://", "postgres://")
_PSYCOPG_PREFIX = "postgresql+psycopg://"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    env: Literal["local", "ci", "prod"] = "local"
    log_level: str = "INFO"

    jwt_secret: str
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    # 本機用 http 開發時在 .env 設 false，否則瀏覽器不會送出 cookie
    cookie_secure: bool = True

    # 本機開發預設用 mock，不會花到 SerpApi 額度
    price_provider: Literal["mock", "serpapi"] = "mock"
    serpapi_key: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, v: str) -> str:
        for prefix in _PLAIN_PREFIXES:
            if v.startswith(prefix):
                return _PSYCOPG_PREFIX + v.removeprefix(prefix)
        return v

    @model_validator(mode="after")
    def _serpapi_needs_key(self) -> Self:
        if self.price_provider == "serpapi" and self.serpapi_key is None:
            raise ValueError("PRICE_PROVIDER=serpapi 時必須設定 SERPAPI_KEY")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
