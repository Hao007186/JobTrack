"""錄製 SerpApi 真實回應當測試資料。只在開發時手動執行，會花 2 次搜尋額度。

用法（在 backend/ 下）：
    1. 在 backend/.env 加上 SERPAPI_KEY=...（不要寫在指令列）
    2. PYTHONPATH=. uv run python scripts/record_serpapi_fixtures.py
       （PowerShell 先執行 $env:PYTHONPATH="."）

存到 tests/fixtures/serpapi/；存檔前若內容含 key 就中止。
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings

BASE_URL = "https://serpapi.com"
OUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "serpapi"
COMMON = {
    "engine": "google_flights",
    "departure_id": "TPE",
    "arrival_id": "NRT",
    "travel_class": "1",
    "adults": "1",
    "currency": "TWD",
    "hl": "zh-TW",
    "gl": "tw",
}


def _get(client: httpx.Client, path: str, params: dict[str, str]) -> dict[str, Any]:
    resp = client.get(f"{BASE_URL}{path}", params=params)
    data: dict[str, Any] = resp.json()
    print(f"- {path} HTTP {resp.status_code}")
    return data


def _save(name: str, payload: dict[str, Any], key: str) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if key in text:
        sys.exit(f"中止：{name} 的內容含有 API key，不存檔")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.json").write_text(text + "\n", encoding="utf-8")


def _summary(name: str, payload: dict[str, Any]) -> None:
    flights = payload.get("best_flights", []) + payload.get("other_flights", [])
    insights = payload.get("price_insights")
    print(f"## {name}")
    print(f"- error：{payload.get('error')}")
    lowest = min((f["price"] for f in flights if "price" in f), default=None)
    print(f"- 航班選項：{len(flights)} 筆；最低價：{lowest}")
    numbers = sorted(
        {leg.get("flight_number", "?") for f in flights for leg in f.get("flights", [])}
    )
    print(f"- 航班號碼（前 5 個）：{numbers[:5]}")
    print(f"- 有 price_insights：{insights is not None}")
    if insights:
        print(f"  - typical_price_range：{insights.get('typical_price_range')}")
        print(f"  - price_history 筆數：{len(insights.get('price_history', []))}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    secret = get_settings().serpapi_key
    if secret is None:
        sys.exit("請先在 backend/.env 設定 SERPAPI_KEY")
    key = secret.get_secret_value()
    depart = date.today() + timedelta(days=60)

    with httpx.Client(timeout=60) as client:
        before = _get(client, "/account.json", {"api_key": key}).get("plan_searches_left")
        print(f"錄製前剩餘次數：{before}\n")

        one_way = _get(
            client,
            "/search.json",
            {**COMMON, "type": "2", "outbound_date": depart.isoformat(), "api_key": key},
        )
        _save("one_way", one_way, key)
        _summary("one_way（TPE→NRT 單程）", one_way)

        with_airlines = _get(
            client,
            "/search.json",
            {
                **COMMON,
                "type": "1",
                "outbound_date": depart.isoformat(),
                "return_date": (depart + timedelta(days=5)).isoformat(),
                "include_airlines": "JX",
                "api_key": key,
            },
        )
        _save("with_airlines", with_airlines, key)
        _summary("with_airlines（TPE→NRT 來回，只限 JX）", with_airlines)

        after = _get(client, "/account.json", {"api_key": key}).get("plan_searches_left")
        print(f"\n錄製後剩餘次數：{after}")


if __name__ == "__main__":
    main()
