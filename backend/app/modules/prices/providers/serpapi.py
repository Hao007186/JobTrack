"""SerpApi Google Flights 查價來源。

SerpApi 要求 api_key 放在網址參數，所以：httpx 的 log 調到 WARNING（預設會印完整網址），
所有錯誤訊息都先把 key 遮掉，避免外洩到 CloudWatch。
"""

import logging
from typing import Any

import httpx

from app.modules.prices.providers.base import Insights, Offer, ProviderError, SearchResult
from app.modules.watches.slots import QueryConditions

logging.getLogger("httpx").setLevel(logging.WARNING)

BASE_URL = "https://serpapi.com"
# SerpApi 用 error 欄位表示查無航班；這不是失敗
NO_RESULTS_MARKERS = ("Google Flights hasn't returned any results for this query.",)
_TRAVEL_CLASS = {"economy": "1", "premium_economy": "2", "business": "3", "first": "4"}


def build_params(cond: QueryConditions) -> dict[str, str]:
    params = {
        "engine": "google_flights",
        "departure_id": cond.origin,
        "arrival_id": cond.destination,
        "outbound_date": cond.depart_date.isoformat(),
        "type": "2" if cond.return_date is None else "1",
        "travel_class": _TRAVEL_CLASS[cond.cabin],
        "adults": str(cond.adults),
        "currency": "TWD",
        "hl": "zh-TW",
        "gl": "tw",
    }
    if cond.return_date is not None:
        params["return_date"] = cond.return_date.isoformat()
    if cond.airlines:
        params["include_airlines"] = ",".join(cond.airlines)
    return params


def _is_price(value: Any) -> bool:
    # bool 也是 int 的子類別，要排除；價格必須 > 0（資料表有 check constraint）
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _airline_of(option: dict[str, Any]) -> str | None:
    legs = option.get("flights") or []
    number = legs[0].get("flight_number") if legs and isinstance(legs[0], dict) else None
    if not isinstance(number, str) or " " not in number:
        return None
    code = number.split(" ", 1)[0]
    # IATA 航空公司代碼固定 2 碼（資料表欄位是 String(2)）
    return code if len(code) == 2 else None


def _insights(raw: Any) -> Insights | None:
    if not isinstance(raw, dict):
        return None
    typical = raw.get("typical_price_range")
    if not isinstance(typical, list) or len(typical) != 2 or not all(map(_is_price, typical)):
        return None
    history = raw.get("price_history") or []
    prices = [
        point[1]
        for point in history
        if isinstance(point, list) and len(point) == 2 and _is_price(point[1])
    ]
    return Insights(
        typical_low=int(typical[0]),
        typical_high=int(typical[1]),
        history_low=min(prices) if prices else None,
    )


def parse_search(payload: dict[str, Any]) -> SearchResult:
    try:
        return _parse(payload)
    except (TypeError, AttributeError, KeyError, ValueError) as e:
        # 格式不對時當成這次查價失敗，不要讓整次每日查價中斷
        raise ProviderError(f"SerpApi 回應格式不正確：{type(e).__name__}") from None


def _parse(payload: dict[str, Any]) -> SearchResult:
    error = payload.get("error")
    if error:
        if any(marker in str(error) for marker in NO_RESULTS_MARKERS):
            return SearchResult(lowest=None, booking_url=None, insights=None)
        raise ProviderError(f"SerpApi 回傳錯誤：{error}")

    options = (payload.get("best_flights") or []) + (payload.get("other_flights") or [])
    priced = [o for o in options if isinstance(o, dict) and _is_price(o.get("price"))]
    lowest = None
    if priced:
        best = min(priced, key=lambda o: o["price"])
        lowest = Offer(
            price=best["price"],
            airline_iata=_airline_of(best),
            stops=max(len(best.get("flights") or []) - 1, 0),
        )
    metadata = payload.get("search_metadata") or {}
    return SearchResult(
        lowest=lowest,
        booking_url=metadata.get("google_flights_url"),
        insights=_insights(payload.get("price_insights")),
    )


class SerpApiProvider:
    name = "serpapi"

    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self._key = api_key
        self._client = client

    def _scrub(self, text: str) -> str:
        return text.replace(self._key, "***")

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        try:
            resp = await self._client.get(
                f"{BASE_URL}{path}", params={**params, "api_key": self._key}
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            # httpx 的例外訊息會帶完整網址（含 key），不保留原例外鏈
            raise ProviderError(self._scrub(f"{type(e).__name__}: {e}")) from None
        return data

    async def search(self, cond: QueryConditions) -> SearchResult:
        return parse_search(await self._get("/search.json", build_params(cond)))

    async def remaining_quota(self) -> int | None:
        data = await self._get("/account.json", {})
        left = data.get("plan_searches_left")
        if not isinstance(left, int):
            raise ProviderError("SerpApi 帳戶資訊缺少 plan_searches_left")
        return left
