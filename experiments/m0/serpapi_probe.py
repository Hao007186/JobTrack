"""M0 小實驗：確認 SerpApi Google Flights 來回票一次呼叫能拿到總價、price_insights 和 Google Flights 網址。

用法（PowerShell）：
    $env:SERPAPI_KEY = "你的 API key"
    python experiments/m0/serpapi_probe.py

只用標準函式庫，只花 1 次搜尋額度（account API 不算額度）。原始回應存到 experiments/m0/output/（不進 Git）。
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

BASE_URL = "https://serpapi.com"
OUTPUT_DIR = Path(__file__).parent / "output"

# 要測的行程，依實際想追蹤的行程調整
ORIGIN, DESTINATION = "TPE", "NRT"
DEPART_IN_DAYS = 60
TRIP_LENGTH_DAYS = 5


def call(path: str, params: dict) -> dict:
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        return {"error": f"HTTP {error.code}", "body": error.read().decode("utf-8", "replace")}
    except urllib.error.URLError as error:
        return {"error": str(error.reason)}


def save(name: str, payload: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def searches_left(api_key: str) -> str:
    account = call("/account.json", {"api_key": api_key})
    if account.get("error"):
        return f"錯誤：{account['error']}"
    return f"{account.get('plan_searches_left')}（方案：{account.get('plan_name')}）"


def probe_round_trip(api_key: str) -> None:
    depart = date.today() + timedelta(days=DEPART_IN_DAYS)
    params = {
        "engine": "google_flights",
        "departure_id": ORIGIN,
        "arrival_id": DESTINATION,
        "outbound_date": depart.isoformat(),
        "return_date": (depart + timedelta(days=TRIP_LENGTH_DAYS)).isoformat(),
        "type": 1,  # 1 = 來回
        "travel_class": 1,  # 1 = 經濟艙
        "adults": 1,
        "currency": "TWD",
        "hl": "zh-TW",
        "gl": "tw",
        "api_key": api_key,
    }
    payload = call("/search.json", params)
    save(f"serpapi_{ORIGIN}_{DESTINATION}_{depart}_rt", payload)
    print(f"## {ORIGIN}→{DESTINATION} 來回，{depart} 出發、{TRIP_LENGTH_DAYS} 天後回程\n")
    if payload.get("error"):
        print(f"錯誤：{payload['error']}\n{payload.get('body', '')}")
        return

    flights = payload.get("best_flights", []) + payload.get("other_flights", [])
    print(f"- 航班選項：best {len(payload.get('best_flights', []))} 筆、other {len(payload.get('other_flights', []))} 筆")
    if flights:
        first = flights[0]
        airlines = sorted({leg.get("airline", "?") for leg in first.get("flights", [])})
        print(f"- 第一筆價格：{first.get('price')} TWD（{', '.join(airlines)}）")
        print(f"- 第一筆航段數：{len(first.get('flights', []))}（只有去程航段代表回程要再呼叫一次才看得到）")
        print(f"- 有 departure_token：{'departure_token' in first}；有 booking_token：{'booking_token' in first}")

    insights = payload.get("price_insights")
    print(f"- 有 price_insights：{insights is not None}")
    if insights:
        print(f"  - lowest_price：{insights.get('lowest_price')}")
        print(f"  - price_level：{insights.get('price_level')}")
        print(f"  - typical_price_range：{insights.get('typical_price_range')}")
        print(f"  - price_history 筆數：{len(insights.get('price_history', []))}")

    metadata = payload.get("search_metadata", {})
    print(f"- google_flights_url：{metadata.get('google_flights_url')}")
    print(f"- 耗時：{metadata.get('total_time_taken')} 秒\n")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        print("請先設定環境變數 SERPAPI_KEY", file=sys.stderr)
        return 1
    print(f"# SerpApi 小實驗（{date.today()}）\n")
    print(f"查價前剩餘額度：{searches_left(api_key)}\n")
    probe_round_trip(api_key)
    print(f"查價後剩餘額度：{searches_left(api_key)}\n")
    print(f"原始回應已存到 {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
