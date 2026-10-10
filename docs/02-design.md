# 階段 2：系統設計（Design）

[← 回總覽](architecture.md)｜上一階段：[需求分析](01-requirements.md)｜下一階段：[開發實作](03-development.md)

## 技術選型
| 層 | 選擇 | 理由 |
|---|---|---|
| 前端 | React + TypeScript + Vite、TanStack Query、Recharts、Tailwind | 主流、型別安全、能純靜態部署到 S3；Recharts 用來畫價格圖 |
| 後端 | FastAPI + Mangum、SQLAlchemy 2.0 + Alembic、Pydantic、httpx | 非同步呼叫外部 API；Mangum 讓同一份程式在 Lambda 上執行；Alembic 讓本機 DB 和 Neon 結構一致 |
| DB | PostgreSQL 16：本機用 Docker，正式環境用 **Neon 免費版**（使用 pooler 連線） | 只換連線字串；pooler 避免 Lambda 併發時連線數爆量 |
| 背景任務 | EventBridge Scheduler + SQS | 取代 Celery/Redis，AWS 代管且免費 |
| 容器 | 同一份 backend Dockerfile（AWS Lambda Python 基底）建出**單一架構** image：arm64 推到 **ECR** 給 Lambda，amd64 只在本機和 CI 建給 kind 用；frontend 用 Nginx image（只給 k8s 用） | Lambda 不接受 multi-arch manifest，build 時要加 `--provenance=false`；見下方〈容器執行方式〉 |
| k8s | **本機 kind + CI 驗證**，用 Helm chart 部署 | 單人維護正式環境的 k8s 成本高；用來學習和展示 |
| 網域／DNS | 自有網域，DNS 放 **Cloudflare**（免費） | Route 53 每月 US$0.50；Terraform 有 Cloudflare provider |
| Email | **SES**（驗證網域 + DKIM／SPF／DMARC）；Gmail SMTP 當備案 | 用 `EmailSender` 介面抽象化，切換只改設定 |
| IaC | Terraform（state 存 S3） | 一鍵建立／刪除所有資源 |

## 容器執行方式
| 環境 | 啟動方式 |
|---|---|
| Lambda（arm64） | 基底 image 預設的 Lambda runtime 進入點，經 Mangum 執行；api／checker／notifier 用不同 handler |
| 本機 docker-compose、k8s（amd64） | 覆寫 ENTRYPOINT 和 CMD 為 `uvicorn app.main:app`（基底 image 的預設進入點是 Lambda runtime）；checker 在 k8s 用 CronJob 執行 |

## 系統架構（正式環境）
架構圖放在[總覽的〈系統架構圖〉](architecture.md#系統架構圖)，以下是各條路徑的細節。

```
使用者 ──► Cloudflare DNS（自有網域）──► CloudFront（ACM 憑證）──► S3（React 靜態檔）
                                              │ /api/*、/line/webhook
                                              │ 轉發時加上 X-Origin-Verify 密鑰標頭
                                              ▼
                       Lambda Function URL（auth NONE）──► Lambda: api（FastAPI + Mangum，含 LINE webhook 路由）
                                                          └ middleware 檢查 X-Origin-Verify，不符回 403

EventBridge Scheduler（每天）──► Lambda: price-checker
     1. 取出需要查價的 price_queries（有啟用中的 watch、非示範資料、出發日 > 今天 + 2 天）
     2. 計算今日預算，從最久沒查的 query 開始呼叫 SerpApi
        → 寫入 price_snapshots 並更新 price_baselines
     3. 套用觸發規則 → 狀態變化才寫入 alerts，送到 SQS
EventBridge Scheduler（每天）──► Lambda: price-checker（維護模式）
     - 出發日已過的 watch 標記為 expired
     - 全站有空位時，把最早排隊的 watch 轉為 active
     - 超過保留期限的 price_snapshots 彙總成每日最低價後刪除
SQS ──► Lambda: notifier ──► 站內通知（notifications）+ Email（SES）+ LINE Messaging API（有綁定才發）
        （每個管道各自記錄狀態；失敗由 SQS 重試，最後進 DLQ）

所有 Lambda ──► Neon PostgreSQL（新加坡區，pooler），Lambda 不放進 VPC，用 TLS 連線
機密資料 ──► SSM Parameter Store 標準版（含 X-Origin-Verify 密鑰）
CloudWatch：錯誤、DLQ 堆積、額度、SES 退信率 → SNS 寄 Email 告警
```

## 核心邏輯設計

### 額度策略
- **只用 SerpApi**，每月 250 次為硬上限。原本規劃用 Travelpayouts 當雷達，M0 實測後不採用（見[總覽〈M0 實驗決策紀錄〉](architecture.md#m0-實驗決策紀錄2026-10-10)）。
- **每天排程一次，輪流查價**：每次執行時計算 `本月剩餘額度 ÷ 本月剩餘天數 = 今日預算`，從最久沒查的 query 開始查，查到預算用完為止。
- **一次查價只花 1 次呼叫**：來回票的第一次回應就包含來回總價和 `price_insights`，不再用 `departure_token` 查回程；訂票連結使用回應中的 Google Flights 網址，不花額度換 `booking_token`。實作時要拿真實回應確認這一點；如果需要多次呼叫，預算以實際次數計算，全站上限也要跟著調整。
- **用量估算**：250 次／月約等於每天 8 次，所以每個 query 大約每「active query 數 ÷ 8」天查到一次。全站上限訂為 **8 個** active price_query，讓每個 query 每天都查得到；放寬到 20 個的話會變成約 2.5 天一次。
- **額度用完**：暫停查價到下個月 1 號，並發一則系統通知。動態預算正常運作時額度不會提前用完，發生時要檢查是否有異常重試。
- 相同條件的追蹤合併成同一個 price_query，額度只花一次。
- 用量記錄在 `api_usage`；供應商用 `PriceProvider` 介面（adapter pattern）抽象化，v1 有 mock 和 SerpApi 兩個實作。

### 價格基準
比較的一律是**同一個 price_query（同一個出發日期）**的價格，不跨日期平均。

| 用途 | 資料來源 |
|---|---|
| 「便宜」的判斷 | SerpApi `price_insights.typical_price_range` 的下緣（Google 的典型價格區間），每次呼叫 SerpApi 時更新 |
| 歷史最低價 | 冷啟動用 `price_insights.price_history` 的最低值當起點，之後用自己累積的 **SerpApi 價格**持續更新 |

- Google 沒有提供 `price_insights` 時（冷門航線、出發日很遠）：只用目標價觸發；「歷史新低」要等累積到至少 3 筆 SerpApi 價格才開始判斷；頁面顯示「歷史資料累積中」。

### 觸發與去重（狀態變化才通知）
每次 SerpApi 查到價格後套用以下規則。觸發原因有三種：

| 原因 | 條件 |
|---|---|
| `below_target` | 價格**從高於變成 ≤ 目標價**（狀態變化） |
| `below_typical` | 價格**從典型區間內變成低於典型區間下緣**（狀態變化） |
| `record_low` | 價格低於歷史最低價（需有足夠樣本） |

- **初始狀態**：新追蹤的 `below_target`、`below_typical` 都是 false（視為「高於」），所以第一次確認的價格若已符合條件，會通知 1 次。
- **有狀態變化就通知**：`below_target` 或 `below_typical` 由 false 變成 true 時，一定通知。
- **沒有狀態變化時套用 5% 門檻**：持續低於目標價或典型區間，或只是創下歷史新低時，要**比上次通知的價格（`last_notified_price`）再降 ≥5%** 才再通知。三種原因共用這個門檻，所以連續小幅創新低不會每次都通知。watch 從未通知過時，`record_low` 直接通知。
- **一筆價格只產生一則 alert**：同時符合多個原因時合併成一則，`alerts.reason` 記主要原因（優先順序 `below_target` > `record_low` > `below_typical`），其餘原因寫在通知內文。
- 價格回到目標價以上 → `below_target` 重置；回到典型區間內 → `below_typical` 重置。之後再跌破，視為新的一次。
- 每個 watch 的狀態記錄在 `watch_alert_states`。
- 冪等：`alerts` 唯一鍵（watch_id + snapshot_id）+ `alert_deliveries` UQ(alert_id, channel)，SQS 重送不會重複發送。
- 收到 LINE unfollow 事件 → 停止 LINE 推播，並產生一則系統通知。

**通知狀態機（`watch_alert_states.below_target`）：** `below_typical` 的形狀相同，把「目標價」換成「典型區間下緣」即可。

```mermaid
stateDiagram-v2
    state "高於目標價" as Above
    state "低於目標價" as Below
    [*] --> Above: 建立追蹤，或編輯後重置
    Above --> Below: 價格 ≤ 目標價，通知
    Below --> Below: 比上次通知再降 ≥5% 才通知
    Below --> Above: 價格回到目標價以上，不通知
```

**查價到通知的時序：**

```mermaid
sequenceDiagram
    participant EB as EventBridge Scheduler
    participant C as price-checker
    participant DB as Neon
    participant SA as SerpApi
    participant Q as SQS
    participant N as notifier
    participant CH as SES / LINE

    EB->>C: 每天觸發
    C->>DB: 取出需要查價的 price_queries，計算今日預算
    loop 從最久沒查的 query 開始，直到預算用完
        C->>SA: 查即時價格
        C->>DB: 寫入 price_snapshots，更新 price_baselines 和 api_usage
        C->>C: 套用觸發規則
        opt 需要通知
            C->>DB: 寫入 alerts，更新 watch_alert_states
            C->>Q: 送出 alert
        end
    end
    opt 本月額度已用完
        C->>DB: 暫停查價，產生系統通知
    end
    Q->>N: 觸發
    N->>DB: 寫入 notifications 和 alert_deliveries
    N->>CH: 寄 Email，有綁 LINE 再推播
    Note over Q,N: 失敗由 SQS 重試，最後進 DLQ
```

### 追蹤的生命週期
| 狀態 | 說明 |
|---|---|
| `active` | 正常查價 |
| `queued` | 排隊中：全站 active price_query 已滿 8 個，暫不查價；有空位時由每日排程依建立時間轉為 `active` |
| `paused` | 使用者暫停，不查價 |
| `expired` | 出發日已過，由每日排程自動標記；前端收到「歷史紀錄」分頁，價格圖保留 |

```mermaid
stateDiagram-v2
    [*] --> active: 新增（有名額，或對應既有 query）
    [*] --> queued: 新增（全站 8 個 query 已滿）
    queued --> active: 每日排程發現空位
    active --> paused: 使用者暫停
    paused --> active: 恢復（有名額）
    paused --> queued: 恢復（已滿）
    active --> expired: 出發日已過
    queued --> expired: 出發日已過
    paused --> expired: 出發日已過
    expired --> [*]
```

（使用者可以在任何狀態刪除追蹤，圖中省略。）

- 出發日在 2 天內就停止查價（價格已無參考價值，把額度省下來）。
- 新增或編輯追蹤時，依條件（出發地、目的地、去回程日期、艙等、人數、航空公司、是否為示範資料）算出 `query_hash`：已存在就沿用該 price_query，否則建立新的，再把 `watches.price_query_id` 指過去。改日期等於換一個查詢，價格歷史從頭累積。
- 編輯目標價、日期或其他查價條件後，該 watch 的 `watch_alert_states` 重置為初始狀態，避免沿用舊條件的通知狀態。
- 新追蹤若對應到已經在查價的 price_query，不佔新名額，直接 `active`；需要新 query 而全站已滿時才進 `queued`。恢復 `paused` 的追蹤時套用同樣規則。
- 沒有任何 `active` watch 的 price_query 不再查價，但保留價格歷史。

## 帳號與驗證設計
- v1：註冊、登入、Argon2、JWT access token（15 分鐘）+ refresh token（7 天，HttpOnly + `Secure` + `SameSite=Strict` Cookie，存 DB，可撤銷）、登出、連續失敗鎖定
- **Email 驗證（v1）**：註冊後寄驗證信，連結 24 小時有效、只能用一次；未驗證的帳號可以登入和瀏覽，但不能新增追蹤，也不會收到價格通知 Email；重寄驗證信有頻率限制
- **示範帳號**：`POST /auth/demo` 直接取得示範帳號的 session；除了登出和 refresh 以外，所有寫入 API 對示範帳號回 403；資料由 seed 腳本預先建立（多個追蹤 + 價格歷史 + 通知），不會被 checker 查價
- LINE 綁定：`GET /me/line/link` → LINE 授權頁（`bot_prompt=aggressive` 引導加好友）→ callback 驗證 `state`（使用者 + 一次性 nonce）→ 寫入 `line_accounts`
  - LINE Login channel 和 Messaging API channel **必須建在同一個 Provider 底下**，兩邊的 `userId` 才會一致
- v2：忘記密碼、LINE 登入（共用同一個 callback，用 `state` 區分）
- 權限：資料一律檢查 owner；`admin` 只能看用量和統計

**註冊到綁定 LINE 的時序：**

```mermaid
sequenceDiagram
    actor U as 使用者
    participant FE as 前端
    participant API as api Lambda
    participant DB as Neon
    participant SES as SES
    participant LINE as LINE Platform

    U->>FE: 填寫 Email 和密碼
    FE->>API: POST /auth/register
    API->>DB: 建立 users 和 email_verifications
    API->>SES: 寄驗證信
    U->>FE: 點信中的驗證連結
    FE->>API: POST /auth/verify-email
    API->>DB: 寫入 email_verified_at
    U->>FE: 登入
    FE->>API: POST /auth/login
    API-->>FE: access token 和 refresh cookie

    Note over U,LINE: 以下為 M2 的 LINE 綁定
    U->>FE: 點「綁定 LINE」
    FE->>API: GET /me/line/link
    API-->>FE: 導向 LINE 授權頁（state 含使用者和一次性 nonce）
    U->>LINE: 同意授權並加好友
    LINE-->>API: 瀏覽器導回 GET /auth/line/callback
    API->>API: 驗證 state
    API->>LINE: 用 code 換取 userId
    API->>DB: 寫入 line_accounts
    API-->>FE: 導回設定頁
```

## 資料模型
圖中只畫資料表之間的關聯和主鍵、外鍵、唯一鍵，型別僅為示意；完整欄位以圖下方的清單為準。`airports` 和 `api_usage` 沒有外鍵關聯，所以不在圖中。

```mermaid
erDiagram
    users ||--o{ refresh_tokens : has
    users ||--o{ email_verifications : has
    users ||--o| line_accounts : links
    users ||--|| notification_settings : has
    users ||--o{ watches : owns
    users ||--o{ notifications : receives
    price_queries ||--o{ watches : serves
    price_queries ||--o{ price_snapshots : records
    price_queries ||--o{ price_daily_lows : aggregates
    price_queries ||--o| price_baselines : has
    watches ||--o{ watch_airlines : filters
    airlines ||--o{ watch_airlines : selected
    watches ||--o| watch_alert_states : has
    watches ||--o{ alerts : triggers
    price_snapshots |o--o{ alerts : source
    alerts ||--o{ alert_deliveries : delivers
    alerts |o--o{ notifications : shown_as

    users {
        int id PK
        string email UK
    }
    refresh_tokens {
        int id PK
        int user_id FK
    }
    email_verifications {
        int id PK
        int user_id FK
    }
    line_accounts {
        int user_id PK
        string line_user_id UK
    }
    notification_settings {
        int user_id PK
    }
    price_queries {
        int id PK
        string query_hash UK
    }
    watches {
        int id PK
        int user_id FK
        int price_query_id FK
        string status
    }
    watch_airlines {
        int watch_id FK
        string airline_iata FK
    }
    airlines {
        string iata PK
    }
    price_snapshots {
        int id PK
        int price_query_id FK
        string provider
    }
    price_daily_lows {
        int price_query_id FK
        date date
        string provider
    }
    price_baselines {
        int price_query_id PK
    }
    watch_alert_states {
        int watch_id PK
    }
    alerts {
        int id PK
        int watch_id FK
        int snapshot_id FK
    }
    alert_deliveries {
        int alert_id FK
        string channel
    }
    notifications {
        int id PK
        int user_id FK
        int alert_id FK
    }
```

- `users`(id, public_id, email UQ, password_hash, display_name, role, is_demo, is_active, failed_login_count, locked_until, email_verified_at NULL, timestamps)
- `refresh_tokens`(id, user_id, token_hash, expires_at, revoked_at)
- `email_verifications`(id, user_id, token_hash, expires_at, used_at)
- `line_accounts`(user_id PK/FK, line_user_id UQ, display_name, is_friend, linked_at)
- `notification_settings`(user_id, email_enabled, line_enabled)
- `airports`(iata PK, name_zh, city, country)、`airlines`(iata PK, name_zh)
- `price_queries`(id, query_hash UQ, origin, destination, depart_date, return_date, cabin, adults, airlines_key, is_demo, last_checked_at)：`adults` 和 `is_demo` 都納入 `query_hash`，人數不同的追蹤不會合併，示範資料也不會和真實查詢共用同一筆
- `watches`(id, public_id, user_id, **price_query_id FK**, origin, destination, depart_date, return_date NULL, trip_type, cabin, adults, **target_price NOT NULL**, currency, **status**(active/queued/paused/expired), timestamps)、`watch_airlines`(watch_id, airline_iata)
- `price_snapshots`(id, price_query_id, provider, price, currency, airline_iata, stops, booking_url, observed_at)：只新增不修改
- `price_daily_lows`(price_query_id, date, provider, min_price, currency)，PK(price_query_id, date, provider)：超過保留期限的 snapshots 彙總到這裡
- `price_baselines`(price_query_id PK, typical_low, typical_high, record_low, sample_count, source, updated_at)
- `watch_alert_states`(watch_id PK, below_target, below_typical, last_notified_price, last_notified_at)
- `alerts`(id, watch_id, snapshot_id, reason, price, created_at, UQ(watch_id, snapshot_id))：價格警示的業務紀錄；`price` 自帶一份，snapshot 因保留期限被刪除時 `snapshot_id` 設為 NULL
- `notifications`(id, user_id, type(price_alert/system), title, body, link, alert_id NULL, is_read, created_at)：站內通知中心
- `alert_deliveries`(alert_id, channel, status, attempts, sent_at)，UQ(alert_id, channel)
- `api_usage`(provider, month, count)

## API 草案（/api/v1，FastAPI 自動產生 OpenAPI 文件）
- Auth：`POST /auth/register|verify-email|resend-verification|login|refresh|logout|demo`、`GET /me`
- LINE：`GET /me/line/link`、`GET /auth/line/callback`、`GET/DELETE /me/line`、`POST /line/webhook`
- Watches：`GET/POST /watches`（`?status=` 篩選）、`GET/PATCH/DELETE /watches/{id}`、`GET /watches/{id}/prices?range=`、`GET /watches/{id}/baseline`
- 通知：`GET /notifications`、`PATCH /notifications/{id}/read`、`POST /notifications/read-all`、`GET/PATCH /me/notification-settings`
- 參考資料：`GET /airports?q=`、`GET /airlines`；Admin：`GET /admin/usage`
- 健康檢查：`GET /health`

## 前端頁面
首頁（含「以示範帳號瀏覽」按鈕）→ 註冊／登入 → 我的追蹤列表（進行中／歷史紀錄分頁）→ 新增／編輯追蹤 → 追蹤詳情 → 通知中心（鈴鐺 + 未讀數）→ 設定（個人資料、LINE 綁定與 QR code、通知開關）

**追蹤詳情的價格圖：** SerpApi 價格畫成主線，加上目標價線和典型價格區間色帶；下方列出最近通知和訂票連結。

## 附圖索引
| 圖 | 位置 |
|---|---|
| 系統架構圖 | [總覽〈系統架構圖〉](architecture.md#系統架構圖) |
| 通知狀態機、查價到通知的時序圖 | [〈觸發與去重〉](#觸發與去重狀態變化才通知) |
| 追蹤生命週期 | [〈追蹤的生命週期〉](#追蹤的生命週期) |
| 註冊到綁定 LINE 的時序圖 | [〈帳號與驗證設計〉](#帳號與驗證設計) |
| ERD | [〈資料模型〉](#資料模型) |

