# M1 子專案 #3：機場／航空公司資料 + 追蹤 CRUD + 生命週期 — 設計

日期：2026-10-23
狀態：待審閱
相關文件：[architecture.md](../../architecture.md)、[01-requirements.md](../../01-requirements.md)、[02-design.md](../../02-design.md)、[#2 帳號系統設計](2026-10-23-m1-auth-design.md)

## 背景與目標
M1 的第 3 個子專案，對應 US-02（新增追蹤）、US-03（編輯、暫停、刪除、查看已過期的追蹤），以及 01-requirements〈已確定的決策〉的追蹤上限：每人 3 個、全站 8 個佔名額的 price_query。

這次建立 `price_queries` 表，因為追蹤要指向它，名額也靠它計算；實際查價是 #4。

**完成標準：**
- 下方〈測試〉列出的案例全部通過
- 本機 `docker compose up` 後，可以用 API 查機場和航空公司，並新增、編輯、暫停、恢復、刪除追蹤；示範帳號看得到 3 個示範追蹤
- PR 上的 CI 全綠

## 不在範圍內
查價與 `price_queries.last_checked_at`（#4）、每日排程的觸發（#4 呼叫本次的維護指令；正式環境排程在 #7）、排隊追蹤啟用時的系統通知與編輯後重置 `watch_alert_states`（#5，相關資料表那時才有）、價格與基準 API（`/watches/{id}/prices`、`/baseline`，#4～#5）、多幣別。

## 設計決定
| 項目 | 決定 | 理由 |
|---|---|---|
| 機場資料 | 精選清單約 60 筆，全部有中文名稱，放 repo 的 CSV | 公開資料只有英文名稱、要寫匯入程式；冷門航線常沒有 `price_insights`。缺的目的地再加一行即可 |
| 排隊啟用時機 | 名額空出時**立刻**依建立時間啟用 | 原本 02-design 是每日排程才啟用，空出的名額最多閒置一天 |
| 名額並發 | 所有會影響名額的操作先拿**全站 advisory lock**，一次處理一個 | 避免兩個請求同時讀到「還有空位」而超過 8 個；使用者極少，排隊只需幾毫秒 |
| 資料模型 | 查價條件只存在 `price_queries`；拿掉 `watch_airlines`、`watches.trip_type`、`watches.currency` | 避免同一份條件存兩處；航空公司本來就是查價條件的一部分；v1 一律 TWD |

## 資料表
| 表 | 欄位 | 說明 |
|---|---|---|
| `airports` | iata（PK，`String(3)`）、name_zh、city_zh、country（ISO 3166-1 alpha-2） | 出發地 = `country = 'TW'` |
| `airlines` | iata（PK，`String(2)`）、name_zh | |
| `price_queries` | id、query_hash（唯一，`String(64)`）、origin（FK airports）、destination（FK airports）、depart_date、return_date（NULL = 單程）、cabin、adults、airlines（`ARRAY(String(2))`，排序後，空陣列 = 全部）、is_demo、created_at | 「查什麼」：條件相同的追蹤共用一筆 |
| `watches` | id、public_id（UUID，唯一）、user_id（FK users，`ON DELETE CASCADE`）、price_query_id（FK price_queries）、target_price、status、created_at、updated_at | 「誰在追、目標價多少、什麼狀態」 |

- `cabin`：`economy`／`premium_economy`／`business`／`first`，用 check constraint 限制
- `adults`：1～9；`target_price`：1～1,000,000（TWD）；`status`：`active`／`queued`／`paused`／`expired`，都用 check constraint 限制
- `watches` 在 `(status)` 和 `(user_id)` 加索引；price_query 被刪除前一定沒有追蹤指向它（本次不刪 price_query）

### 參考資料
- `backend/app/seeds/data/airports.csv`、`airlines.csv`，UTF-8，含標題列
- 機場：台灣 4 個（TPE、TSA、KHH、RMQ）+ 日本、韓國、港澳、中國主要城市、東南亞、少數歐美澳的熱門目的地，合計約 60 筆
- 航空公司：有台灣航線的約 30 家
- `python -m app.seeds.reference`：以 IATA 代碼 upsert（不存在就新增、存在就更新名稱），可重複執行；不刪除 CSV 中沒有的列（可能已被 price_query 引用）
- compose 的 api 啟動順序：`alembic upgrade head` → `app.seeds.reference` → `app.seeds.demo` → uvicorn（示範追蹤需要參考資料）

## 程式結構
```
backend/app/
├─ core/clock.py              # taipei_today() -> date
├─ modules/reference/
│  ├─ models.py               # Airport、Airline
│  ├─ schemas.py
│  └─ router.py               # GET /airports、GET /airlines
├─ modules/watches/
│  ├─ models.py               # PriceQuery、Watch
│  ├─ schemas.py              # 輸入驗證與回傳格式
│  ├─ slots.py                # 全站鎖、query_hash、佔名額判斷、補位
│  ├─ service.py              # 新增、編輯、暫停／恢復、刪除、過期
│  └─ router.py
├─ jobs/maintenance.py        # python -m app.jobs.maintenance
└─ seeds/
   ├─ reference.py
   ├─ data/airports.csv、airlines.csv
   └─ demo.py                 # 加入 3 個示範追蹤
```
- service 的函式接收 `today: date` 參數，router 和維護指令傳入 `taipei_today()`，測試可以指定日期
- 「今天」一律以台灣時間（`Asia/Taipei`）計算

## API
所有端點在 `/api/v1` 底下，錯誤格式沿用 `{"detail": "..."}`。

### 參考資料（不需登入）
- `GET /airports`：全部機場，依 iata 排序；每筆 `iata`、`name_zh`、`city_zh`、`country`、`is_origin`（`country == "TW"`）
- `GET /airlines`：全部航空公司，依 iata 排序；每筆 `iata`、`name_zh`

### 追蹤（需登入）
新增、修改、刪除使用 `WritableUser`，示範帳號回 403；讀取用 `CurrentUser`。

| 端點 | 行為 |
|---|---|
| `GET /watches?status=...` | 自己的追蹤，依 created_at 新到舊。`status` 可重複帶（例如 `?status=active&status=queued&status=paused`），不帶就回全部；不合法的值回 422 |
| `POST /watches` | 新增，回 201 和追蹤內容 |
| `GET /watches/{public_id}` | 單筆 |
| `PATCH /watches/{public_id}` | 部分更新，只處理有送出的欄位；回 200 和更新後內容 |
| `DELETE /watches/{public_id}` | 刪除，回 204 |

**回傳格式（`WatchOut`）**：`public_id`、`origin`、`destination`、`depart_date`、`return_date`、`trip_type`（`one_way`／`round_trip`，由 return_date 推算）、`cabin`、`adults`、`airlines`、`target_price`、`status`、`created_at`、`updated_at`。查價條件取自對應的 price_query。

**新增的輸入（`WatchCreate`）**：`origin`、`destination`、`depart_date`、`return_date`（選填）、`cabin`（預設 `economy`）、`adults`（預設 1）、`airlines`（預設空陣列）、`target_price`。

**修改的輸入（`WatchUpdate`）**：以上欄位都選填，另加 `status`（只接受 `active`、`paused`）。`return_date` 明確送 `null` 代表改成單程；沒送代表不改。

### 輸入驗證（422）
`today` = 台灣時間的今天。
- `origin` 必須是 `country = 'TW'` 的機場；`destination` 必須存在於 `airports`，且不等於 `origin`
- `depart_date`：`today + 3 天` ≤ 出發日 ≤ `today + 330 天`（兩端都含）。下限是因為出發前 2 天就停止查價；上限是 Google Flights 大約開放的範圍
- `return_date`：不早於 `depart_date`，且 ≤ `today + 330 天`
- `adults` 1～9；`target_price` 1～1,000,000；`airlines` 每個代碼都要存在於 `airlines` 表，自動去重並排序
- PATCH：任何查價條件欄位有變動時，把「變動後的完整條件」重新跑一次上面的驗證；只改目標價或狀態時不檢查日期
- PATCH 的 `status` 為 `expired` 或 `queued` → 422

需要查 DB 的驗證（機場、航空公司是否存在）在 service 層做，錯誤同樣回 422，`detail` 說明是哪個欄位。

### 業務規則錯誤
| 情況 | 回應 |
|---|---|
| 追蹤不存在或屬於別人 | 404「找不到追蹤」 |
| 已有 3 個 `active` + `queued` 時新增，或從 `paused` 恢復 | 409「每人最多 3 個追蹤」 |
| 修改 `expired` 的追蹤 | 409「已過期的追蹤不能修改」（刪除可以） |

## 名額與生命週期
所有會影響名額的操作（新增、編輯、暫停、恢復、刪除、每日維護）在同一個 transaction 開頭呼叫 `pg_advisory_xact_lock(<固定常數>)`，transaction 結束時自動釋放。

### 佔名額的定義
一筆 price_query **佔名額**：至少有 1 個 `active` 追蹤、`is_demo = false`，而且 `depart_date > today + 2 天`。全站上限 `MAX_ACTIVE_QUERIES = 8`。每人上限 `MAX_WATCHES_PER_USER = 3`（只算 `active` + `queued`）。

### query_hash
把 `origin`、`destination`、`depart_date`（ISO 格式）、`return_date`（ISO 或 null）、`cabin`、`adults`、`airlines`（排序後）、`is_demo` 組成 key 排序、無空白的 JSON，取 SHA-256 hex。已存在就沿用該 price_query，否則新增。示範帳號的追蹤 `is_demo = true`，不會和真實查詢共用。

### 決定新狀態（新增、恢復、編輯查價條件時共用）
1. 對應的 price_query 已經佔名額 → `active`（不多佔）
2. 出發日在 2 天內 → `queued`（啟用了也查不到，等著被標成過期）
3. 全站佔名額的 query 少於 8 個，或這是示範資料 → `active`
4. 否則 → `queued`

### 各操作
| 操作 | 規則 |
|---|---|
| 新增 | 檢查每人上限 → 找到或建立 price_query → 決定新狀態 |
| 編輯查價條件 | 改指向新的 price_query；`paused` 維持 `paused`，其他先視為不佔名額再決定新狀態（可能從 `active` 變 `queued`） |
| 只改目標價 | 不影響狀態與名額 |
| 暫停（`status: paused`） | `active`／`queued` → `paused`；已經 `paused` 則不變 |
| 恢復（`status: active`） | 只對 `paused` 有效：檢查每人上限 → 決定新狀態。對 `active`／`queued` 送 `active` 不改變任何東西 |
| 刪除 | 刪除追蹤；price_query 保留（#4 的價格歷史會掛在它上面） |

### 補位
每個操作在同一個 transaction 的最後執行補位：
1. `queued` 追蹤若對應的 query 已經佔名額 → `active`
2. 全站佔名額的 query 少於 8 個時，從 `depart_date > today + 2 天` 的 `queued` 追蹤中取 **created_at 最早**的一個，啟用它和同一個 query 的所有 `queued` 追蹤；重複直到額滿或沒有可啟用的追蹤

### 每日維護
`python -m app.jobs.maintenance`：在全站鎖內把 `depart_date < today`、狀態不是 `expired` 的追蹤標成 `expired`，然後補位，最後印出過期與啟用的數量。重複執行沒有副作用。Windows 上用 `SelectorEventLoop`（同 `app.seeds.demo`）。

## 示範帳號
`app.seeds.demo` 在示範帳號建立後，若示範帳號還沒有任何追蹤，就建立 3 個（`is_demo = true` 的 price_query，直接寫 DB、不經過 API 驗證）：
1. `active`：TPE → NRT 來回，經濟艙 1 人，出發日為今天 + 60 天、5 天後回程，目標價 9,000
2. `paused`：TPE → BKK 單程，經濟艙 1 人，出發日為今天 + 90 天，目標價 4,500
3. `expired`：KHH → KIX 來回，經濟艙 2 人，出發日為今天 − 30 天、4 天後回程，目標價 15,000

示範 query 不佔名額，也不會被 #4 查價。

## 測試
沿用既有方式：連真實 Postgres，每個測試結束 rollback；測試用 `today` 固定為 `date(2026, 11, 1)`。

| 範圍 | 案例 |
|---|---|
| 參考資料 | seed 執行兩次筆數不變；改了名稱再 seed 會更新；`/airports` 中 TPE 的 `is_origin` 為 true、NRT 為 false；不需登入 |
| query_hash | 相同條件得到相同 hash；airlines 順序不同 hash 相同；人數、`is_demo` 不同 hash 不同 |
| 驗證 | 出發日 today+3、today+330 可以；today+2、today+331 → 422；回程早於出發、出發地 NRT、目的地等於出發地、不存在的機場或航空公司 → 422；airlines 去重排序 |
| 權限 | 未登入 → 401；別人的追蹤 GET／PATCH／DELETE → 404；示範帳號 POST／PATCH／DELETE → 403、GET 可以 |
| 列表 | 只看到自己的；`status` 篩選（單一、多個）；新到舊排序 |
| 每人上限 | 3 個 `active`／`queued` 後第 4 個 → 409；`paused`、`expired` 不算；恢復時已有 3 個 → 409 |
| 全站名額 | 8 個不同 query 後第 9 個 → `queued`；相同條件的新追蹤（別的使用者）→ `active` 且不多佔；示範 query、出發日在 2 天內的 query 不佔名額 |
| 補位 | 刪除、暫停、編輯後，最早排隊的立刻變 `active`；依 created_at 而非 id；同 query 的排隊者一起啟用；出發日在 2 天內的排隊者不啟用；別人建立相同 query 後排隊者轉 `active` |
| 編輯 | 只改目標價不影響狀態；改條件後指向新 query，額滿時從 `active` 變 `queued`；`paused` 改條件後仍是 `paused`；改成單程（`return_date: null`）；修改 `expired` → 409；status 設 `expired`／`queued` → 422 |
| 暫停／恢復 | 暫停釋出名額；恢復時額滿 → `queued` |
| 每日維護 | 出發日已過 → `expired` 並補位；出發日是今天的不過期；重複執行結果相同 |
| 全站鎖 | 寫入操作執行中，`pg_locks` 可以看到這把 advisory lock |
| 示範 seed | 建立 3 個示範追蹤，重跑不重複；示範帳號 `GET /watches` 看得到 |
| migration | 既有的 upgrade → downgrade 測試自動涵蓋新表 |

## 文件更新（同一個分支）
- `docs/02-design.md`：
  - 資料模型：`watches` 精簡、拿掉 `watch_airlines`、`price_queries.airlines` 改陣列
  - 〈追蹤的生命週期〉：名額空出時立刻補位、出發前 2 天的 query 不佔名額
  - API 草案：`GET /airports` 不帶 `?q=`；PATCH 可改 status
- `docs/01-requirements.md`：US-02 驗收條件「有空位後由每日排程依建立時間依序啟用」改為「名額空出時立刻依建立時間啟用」；系統通知標註於 #5 補上
- `docs/architecture.md`：新增〈2026-10-23 #3 決策紀錄〉，記錄上方〈設計決定〉四項
