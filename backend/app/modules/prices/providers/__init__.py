import httpx

from app.core.config import Settings
from app.modules.prices.providers.base import PriceProvider
from app.modules.prices.providers.mock import MockProvider


def get_provider(settings: Settings, client: httpx.AsyncClient | None = None) -> PriceProvider:
    return MockProvider()
