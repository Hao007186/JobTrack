"""查價來源的介面：不碰 DB，換供應商只要新增一個實作。"""

from dataclasses import dataclass
from typing import Protocol

from app.modules.watches.slots import QueryConditions


@dataclass(frozen=True)
class Offer:
    price: int
    airline_iata: str | None
    stops: int


@dataclass(frozen=True)
class Insights:
    typical_low: int
    typical_high: int
    history_low: int | None


@dataclass(frozen=True)
class SearchResult:
    lowest: Offer | None  # None = 查不到航班
    booking_url: str | None
    insights: Insights | None


class ProviderError(Exception):
    pass


class PriceProvider(Protocol):
    name: str

    async def search(self, cond: QueryConditions) -> SearchResult: ...

    async def remaining_quota(self) -> int | None:
        """本月剩餘次數；None 代表不限（mock）。"""
        ...
