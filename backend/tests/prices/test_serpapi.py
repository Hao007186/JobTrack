import copy
import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.modules.prices.providers import get_provider
from app.modules.prices.providers.base import ProviderError
from app.modules.prices.providers.serpapi import (
    NO_RESULTS_MARKERS,
    SerpApiProvider,
    build_params,
    parse_search,
)
from tests.prices.conftest import TODAY, conditions

KEY = "test-key-SHOULD-NOT-LEAK"
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "serpapi"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def provider_with(handler: Any) -> SerpApiProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SerpApiProvider(KEY, client)


async def test_parse_round_trip() -> None:
    result = parse_search(load("round_trip"))
    assert result.lowest is not None
    assert (result.lowest.price, result.lowest.airline_iata, result.lowest.stops) == (
        10372,
        "MM",
        0,
    )
    assert result.booking_url is not None
    assert result.booking_url.startswith("https://www.google.com/travel/flights")
    assert result.insights is not None
    assert (result.insights.typical_low, result.insights.typical_high) == (6400, 12500)
    assert result.insights.history_low == 8637


async def test_parse_one_way() -> None:
    result = parse_search(load("one_way"))
    assert result.lowest is not None
    assert (result.lowest.price, result.lowest.airline_iata, result.lowest.stops) == (4840, "MM", 0)
    assert result.insights is not None
    assert (result.insights.typical_low, result.insights.typical_high) == (3550, 5300)
    assert result.insights.history_low == 3640


async def test_parse_with_airlines() -> None:
    # 錄製結果：指定航空公司時仍有典型區間，但沒有 price_history
    result = parse_search(load("with_airlines"))
    assert result.lowest is not None
    assert (result.lowest.price, result.lowest.airline_iata) == (27524, "JX")
    assert result.insights is not None
    assert (result.insights.typical_low, result.insights.typical_high) == (15500, 26500)
    assert result.insights.history_low is None


async def test_parse_skips_options_without_price() -> None:
    payload = load("round_trip")
    del payload["best_flights"][0]["price"]  # 原本最便宜的 10372
    options = payload["best_flights"] + payload["other_flights"]
    expected = min(o["price"] for o in options if "price" in o)
    result = parse_search(payload)
    assert result.lowest is not None
    assert result.lowest.price == expected

    no_prices = copy.deepcopy(payload)
    for option in no_prices["best_flights"] + no_prices["other_flights"]:
        option.pop("price", None)
    assert parse_search(no_prices).lowest is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda pi: pi.pop("typical_price_range"),
        lambda pi: pi.__setitem__("typical_price_range", [6400]),
    ],
    ids=["range-missing", "range-one-value"],
)
async def test_parse_incomplete_range(mutate: Any) -> None:
    payload = load("round_trip")
    mutate(payload["price_insights"])
    result = parse_search(payload)
    assert result.lowest is not None
    assert result.insights is None


async def test_parse_empty_history() -> None:
    payload = load("round_trip")
    payload["price_insights"]["price_history"] = []
    result = parse_search(payload)
    assert result.insights is not None
    assert result.insights.history_low is None


async def test_parse_no_results() -> None:
    result = parse_search({"error": NO_RESULTS_MARKERS[0], "search_metadata": {}})
    assert result.lowest is None
    assert result.insights is None


async def test_parse_other_error() -> None:
    with pytest.raises(ProviderError):
        parse_search({"error": "Invalid API key. Your API key should be here."})


@pytest.mark.parametrize(
    ("cond_overrides", "expected", "absent"),
    [
        (
            {},
            {"type": "2", "travel_class": "1", "adults": "1"},
            ["return_date", "include_airlines"],
        ),
        (
            {"return_date": TODAY + timedelta(days=35)},
            {"type": "1", "return_date": (TODAY + timedelta(days=35)).isoformat()},
            [],
        ),
        ({"cabin": "business"}, {"travel_class": "3"}, []),
        ({"airlines": ("BR", "CI")}, {"include_airlines": "BR,CI"}, []),
    ],
    ids=["one-way", "round-trip", "business", "airlines"],
)
async def test_build_params(
    cond_overrides: dict[str, Any], expected: dict[str, str], absent: list[str]
) -> None:
    params = build_params(conditions(**cond_overrides))
    for k, v in expected.items():
        assert params[k] == v
    for k in absent:
        assert k not in params
    assert params["engine"] == "google_flights"
    assert (params["currency"], params["hl"], params["gl"]) == ("TWD", "zh-TW", "tw")
    assert (params["departure_id"], params["arrival_id"]) == ("TPE", "NRT")
    assert "api_key" not in params


async def test_search_sends_key_and_params() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=load("round_trip"))

    result = await provider_with(handler).search(conditions())
    assert result.lowest is not None and result.lowest.price == 10372
    assert seen[0].url.path == "/search.json"
    assert seen[0].url.params["api_key"] == KEY
    assert seen[0].url.params["type"] == "2"


async def test_http_error_hides_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(ProviderError) as exc_info:
        await provider_with(handler).search(conditions())
    assert KEY not in str(exc_info.value)


async def test_timeout_is_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timed out: {request.url}", request=request)

    with pytest.raises(ProviderError) as exc_info:
        await provider_with(handler).search(conditions())
    assert KEY not in str(exc_info.value)


async def test_remaining_quota() -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/account.json"
        return httpx.Response(200, json={"plan_searches_left": 238})

    assert await provider_with(ok).remaining_quota() == 238

    def fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="oops")

    with pytest.raises(ProviderError) as exc_info:
        await provider_with(fail).remaining_quota()
    assert KEY not in str(exc_info.value)


async def test_logs_do_not_contain_key(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load("round_trip"))

    def fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    await provider_with(ok).search(conditions())
    with pytest.raises(ProviderError):
        await provider_with(fail).search(conditions())
    assert KEY not in caplog.text


async def test_get_provider_serpapi() -> None:
    settings = get_settings().model_copy(
        update={"price_provider": "serpapi", "serpapi_key": SecretStr(KEY)}
    )
    async with httpx.AsyncClient() as client:
        assert isinstance(get_provider(settings, client), SerpApiProvider)
