from datetime import timedelta

import pytest

from app.modules.prices.providers.mock import (
    MockProvider,
    mock_base_price,
    mock_insights,
    mock_price,
)
from tests.prices.conftest import TODAY, conditions

HASHES = [conditions(destination=d).query_hash() for d in ("NRT", "KIX", "BKK")]


@pytest.mark.parametrize("query_hash", HASHES)
async def test_base_price_range(query_hash: str) -> None:
    base = mock_base_price(query_hash)
    assert 3000 <= base <= 15000
    assert base % 100 == 0


async def test_same_day_same_price() -> None:
    h = HASHES[0]
    assert mock_price(h, TODAY) == mock_price(h, TODAY)


async def test_different_day_different_price() -> None:
    h = HASHES[0]
    prices = {mock_price(h, TODAY + timedelta(days=i)) for i in range(7)}
    assert len(prices) > 1


@pytest.mark.parametrize("query_hash", HASHES)
async def test_price_within_band(query_hash: str) -> None:
    base = mock_base_price(query_hash)
    for i in range(30):
        price = mock_price(query_hash, TODAY + timedelta(days=i))
        assert 0.85 * base <= price <= 1.2 * base
        assert price % 10 == 0


async def test_mock_insights() -> None:
    h = HASHES[0]
    base = mock_base_price(h)
    insights = mock_insights(h)
    assert insights.typical_low == int(base * 0.9)
    assert insights.typical_high == int(base * 1.2)
    assert insights.history_low == int(base * 0.8)


async def test_mock_search() -> None:
    provider = MockProvider()
    result = await provider.search(conditions(airlines=("BR",)))
    assert result.lowest is not None
    assert result.lowest.airline_iata == "BR"
    assert result.lowest.stops == 0
    assert result.booking_url is None
    assert result.insights is not None
    assert await provider.remaining_quota() is None
