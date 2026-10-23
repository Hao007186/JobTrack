"""prices 測試共用 watches 的參考資料 fixture 與佈置 helper，以及假的查價來源。"""

from collections.abc import Awaitable, Callable

from app.modules.prices.providers.base import Offer, SearchResult
from app.modules.watches.slots import QueryConditions
from tests.watches.conftest import (
    TODAY,
    auth_headers,
    conditions,
    demo_headers,
    fixed_today,
    insert_watch,
    reference,
)

__all__ = [
    "TODAY",
    "FakeProvider",
    "auth_headers",
    "conditions",
    "demo_headers",
    "fixed_today",
    "insert_watch",
    "reference",
]

DEFAULT_RESULT = SearchResult(Offer(9000, "BR", 0), "https://example.test", None)


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        remaining: int | None | Exception = None,
        results: dict[str, SearchResult | Exception] | None = None,
        default: SearchResult | Exception = DEFAULT_RESULT,
        on_remaining: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.remaining = remaining
        self.results = results or {}
        self.default = default
        self.on_remaining = on_remaining
        self.calls: list[QueryConditions] = []

    async def search(self, cond: QueryConditions) -> SearchResult:
        self.calls.append(cond)
        outcome = self.results.get(cond.destination, self.default)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def remaining_quota(self) -> int | None:
        if self.on_remaining is not None:
            await self.on_remaining()
        if isinstance(self.remaining, Exception):
            raise self.remaining
        return self.remaining
