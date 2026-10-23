import httpx

from app.core.config import Settings
from app.modules.prices.providers.base import PriceProvider
from app.modules.prices.providers.mock import MockProvider
from app.modules.prices.providers.serpapi import SerpApiProvider

SERPAPI_TIMEOUT_SECONDS = 60


def get_provider(settings: Settings, client: httpx.AsyncClient | None = None) -> PriceProvider:
    if settings.price_provider == "serpapi":
        # Settings 的驗證已保證 serpapi 時一定有 key
        assert settings.serpapi_key is not None
        return SerpApiProvider(
            settings.serpapi_key.get_secret_value(),
            client or httpx.AsyncClient(timeout=SERPAPI_TIMEOUT_SECONDS),
        )
    return MockProvider()
