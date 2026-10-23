"""本機開發用的假查價來源：不連網路，同一天同一個 query 價格固定、隔天會變動。"""

import hashlib
from datetime import date

from app.core.clock import taipei_today
from app.modules.prices.providers.base import Insights, Offer, SearchResult
from app.modules.watches.slots import QueryConditions


def _number(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16)


def mock_base_price(query_hash: str) -> int:
    # 3,000～15,000，取到百位
    return 3000 + (_number(query_hash) % 121) * 100


def mock_price(query_hash: str, day: date) -> int:
    base = mock_base_price(query_hash)
    permille = 850 + _number(query_hash + day.isoformat()) % 351  # 85%～120%
    raw = base * permille // 1000
    # 無條件進位到十位；base 是百的倍數，所以不會超過 120%
    return (raw + 9) // 10 * 10


def mock_insights(query_hash: str) -> Insights:
    base = mock_base_price(query_hash)
    return Insights(
        typical_low=int(base * 0.9),
        typical_high=int(base * 1.2),
        history_low=int(base * 0.8),
    )


class MockProvider:
    name = "mock"

    async def search(self, cond: QueryConditions) -> SearchResult:
        query_hash = cond.query_hash()
        airline = cond.airlines[0] if cond.airlines else None
        return SearchResult(
            lowest=Offer(
                price=mock_price(query_hash, taipei_today()), airline_iata=airline, stops=0
            ),
            booking_url=None,
            insights=mock_insights(query_hash),
        )

    async def remaining_quota(self) -> int | None:
        return None
