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

    # 本機預設只把信印在 log；smtp 可接 Resend、Gmail 或 SES
    email_sender: Literal["console", "smtp"] = "console"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    email_from: str | None = None
    # 信中「查看追蹤」連結的開頭（前端網址）
    app_base_url: str = "http://localhost:5173"

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

    @model_validator(mode="after")
    def _smtp_needs_fields(self) -> Self:
        if self.email_sender != "smtp":
            return self
        required = {
            "SMTP_HOST": self.smtp_host,
            "SMTP_USERNAME": self.smtp_username,
            "SMTP_PASSWORD": self.smtp_password,
            "EMAIL_FROM": self.email_from,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"EMAIL_SENDER=smtp 時必須設定 {', '.join(missing)}")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
