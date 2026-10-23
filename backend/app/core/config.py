from functools import lru_cache
from typing import Literal

from pydantic import field_validator
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

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, v: str) -> str:
        for prefix in _PLAIN_PREFIXES:
            if v.startswith(prefix):
                return _PSYCOPG_PREFIX + v.removeprefix(prefix)
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
