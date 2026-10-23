# M1 子專案 #4：PriceProvider + 每日查價 + 額度預算 — 設計

日期：2026-10-23
狀態：待審閱
相關文件：[architecture.md](../../architecture.md)、[02-design.md](../../02-design.md)、[#3 追蹤功能設計](2026-10-23-m1-watches-design.md)

## 背景與目標
M1 的第 4 個子專案：查價來源（mock 與 SerpApi）、每日查價指令、額度預算、價格快照與基準，以及 US-04、US-05 需要的兩個讀取 API。

**完成標準：**
- 下方〈測試〉列出的案例全部通過；測試完全不連網路、不花 SerpApi 額度
- 本機用 mock 執行 `python -m app.jobs.check_prices` 後，`GET /watches/{id}/prices`、`/baseline` 有資料；示範帳號登入就看得到價格歷史
- 用 SerpApi 錄製單程與指定航空公司的真實回應（共花 2 次額度），並回答 M0 留下的問題
- PR 上的 CI 全綠

## 不在範圍內
觸發規則、alerts、通知（#5）；額度用完時的系統通知（#5）；管理員用量頁 US-10 與 `require_admin`（之後再做）；`price_daily_lows` 與舊快照彙總（資料量小，需要時再做）；每日排程的觸發（#7）；把 Google 的 `price_history` 畫進價格圖。

## 設計決定
| 項目 | 決定 | 理由 |
|---|---|---|
| 剩餘額度來源 | 每次執行先呼叫 SerpApi `/account.json`（不花額度），以 `plan_searches_left` 為準；自己另外記錄 `api_usage` | 程式以外用掉的次數（網站試查、實驗腳本）也算得到，不用猜 SerpApi 的重置日期 |
| 今日預算 | `ceil(剩餘次數 ÷ 本月剩餘天數)`，本月剩餘天數含今天 | 無條件進位才不會在月底剩少量額度時每天都是 0；預算永遠不超過剩餘次數，不會超支 |
| 寫入方式 | 每個 query 查完各自 commit | 中途出錯時已花的額度不白費；失敗的明天優先重查 |
| 防止重複查價 | 用條件式 UPDATE「搶下」query：今天還沒查過才能搶到 | 排程重試或兩個程式同時跑時不會重複花額度；Neon pooler 下 session 級 advisory lock 不可靠，所以不用鎖 |
| API key 保護 | httpx log 調到 WARNING；錯誤訊息遮掉 key；有測試把關 | SerpApi 要求 key 放在網址參數，httpx 預設會在 log 印出完整網址 |

## 資料表
| 表 | 欄位 | 說明 |
|---|---|---|
| `price_queries`（加欄位） | `last_checked_at`（`timestamptz`，NULL = 從沒查過） | |
| `price_snapshots` | id、price_query_id（FK，index）、provider（`serpapi`／`mock`）、price（TWD 整數，> 0）、airline_iata（`String(2)`，NULL 可）、stops（≥ 0）、booking_url（Text）、observed_at（`timestamptz`） | 只新增不修改；`(price_query_id, observed_at)` 加索引 |
| `price_baselines` | price_query_id（PK、FK）、typical_low、typical_high（NULL 可）、record_low（NULL 可）、history_seeded（預設 false）、sample_count（預設 0）、updated_at | 每個 query 一筆 |
| `api_usage` | provider、month（`String(7)`，例如 `2026-10`）、count；PK(provider, month) | 自己記錄的呼叫次數 |

和 02-design 的差異：快照拿掉 `currency`（v1 一律 TWD）；基準拿掉 `source`，改用 `history_seeded`。

### 基準的更新規則（每次查到價格時）
- 有 insights：`typical_low`／`typical_high` 改成最新的典型區間；第一次拿到 insights（`history_seeded` 為 false）且有歷史最低值時，`record_low = min(record_low, 歷史最低值)`，`history_seeded = true`
- 沒有 insights：典型區間保留上次的值
- `record_low = min(record_low, 這次價格)`
- `sample_count += 1`
- `history_ready`（不存，API 計算）= `history_seeded` 或 `sample_count >= 3`

查不到任何航班時：不存快照、不更新基準，但 `last_checked_at` 維持「已查」（額度已花）、`api_usage` 照樣加 1。

## 查價來源（`app/modules/prices/providers/`）
### 介面
```python
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
    lowest: Offer | None          # None = 查不到航班
    booking_url: str | None
    insights: Insights | None

class ProviderError(Exception): ...

class PriceProvider(Protocol):
    name: str
    async def search(self, cond: QueryConditions) -> SearchResult: ...
    async def remaining_quota(self) -> int | None: ...   # None = 不限（mock）
```

### SerpApi
- `GET https://serpapi.com/search.json`，參數：`engine=google_flights`、`departure_id`、`arrival_id`、`outbound_date`、`return_date`（只有來回才帶）、`type`（來回 1、單程 2）、`travel_class`（economy 1、premium_economy 2、business 3、first 4）、`adults`、`include_airlines`（有指定才帶，逗號分隔）、`currency=TWD`、`hl=zh-TW`、`gl=tw`、`api_key`
- 最便宜選項：`best_flights` 與 `other_flights` 合併後取 `price` 最低的一筆；`airline_iata` 取第一段 `flight_number` 空白前的部分（取不到為 None）；`stops = len(flights) - 1`
- `booking_url = search_metadata.google_flights_url`
- insights：`price_insights.typical_price_range` 有兩個數字才算有；`history_low = min(price_history 的價格)`，沒有歷史則為 None
- 錯誤處理：網路錯誤、逾時（60 秒）、HTTP 非 2xx、回應的 `error` 欄位 → `ProviderError`；但 `error` 表示「查無航班」時（實際字樣以錄製結果為準）→ `SearchResult(lowest=None, ...)`
- `remaining_quota`：`GET https://serpapi.com/account.json`，回傳 `plan_searches_left`；失敗 → `ProviderError`
- 所有錯誤訊息先把 key 換成 `***`；`logging.getLogger("httpx")` 設為 WARNING

### Mock
- 不連網路；`remaining_quota` 回 None
- 以 `sha256(query_hash)` 決定基準價 `base`（3,000～15,000，取到百位）；以 `sha256(query_hash + 日期)` 決定當天價格 = `base` 的 85%～120%（取到十位）
- insights：`typical_low = base × 0.9`、`typical_high = base × 1.2`、`history_low = base × 0.8`（取整）
- `lowest.airline_iata`：有指定航空公司就用第一個，否則 None；`stops = 0`；`booking_url = None`

### 設定
- `PRICE_PROVIDER`：`mock`（預設）或 `serpapi`
- `SERPAPI_KEY`（`SecretStr`）：`PRICE_PROVIDER=serpapi` 時必填，缺少就啟動失敗
- `get_provider(settings, client: httpx.AsyncClient | None = None) -> PriceProvider`

## 每日查價（`app/modules/prices/checker.py`、`python -m app.jobs.check_prices`）
`today` 為台灣時間的今天，`today_start` 為台灣時間今天 00:00。

1. **要查的 query**：至少一個 `active` 追蹤、`is_demo = false`、`depart_date > today + 2`、`last_checked_at IS NULL OR last_checked_at < today_start`；依 `last_checked_at NULLS FIRST, id` 排序
2. **今日預算**：`remaining = provider.remaining_quota()`。失敗 → 不查任何 query，指令以非 0 結束。`remaining is None`（mock）→ 預算 = 要查的數量；`remaining == 0` → 印出「本月額度已用完」並結束；否則 `daily_budget(remaining, today) = ceil(remaining / 本月剩餘天數)`
3. **逐一處理**前 `預算` 個 query：
   1. 搶下：`UPDATE price_queries SET last_checked_at = now() WHERE id = :id AND (last_checked_at IS NULL OR last_checked_at < :today_start) RETURNING id`，記下原本的值，commit；沒有回傳 → 跳過（不計入失敗）
   2. `provider.search(條件)`
   3. 成功：寫快照（有最低價時）、更新基準、`api_usage` 本月加 1（`INSERT ... ON CONFLICT DO UPDATE`），commit
   4. `ProviderError`：把 `last_checked_at` 還原成原本的值並 commit，不加用量；連續 3 次失敗就停止
4. 回傳並印出摘要：`checked`、`no_result`、`failed`、`skipped`、`remaining`（執行前的剩餘次數）

## 價格 API（`app/modules/prices/router.py`）
需登入（`CurrentUser`），追蹤不存在或屬於別人 → 404「找不到追蹤」（沿用 watches 的 `get_watch`）；示範帳號可以讀。

| 端點 | 回傳 |
|---|---|
| `GET /watches/{public_id}/prices?range=30d\|90d\|all`（預設 `90d`） | `[{observed_at, price, airline_iata}]`，依 observed_at 由舊到新；`range` 以現在時間往回算；不合法的值 → 422 |
| `GET /watches/{public_id}/baseline` | `latest_price`、`latest_observed_at`、`last_checked_at`、`typical_low`、`typical_high`、`record_low`、`history_ready`；沒有資料的欄位為 null，`history_ready` 為 false |

## 示範資料
`app.seeds.demo` 在建立示範追蹤後，對示範帳號「進行中」與「已過期」兩個追蹤的 query，若還沒有快照，用 mock 的價格規則產生 30 天的每日快照（每天台灣時間 09:00，provider `mock`）與基準：
- 進行中：`today - 29` ～ `today`
- 已過期：出發日前 32 天 ～ 出發日前 3 天
- 基準：以 mock insights 打底（`history_seeded = true`），`sample_count = 30`，`record_low` 取 30 筆與歷史最低的較小值

## 錄製真實回應（`backend/scripts/record_serpapi_fixtures.py`）
- 只在開發時手動執行，從環境變數 `SERPAPI_KEY` 讀 key
- 查兩次：TPE→NRT 單程（今天 + 60 天，經濟艙 1 人）、TPE→NRT 來回且 `include_airlines=JX`（今天 + 60 天出發、5 天後回程）
- 存到 `backend/tests/fixtures/serpapi/one_way.json`、`with_airlines.json`；M0 的來回回應複製為 `round_trip.json`
- 存檔前檢查內容是否含 key，含有就中止不存

## 測試
| 範圍 | 案例 |
|---|---|
| 設定 | `PRICE_PROVIDER` 預設 `mock`；設成 `serpapi` 但沒有 key → 驗證錯誤 |
| SerpApi 解析 | 三份錄製回應各自取出正確的最低價、航空公司代碼、轉機次數、訂票連結；有／沒有 `price_insights` 的處理；「查無航班」回應 → `lowest is None`；其他 `error` → `ProviderError` |
| SerpApi 請求 | 用 `httpx.MockTransport`：單程不帶 `return_date`、`type=2`；來回 `type=1`；艙等對應；有航空公司才帶 `include_airlines`；逾時、HTTP 500 → `ProviderError`；`remaining_quota` 解析 `plan_searches_left` |
| key 保護 | `ProviderError` 訊息不含 key；用 `caplog` 確認查價過程的 log 不含 key |
| Mock | 同一天同一 query 價格相同；不同日期價格不同；價格在 base 的 85%～120% |
| 預算 | `daily_budget(250, 10/1)` = 9（31 天）；`(5, 10/22)` = 1（10 天）；`(0, …)` = 0；`(7, 10/31)` = 7 |
| 基準 | 第一次有 insights 時以歷史最低打底；之後取較低值；沒有 insights 時保留典型區間；`history_ready` 兩種成立條件與不成立 |
| 查價流程 | 只查符合條件的 query（排除 paused-only、示範、出發日在 2 天內、今天已查）；順序 NULLS FIRST；預算限制；搶不到（模擬另一個程式先查）→ 跳過；失敗 → 還原 `last_checked_at`、不加用量；連續 3 次失敗停止；查不到航班 → 不存快照但加用量；`remaining_quota` 失敗 → 不查任何 query；`remaining == 0` → 不查 |
| 價格 API | `range` 篩選與排序；別人的追蹤 → 404；示範帳號可讀；未查過 → 欄位 null、`history_ready` false |
| 示範 seed | 兩個示範追蹤各有 30 筆快照與基準；重跑不重複 |
| 入口 | `app.jobs.check_prices` 加進 `tests/test_entrypoints.py` |

## 文件更新（同一個分支）
- `docs/02-design.md`：〈額度策略〉改為以 SerpApi 回報的剩餘次數為準、預算無條件進位、搶下 query 防重複；〈資料模型〉更新 `price_snapshots`、`price_baselines`、`price_queries.last_checked_at`，`price_daily_lows` 標註延後
- `docs/architecture.md`：新增〈2026-10-23 #4 決策紀錄〉，記錄上方〈設計決定〉與錄製結果（指定航空公司時是否有 `price_insights`、查無航班的回應格式）；〈M0 SerpApi 實驗紀錄〉第 4 項改為已確認
- `docs/06-operations.md`：事件處理手冊新增「SerpApi key 外洩」：到 SerpApi 重新產生 key → 更新 SSM（正式）或 `backend/.env`（本機）→ 重新部署
