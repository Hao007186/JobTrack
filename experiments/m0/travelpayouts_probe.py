"""M0 小實驗：確認 Travelpayouts 對目標航線的資料覆蓋率、新鮮度，以及是否區分艙等。

用法（PowerShell）：
    $env:TRAVELPAYOUTS_TOKEN = "你的 token"
    python experiments/m0/travelpayouts_probe.py

只用標準函式庫。原始回應存到 experiments/m0/output/（不進 Git）。
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_URL = "https://api.travelpayouts.com"
OUTPUT_DIR = Path(__file__).parent / "output"

# 要測的航線和出發日，依實際想追蹤的行程調整
ROUTES = [("TPE", "NRT"), ("TPE", "KIX"), ("TPE", "ICN"), ("TPE", "BKK"), ("TPE", "SIN")]
DEPART_IN_DAYS = [30, 60, 120]
TRIP_LENGTH_DAYS = 5


def call(path: str, params: dict, token: str) -> dict:
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"X-Access-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        return {"success": False, "error": f"HTTP {error.code}", "body": error.read().decode("utf-8", "replace")}
    except urllib.error.URLError as error:
        return {"success": False, "error": str(error.reason)}


def save(name: str, payload: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def rows(payload: dict) -> list:
    data = payload.get("data")
    return data if isinstance(data, list) else []


def probe_exact_dates(token: str) -> None:
    """固定日期的覆蓋率：這是 v1 追蹤條件實際會查的方式。"""
    print("## 1. 固定日期覆蓋率（prices_for_dates）\n")
    print("| 航線 | 出發日 | 類型 | 筆數 | 最低價 TWD | 航空公司 |")
    print("|---|---|---|---|---|---|")
    hits = total = 0
    for origin, destination in ROUTES:
        for offset in DEPART_IN_DAYS:
            depart = date.today() + timedelta(days=offset)
            for one_way in (True, False):
                params = {
                    "origin": origin,
                    "destination": destination,
                    "departure_at": depart.isoformat(),
                    "one_way": str(one_way).lower(),
                    "currency": "twd",
                    "sorting": "price",
                    "limit": 30,
                }
                if not one_way:
                    params["return_at"] = (depart + timedelta(days=TRIP_LENGTH_DAYS)).isoformat()
                payload = call("/aviasales/v3/prices_for_dates", params, token)
                kind = "單程" if one_way else "來回"
                save(f"dates_{origin}_{destination}_{depart}_{'ow' if one_way else 'rt'}", payload)
                found = rows(payload)
                total += 1
                if payload.get("error"):
                    print(f"| {origin}→{destination} | {depart} | {kind} | 錯誤：{payload['error']} | | |")
                    continue
                if found:
                    hits += 1
                prices = [row.get("price") for row in found if row.get("price") is not None]
                airlines = sorted({row.get("airline", "?") for row in found})
                print(
                    f"| {origin}→{destination} | {depart} | {kind} | {len(found)} | "
                    f"{min(prices) if prices else '無資料'} | {', '.join(airlines)} |"
                )
    print(f"\n覆蓋率：{hits}/{total} 個查詢有資料\n")


def probe_latest(token: str) -> None:
    """新鮮度（found_at）和艙等（trip_class 0 = 經濟、1 = 商務）。"""
    print("## 2. 新鮮度與艙等（get_latest_prices）\n")
    print("| 航線 | 艙等 | 筆數 | 最新一筆距今（小時） | 最舊一筆距今（小時） |")
    print("|---|---|---|---|---|")
    now = datetime.now(timezone.utc)
    month_start = (date.today() + timedelta(days=DEPART_IN_DAYS[0])).replace(day=1)
    for origin, destination in ROUTES:
        for trip_class, label in ((0, "經濟"), (1, "商務")):
            payload = call(
                "/aviasales/v3/get_latest_prices",
                {
                    "origin": origin,
                    "destination": destination,
                    "beginning_of_period": month_start.isoformat(),
                    "period_type": "month",
                    "trip_class": trip_class,
                    "currency": "twd",
                    "limit": 100,
                },
                token,
            )
            save(f"latest_{origin}_{destination}_class{trip_class}", payload)
            if payload.get("error"):
                print(f"| {origin}→{destination} | {label} | 錯誤：{payload['error']} | | |")
                continue
            ages = []
            for row in rows(payload):
                try:
                    found_at = datetime.fromisoformat(str(row.get("found_at")).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if found_at.tzinfo is None:
                    found_at = found_at.replace(tzinfo=timezone.utc)
                ages.append((now - found_at).total_seconds() / 3600)
            newest = f"{min(ages):.0f}" if ages else "無 found_at"
            oldest = f"{max(ages):.0f}" if ages else "無 found_at"
            print(f"| {origin}→{destination} | {label} | {len(rows(payload))} | {newest} | {oldest} |")
    print()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    token = os.environ.get("TRAVELPAYOUTS_TOKEN")
    if not token:
        print("請先設定環境變數 TRAVELPAYOUTS_TOKEN", file=sys.stderr)
        return 1
    print(f"# Travelpayouts 小實驗（{date.today()}）\n")
    probe_exact_dates(token)
    probe_latest(token)
    print(f"原始回應已存到 {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
