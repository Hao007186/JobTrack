# FareWatch 最低價機票即時通知網站 — 架構規劃（依 SDLC 6 階段）

## Context
產品名稱 **FareWatch**（repo 資料夾為 `Project_TicketTrack`）。
使用者註冊帳號 → 設定航線／日期／目標價／航空公司 → 系統每 6 小時查價、累積價格歷史 → 價格**跌破目標價、低於 Google 典型價格區間，或創下歷史新低**時，發送站內通知 + Email；**有綁定 LINE 的使用者額外收到 LINE 推播**，訊息附訂票連結。
定位是**單人維護的展示型作品集**，**預算約每年 US$10（只有網域費用）**，同時涵蓋 前端／後端／API／Docker／CI/CD／k8s／AWS／DevOps，並依**軟體開發生命週期（SDLC）6 階段**組織。
本階段**不寫程式碼**，只產出架構文件。

## 文件狀態
- 目前為**待審閱草稿（第 3 版）**，6 個階段都放在這份文件裡
- 2026-10-09 審閱後已套用 12 項決策，見文末〈審閱決策紀錄〉
- 2026-10-10 第二次審閱後再套用 20 項決策，見文末〈第二次審閱決策紀錄〉
- 再次確認後，拆成 `docs/architecture.md`（總覽）+ `docs/01-requirements.md` ~ `docs/06-operations.md`，並補上 Mermaid 圖

---

# 階段 1：需求分析（Requirements）

## 已確定的決策
| 項目 | 決定 | 理由 |
|---|---|---|
| 價格來源 | **只用 API，不寫爬蟲**：Travelpayouts（免費、快取資料）+ SerpApi Google Flights（250 次／月免費、即時） | Skyscanner 只開放商業合作夥伴且禁止快取；Amadeus Self-Service 已在 2026/7 關閉；自己寫爬蟲違反條款且會被封鎖。SerpApi 本身也有供應風險，用 `PriceProvider` 介面隔離 |
| 額度策略 | Travelpayouts 當雷達、SerpApi 只做確認與輪流巡檢；**嚴格限制在免費額度內**，用完就降級，不升級付費方案 | 見階段 2〈額度策略〉 |
| 航空公司 | 使用者可勾選，不勾就是全部 | SerpApi `include_airlines` 篩選；Travelpayouts 結果在程式端過濾 |
| 追蹤條件 v1 | 台灣出發、單程或來回、**固定日期** + **目標價（必填）**，幣別一律 TWD | 日期區間會讓 API 用量倍增，列為擴充；目標價不需要歷史資料，確保最基本的通知永遠有效 |
| 通知規則 | **狀態變化才通知**，不是條件成立就一直通知 | 避免價格持續低於目標價時天天被打擾，見階段 2〈觸發與去重〉 |
| 帳號 | **網站自有帳號**：Email + 密碼 + **Email 驗證**；另提供唯讀**示範帳號** | LINE 是可選的綁定項目；示範帳號讓面試官免註冊即可瀏覽；未驗證的信箱不寄價格通知，保護 SES 寄信信譽 |
| 追蹤上限 | 每人最多 **3 個**追蹤（active + 排隊中）；全站最多 **20 個** active price_query，額滿時新追蹤進入**排隊中**（暫不查價），有空位再依序啟用 | 公開註冊下保護 250 次／月的額度，見階段 2〈額度策略〉的用量估算；排隊讓晚註冊的人仍能建立追蹤 |
| 通知管道 | 站內通知中心 + Email 一律提供；有綁 LINE 就額外推播 | LINE Notify 已在 2025/3 停止服務，改用 Messaging API |
| 網域與 Email | 購買自有網域（約 US$10／年），DNS 放 Cloudflare；Email 用 SES | SES 寄給一般使用者需要驗證網域；自訂網址也讓作品集更完整 |
| 查價頻率 | 每 6 小時 | 搭配額度策略（見階段 2） |
| 交付範圍 | 分 4 個里程碑：M1 MVP 上線 → M2 LINE → M3 k8s/E2E → M4 維運強化 | 先有可展示的成果，再逐步擴充 |

## 使用者故事（v1）
| ID | 身為… | 我想要… | 以便… | 里程碑 |
|---|---|---|---|---|
| US-01 | 訪客 | 用 Email + 密碼註冊、驗證信箱、登入、登出 | 擁有自己的追蹤清單 | M1 |
| US-02 | 會員 | 新增追蹤（出發地、目的地、日期、單程／來回、艙等、目標價、航空公司） | 系統幫我盯價格 | M1 |
| US-03 | 會員 | 編輯、暫停、刪除追蹤；查看已過期的追蹤 | 管理我的行程 | M1 |
| US-04 | 會員 | 看到每個追蹤的目前最低價、典型價格區間和歷史最低價 | 判斷現在買划不划算 | M1 |
| US-05 | 會員 | 看價格歷史折線圖（含目標價線、典型價格區間） | 了解價格走勢 | M1 |
| US-06 | 會員 | 價格符合條件時收到站內通知和 Email | 不用一直盯著網頁 | M1 |
| US-07 | 會員 | 綁定或解除綁定 LINE | 在手機上即時收到通知 | M2 |
| US-08 | 已綁 LINE 的會員 | 收到附訂票連結的 LINE 訊息 | 立刻去訂票 | M2 |
| US-09 | 會員 | 分別開關 Email 和 LINE 通知 | 控制打擾程度 | M1（LINE 開關於 M2） |
| US-10 | 管理員 | 查看 API 額度用量和通知發送量 | 避免額度用完 | M1 |
| US-11 | 訪客（面試官） | 點一下就用示範帳號瀏覽完整功能 | 不用註冊、不用等查價就能看到成果 | M1 |

**v2（M4）：** 忘記密碼、用 LINE 登入（已綁定的帳號）。**擴充：** 日期區間、任意出發地、Duffel adapter。

## 驗收條件（範例）
- US-06（目標價 10,000）：
  - checker 確認價格 9,500 → 5 分鐘內產生 1 筆 alert，站內通知和 Email 各送出 1 次
  - 下次確認價格 9,300（比 9,500 只降 2%，即使是歷史新低）→ 不通知
  - 下次確認價格 8,900（比上次通知的 9,500 降 ≥5%）→ 再通知 1 次
  - 價格回升到 10,500，之後又跌到 9,800 → 視為重新跌破目標價，再通知 1 次
- US-07：綁定時 `state` 遭竄改 → 拒絕綁定；一個 LINE 帳號只能綁一個會員；使用者封鎖官方帳號 → 停止 LINE 推播並產生一則系統通知
- US-01：未驗證信箱的帳號可以登入和瀏覽，但新增追蹤回 403，也不會收到價格通知 Email
- US-02：已有 3 個追蹤（active + 排隊中）時再新增 → 拒絕並提示；全站 active price_query 已達 20 個且新追蹤需要建立新 query → 追蹤建立成功但狀態為「排隊中，暫不查價」；有空位後由每日排程依建立時間依序啟用，並發一則系統通知
- US-11：示範帳號除了登出和 refresh token 以外，所有寫入操作回 403；示範帳號的追蹤不會被 checker 查價、不消耗任何 API 額度

## 非功能需求
| 類別 | 需求 |
|---|---|
| 成本 | 網域約 US$10／年；AWS 每月約 US$0（免費方案結束後 ECR、S3、SES 每月幾分錢）；所有外部 API 用免費方案 |
| 額度 | SerpApi ≤ 250 次／月（硬上限）；LINE ≤ 200 則／月 |
| 效能 | API p95 < 500ms（Lambda、Neon 冷啟動除外）；從確認降價到發出通知 < 5 分鐘 |
| 可靠性 | 通知不漏發（SQS 重試 + DLQ）、不重發（冪等鍵） |
| 安全 | Argon2 密碼雜湊、HttpOnly Cookie、LINE webhook 簽章驗證、CloudFront 來源驗證標頭、機密資料不進 Git、使用者之間資料隔離 |
| 可維護性 | 單人可維護；全部 AWS 與 Cloudflare 資源用 Terraform 管理 |
| 規模 | 初期 < 50 人、≤ 20 個不同查詢組合（由階段 1 的追蹤上限強制） |

---

# 階段 2：系統設計（Design）

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
```
使用者 ──► Cloudflare DNS（自有網域）──► CloudFront（ACM 憑證）──► S3（React 靜態檔）
                                              │ /api/*、/line/webhook
                                              │ 轉發時加上 X-Origin-Verify 密鑰標頭
                                              ▼
                       Lambda Function URL（auth NONE）──► Lambda: api（FastAPI + Mangum，含 LINE webhook 路由）
                                                          └ middleware 檢查 X-Origin-Verify，不符回 403

EventBridge Scheduler（每 6 小時）──► Lambda: price-checker
     1. 取出需要查價的 price_queries（有啟用中的 watch、非示範資料、出發日 > 今天 + 2 天）
     2. Travelpayouts 查價（雷達）→ 寫入 price_snapshots（provider = travelpayouts）
     3. 雷達顯示可能觸發的候選 + 本輪輪到巡檢的 query → 在額度預算內呼叫 SerpApi
        → 寫入 price_snapshots（provider = serpapi）並更新 price_baselines
     4. 用 SerpApi 確認的價格套用觸發規則 → 狀態變化才寫入 alerts，送到 SQS
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
- **Travelpayouts = 雷達**：每 6 小時查所有 query，免費且沒有嚴格額度，只用來找出「可能降價」的候選。
- **SerpApi = 確認 + 巡檢**，每月 250 次為硬上限：
  - **確認**：雷達價格可能觸發條件時，才用 SerpApi 查即時價格。每個 query 每天最多確認 1 次，避免 Travelpayouts 過期資料重複浪費額度。
    - 「可能觸發」的定義：雷達價格 ≤ 目標價 × 1.05、低於典型區間下緣，或低於歷史最低價；已經通知過的 watch 則要 ≤ `last_notified_price` × 0.95。
  - **輪流巡檢**：Travelpayouts 可能沒有冷門航線或日期的資料，所以剩餘額度平均分配給各 query，輪流用 SerpApi 直接查價，確保每個追蹤每隔幾天至少有一筆真實價格。
  - **動態預算**：每次執行時計算 `本月剩餘額度 ÷ 本月剩餘天數 = 今日預算`，先預留確認用量，剩下的分給巡檢（最久沒查的 query 優先）。
- **用完就降級**：SerpApi 額度歸零 → 只用 Travelpayouts，通知標註「價格為參考值」，並發一則系統通知；下個月 1 號恢復。
- **用量估算**：250 次／月約等於每天 8 次；來回票一次查價要 2～3 次呼叫，所以 20 個來回查詢時，每個查詢大約 5～7 天才巡檢到一次。這是全站上限訂在 20 個 active price_query 的原因。
- 相同條件的追蹤合併成同一個 price_query，額度只花一次。
- 用量記錄在 `api_usage`；供應商用 `PriceProvider` 介面（adapter pattern）抽象化。
- 一次完整的 SerpApi 結果可能需要 2～3 次呼叫（來回票的 `departure_token`、訂票連結的 `booking_token`），預算計算時以實際呼叫次數為準。

### 價格基準
比較的一律是**同一個 price_query（同一個出發日期）**的價格，不跨日期平均。

| 用途 | 資料來源 |
|---|---|
| 「便宜」的判斷 | SerpApi `price_insights.typical_price_range` 的下緣（Google 的典型價格區間），每次呼叫 SerpApi 時更新 |
| 歷史最低價 | 冷啟動用 `price_insights.price_history` 的最低值當起點，之後用自己累積的 **SerpApi 價格**持續更新 |

- **Travelpayouts 的價格只當雷達，不納入基準計算**，避免快取價和即時價混在一起造成偏差。
- Google 沒有提供 `price_insights` 時（冷門航線、出發日很遠）：只用目標價觸發；「歷史新低」要等累積到至少 3 筆 SerpApi 價格才開始判斷；頁面顯示「歷史資料累積中」。

### 觸發與去重（狀態變化才通知）
只有 **SerpApi 確認過的價格**才能觸發通知。觸發原因有三種：

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

### 追蹤的生命週期
| 狀態 | 說明 |
|---|---|
| `active` | 正常查價 |
| `queued` | 排隊中：全站 active price_query 已滿 20 個，暫不查價；有空位時由每日排程依建立時間轉為 `active` |
| `paused` | 使用者暫停，不查價 |
| `expired` | 出發日已過，由每日排程自動標記；前端收到「歷史紀錄」分頁，價格圖保留 |

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

## 資料模型（ERD 會在文件中用 Mermaid 繪製）
- `users`(id, public_id, email UQ, password_hash, display_name, role, is_demo, is_active, failed_login_count, locked_until, email_verified_at NULL, timestamps)
- `refresh_tokens`(id, user_id, token_hash, expires_at, revoked_at)
- `email_verifications`(id, user_id, token_hash, expires_at, used_at)
- `line_accounts`(user_id PK/FK, line_user_id UQ, display_name, is_friend, linked_at)
- `notification_settings`(user_id, email_enabled, line_enabled)
- `airports`(iata PK, name_zh, city, country)、`airlines`(iata PK, name_zh)
- `price_queries`(id, query_hash UQ, origin, destination, depart_date, return_date, cabin, adults, airlines_key, is_demo, last_checked_at, last_serpapi_at, next_check_at)：`adults` 和 `is_demo` 都納入 `query_hash`，人數不同的追蹤不會合併，示範資料也不會和真實查詢共用同一筆
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

**追蹤詳情的價格圖：** SerpApi 價格畫成主線，Travelpayouts 畫成淡色參考點，加上目標價線和典型價格區間色帶；下方列出最近通知和訂票連結。

## 設計文件附圖（Mermaid）
系統架構圖、ERD、時序圖（① 註冊 → 綁 LINE ② 查價 → 確認 → 觸發 → 通知）、通知狀態機（watch_alert_states）、追蹤生命週期

---

# 階段 3：開發實作（Development）

## 專案結構（monorepo）
```
Project_TicketTrack/
├─ backend/app/
│  ├─ core/  db/
│  ├─ modules/{auth,users,watches,prices,providers,alerts,notifications,email,line,admin}/   # 每個模組：router / schemas / models / service
│  ├─ handlers/{api.py,checker.py,notifier.py}                                              # Lambda 進入點
│  └─ alembic/  seeds/（示範帳號資料）  tests/  Dockerfile
├─ frontend/  src/{pages,components,api,hooks}  Dockerfile
├─ deploy/  docker-compose.yml（api + postgres + frontend + MailHog + LocalStack）  helm/farewatch/
├─ infra/terraform/  （ECR、Lambda + Function URL、EventBridge、SQS、S3、CloudFront、ACM、SES、SSM、IAM、CloudWatch、Budgets、Cloudflare DNS）
├─ .github/  workflows/  pull_request_template.md
└─ docs/
```

## 開發規範
- **分支策略：** GitHub Flow。`main` 隨時可部署；功能分支 `feat/*`、`fix/*` → PR → CI 全綠才能 merge（設定 branch protection）
- **Commit 格式：** Conventional Commits（`feat:`、`fix:`、`docs:`…），方便自動產生 CHANGELOG
- **程式碼品質：** 後端 ruff + mypy，前端 eslint + prettier；pre-commit hook 在本機先檢查
- **設定管理：** 12-Factor，所有設定走環境變數；`.env.example` 進 Git，`.env` 不進 Git
- **追蹤進度：** GitHub Issues + Projects 看板，每個使用者故事一張卡，依里程碑分組

## 實作順序（依里程碑）

**M0：前置驗證**
- 小實驗：拿 3～5 條目標航線實際呼叫 Travelpayouts，確認資料覆蓋率和新鮮度，以及價格是否區分艙等和人數。若覆蓋率太差，回頭重新檢討額度策略；若不區分艙等和人數，v1 改為限定經濟艙、單人，或讓其他追蹤只靠巡檢
- 購買網域、Cloudflare 設定 DNS、申請 SES 正式使用權限（審核需要時間，提早送出）

**M1：MVP 上線**
1. 骨架 + docker-compose + CI（ci.yml）
2. 帳號系統（含 Email 驗證）+ 示範帳號（US-01、US-11）
3. 機場／航空公司資料 + 追蹤 CRUD + 生命週期（US-02、US-03）
4. PriceProvider：mock → Travelpayouts → SerpApi；checker、查詢合併、額度預算與輪流巡檢（US-10）
5. 價格基準 + 觸發規則 + alerts + notifications + notifier（站內、Email）（US-04、US-06、US-09）
6. 前端頁面 + 價格歷史圖（US-05）
7. Terraform（AWS + Cloudflare）+ deploy pipeline + 基本告警 → **正式上線**

**M2：LINE**
8. LINE 綁定 + Messaging API + webhook（本機用 Cloudflare Tunnel）（US-07、US-08）

**M3：k8s 與 E2E**
9. Helm chart + kind 冒煙測試 + Playwright E2E 進 CI（階段 4、5）

**M4：維運強化**
10. 完整監控告警、v2 帳號功能、Dependabot、安全掃描、README

---

# 階段 4：測試（Testing）

## 測試金字塔
| 層級 | 工具 | 範圍 | 目標 |
|---|---|---|---|
| 單元測試 | pytest、Vitest | 價格基準、觸發規則與狀態轉換、額度預算計算、查詢合併、JWT、元件 | 核心邏輯（prices、alerts）覆蓋率 ≥ 90%，整體 ≥ 70% |
| 整合測試 | pytest + 真實 Postgres（CI service container）、httpx mock 外部 API | API 端點、DB 交易、Alembic migration、LINE 簽章驗證、來源驗證標頭 | 每個端點都有正常、錯誤和權限案例 |
| 契約測試 | 錄製的 Travelpayouts／SerpApi 回應（fixtures，含有／沒有 `price_insights` 兩種） | adapter 能正確解析真實格式 | 供應商改格式時能及早發現 |
| E2E 測試 | **Playwright**（M3） | 註冊 → 建立追蹤 → mock 降價 → 通知中心出現通知；示範帳號瀏覽 | 核心流程 3–5 條 |
| k8s 冒煙測試 | kind + Helm（M3） | 部署後 API 健康檢查 + checker 跑一次 | 每個 PR |

## 必測案例
- 安全：token 過期／撤銷、帳號鎖定、使用者 A 讀不到 B 的追蹤、非 admin 打 admin API 回 403、示範帳號寫入回 403、綁定 `state` 遭竄改時拒絕、webhook 簽章錯誤回 401、缺少或錯誤的 `X-Origin-Verify` 回 403、未驗證信箱不能新增追蹤也不會收到 Email、驗證連結過期或重複使用時拒絕
- 觸發規則：三種觸發原因、新追蹤第一次確認就低於目標價會通知 1 次、連續小幅創新低不重複通知、同一筆價格符合多個原因只產生一則 alert、跌破目標價只通知 1 次、再降 ≥5% 才再通知、回升後再跌破會重新通知、只有 SerpApi 價格能觸發、樣本不足時不判斷歷史新低、沒有 `price_insights` 時只用目標價
- 額度：每日預算計算、確認優先於巡檢、額度歸零時降級並發系統通知、每個 query 每天最多確認 1 次、超過每人 3 個追蹤時拒絕新增、全站滿 20 個 query 時新追蹤進入排隊且不被查價、對應到既有 query 的新追蹤不必排隊、雷達價格未達「可能觸發」門檻時不呼叫 SerpApi、人數不同的追蹤不合併成同一個 query
- 生命週期：出發前 2 天停止查價、出發後自動 expired、編輯追蹤後重新對應 price_query 並重置通知狀態、有空位時依建立時間啟用排隊中的追蹤、示範資料不被查價
- 可靠性：SQS 重送不重複發送
- 外部 API 一律 mock，CI 不消耗真實額度

---

# 階段 5：部署（Deployment）

## 環境
| 環境 | 內容 |
|---|---|
| local | docker-compose（Postgres、MailHog、LocalStack SQS、mock provider） |
| k8s-demo | kind + Helm（本機和 CI，M3） |
| prod | AWS Serverless + Neon + Cloudflare DNS |

（單人專案不另外建 staging；Neon 免費版可以開 branch，給 migration 預演用）

## 一次性手動設定（寫進部署文件）
- 購買網域，將 DNS 交給 Cloudflare 管理
- 申請 SES 正式使用權限（說明用途、退信與投訴處理方式）
- 建立 LINE Provider，並在其下建立 Login channel 和 Messaging API channel
- 建立 Terraform state 用的 S3 bucket（避免雞生蛋問題，不由 Terraform 自己建立）

## CI/CD
- `ci.yml`（PR）：lint + 型別檢查 + 單元／整合測試 + 前端 build + docker build + `terraform fmt/validate/plan`
- `k8s-e2e.yml`（PR，M3）：建 amd64 image 並 `kind load`（不推 ECR）→ `helm install` → 冒煙測試 + Playwright E2E
- `deploy.yml`（merge 到 main）：`buildx` 建 arm64 單一架構 image（`--provenance=false`）推上 ECR（tag = git SHA）→ 在 Neon branch 預演 migration → `alembic upgrade head` → `terraform apply` 更新 Lambda → 前端 `s3 sync` + CloudFront invalidation → 部署後冒煙測試
- AWS 認證用 GitHub OIDC（不存長期金鑰）；Cloudflare API token 存在 GitHub Secrets（權限只限該網域的 DNS）

## 回滾策略
- 程式：Lambda 改回上一個 image tag（ECR 保留 3 個版本）→ `terraform apply -var image_tag=<上一版>`
- 資料庫：migration 一律向後相容（先加欄位、再改程式、最後才刪欄位）；資料救援以每週 `pg_dump` 備份為主，Neon 免費版的 point-in-time restore 視窗很短（實作時確認當時的額度），只能救剛發生的誤操作
- 前端：S3 開啟版本控制，可以還原上一版

## 成本控管
- **網域**：約 US$10／年（唯一固定支出）
- **AWS 免費方案期間**（新帳號最多 6 個月）：費用由抵用金支付，信用卡不會被扣款。**到期或抵用金用完之前必須升級成付費方案，否則帳號會被關閉**
- **之後**：ECR、S3、SES 每月幾分錢，其他都在永久免費額度內

| 會產生費用的項目 | 怎麼避免 |
|---|---|
| API Gateway（免費額度只有 12 個月） | 改用 Lambda Function URL |
| Route 53 hosted zone（每月 US$0.50） | DNS 放 Cloudflare |
| ECR 儲存費 | lifecycle 規則只保留 3 個 image |
| Secrets Manager | 改用 SSM Parameter Store 標準版 |
| CloudWatch Logs 超過 5GB | log 只保留 7–14 天 |
| NAT Gateway | Lambda 不放進 VPC |
| KMS 自訂金鑰 | 使用 AWS 管理的金鑰 |
| SerpApi 超量 | 硬上限 250 次，用完降級，不升級付費 |
| 忘記關掉的資源 | AWS Budgets US$1 告警 + 全部用 Terraform 管理 |
| 免費方案到期，帳號被關閉 | 到期前升級成付費方案（設行事曆提醒），升級後靠 Budgets US$1 告警把關 |

---

# 階段 6：維運（Operations / Maintenance）

## 監控與告警（CloudWatch + SNS Email）
| 指標 | 告警條件 |
|---|---|
| Lambda 錯誤率 | 5 分鐘內錯誤 > 5 次 |
| checker 是否有在跑 | 超過 7 小時沒有成功執行 |
| DLQ 訊息數 | > 0 |
| SerpApi／LINE 額度 | 用量 > 80% |
| SES 退信率／投訴率 | 退信 > 5% 或投訴 > 0.1%（超過 AWS 門檻帳號會被暫停寄信） |
| AWS 費用 | > US$1 |
- 結構化日誌（JSON，帶 request_id、watch_id），用 CloudWatch Logs Insights 查詢
- `/health` 健康檢查端點；Admin 頁面顯示額度、巡檢覆蓋率（每個 query 距離上次 SerpApi 查價幾天）和通知成功率

## 事件處理手冊（`docs/06-operations.md` 中的 runbook）
| 狀況 | 處理方式 |
|---|---|
| SerpApi 額度用完 | 自動降級成只用 Travelpayouts，通知標註「價格為參考值」，發系統通知；下個月 1 號恢復 |
| SerpApi 停止服務或長期無法使用 | 走和額度用完相同的降級流程；透過 `PriceProvider` 介面換接其他供應商（例如 Duffel adapter） |
| Travelpayouts 長期沒有某航線資料 | 該 query 只靠輪流巡檢；Admin 頁面標示覆蓋率偏低 |
| LINE 推播失敗或額度用完 | 改由 Email 送達；DLQ 告警後人工檢查 |
| SES 正式權限被拒或帳號被暫停 | `EmailSender` 切換到 Gmail SMTP 備案；檢查退信／投訴原因後重新申請 |
| 註冊或重寄驗證信被濫用（SES 退信率／投訴率告警） | 先暫時關閉註冊；再補上註冊頻率限制或 Cloudflare Turnstile，並對 Lambda 設 reserved concurrency |
| 外部 API 格式改變 | 契約測試會在 CI 失敗；adapter 記錄錯誤並跳過，不影響其他供應商 |
| 部署後出錯 | 依階段 5 回滾 |
| Neon 資料異常 | 剛發生的用 point-in-time restore；其餘從每週的 `pg_dump` 備份（存 S3，保留 4 份）還原 |

## 維護
- **相依套件更新：** Dependabot 每週發 PR，CI 全綠才 merge
- **安全掃描：** CI 加上 `pip-audit`、`npm audit`、Trivy 掃描 image
- **版本發布：** 用 Git tag（語意化版本）+ CHANGELOG（從 Conventional Commits 產生）
- **資料保留：** `price_snapshots` 保留 2 年，超過的由每日排程彙總成每日最低價後刪除，控制在 Neon 0.5GB 內
- **擴充路線：** 日期區間、ArgoCD、Prometheus/Grafana、Duffel adapter、v2 帳號功能

---

## 審閱決策紀錄（2026-10-09）
| # | 問題 | 決定 |
|---|---|---|
| 1 | SerpApi 每日校準會超過 250 次／月 | 取消每日校準；SerpApi 只做確認 + 輪流巡檢，動態分配每日預算，嚴格限制在免費額度內 |
| 2 | 24 小時去重會讓使用者每天被通知；「低於平均」太常成立 | 狀態變化才通知；「便宜」改用 Google 典型價格區間下緣 |
| 3 | watch 和 price_query 沒有關聯 | `watches.price_query_id` FK；編輯時依 `query_hash` 重新對應 |
| 4 | 基準跨日期平均、混用不同供應商的價格 | 只比較同一個 price_query；基準來自 `price_insights` + 自己的 SerpApi 價格；Travelpayouts 只當雷達；目標價必填；累積 3 筆才判斷歷史新低 |
| 5 | SES 沙盒限制與預算 US$0 衝突 | 購買網域（約 US$10／年）+ SES；DNS 用 Cloudflare；Gmail SMTP 當備案 |
| 6 | Travelpayouts 對特定航線的覆蓋率未知 | M0 先做小實驗確認 |
| 7 | CloudFront OAC 會擋下 LINE webhook 的 POST | Function URL 公開 + CloudFront 加 `X-Origin-Verify` 密鑰標頭，由 middleware 驗證 |
| 8 | 同一個 image 跑 Lambda、本機、k8s | Lambda 基底 image；本機與 k8s 覆寫為 uvicorn；`buildx` 建 arm64 + amd64 |
| 9 | 出發日已過的追蹤仍會被查價 | 出發前 2 天停止查價；出發後自動 expired，前端收到歷史紀錄分頁 |
| 10 | LINE userId 不一致風險 | Login 與 Messaging API channel 建在同一個 Provider |
| 11 | 站內通知中心無法放系統訊息 | 拆成 `alerts`（業務紀錄）與 `notifications`（通知中心，支援 system 類型） |
| 12 | 單人開發範圍過大、上線太晚 | 分 M0～M4 里程碑，M1 即上線；新增唯讀示範帳號 |

## 第二次審閱決策紀錄（2026-10-10）
| # | 問題 | 決定 |
|---|---|---|
| 1 | Lambda 不接受 multi-arch image（修正上表第 8 項） | 改建單一架構 image：arm64 推 ECR 給 Lambda，amd64 只在本機和 CI 給 kind 用；build 加 `--provenance=false` |
| 2 | `record_low` 和 US-06 驗收條件矛盾 | 有狀態變化就通知；沒有狀態變化時三種原因共用「比上次通知再降 ≥5%」門檻；一筆價格只產生一則 alert |
| 3 | 新追蹤的初始狀態沒有定義 | 初始視為「高於」，第一次確認就符合條件會通知 1 次 |
| 4 | `query_hash` 沒有包含人數 | `price_queries` 加 `adults` 並納入 hash |
| 5 | 示範資料可能和真實查詢共用同一筆 price_query | `is_demo` 納入 hash |
| 6 | 公開註冊但 Email 驗證排在 M4，會傷害 SES 寄信信譽 | Email 驗證移到 M1；未驗證不能新增追蹤、不寄價格通知 |
| 7 | 沒有追蹤數上限，額度會被稀釋 | 每人 3 個追蹤、全站 20 個 active price_query；全站額滿時新追蹤排隊，暫不查價 |
| 8 | AWS 免費方案到期後帳號會被關閉；SES 不是永久免費 | 到期前升級成付費方案；成本說明補上 SES |
| 9 | Neon 免費版 point-in-time restore 視窗很短 | 資料救援以每週 `pg_dump` 為主 |
| 10 | SerpApi 本身有供應風險 | runbook 新增「SerpApi 停止服務」，靠 `PriceProvider` 介面換接 |
| 11 | 示範帳號「所有寫入回 403」會擋到登出 | 登出和 refresh 例外 |
| 12 | 彙總後的每日最低價沒有資料表；snapshot 刪除後 `alerts` 的 FK 失效 | 新增 `price_daily_lows`；`alerts.snapshot_id` 改為可 NULL |
| 13 | Context 開頭在講已作廢的舊文件；產品與 repo 名稱不一致 | 改成說明產品名稱 FareWatch 與 repo 名稱的對應 |
| 14 | 編輯追蹤後通知狀態沒有處理 | 編輯查價條件或目標價後重置 `watch_alert_states` |
| 15 | 「雷達顯示可能觸發」沒有定義 | 雷達價格 ≤ 目標價 × 1.05、低於典型區間下緣或歷史最低價；已通知過的要 ≤ 上次通知價 × 0.95 |
| 16 | Travelpayouts 可能不區分艙等和人數 | 併入 M0 小實驗確認，再決定是否限定經濟艙、單人 |
| 17 | refresh token cookie 沒有 CSRF 防護 | 加上 `Secure` 和 `SameSite=Strict` |
| 18 | 幣別沒有定義 | v1 一律 TWD |
| 19 | 公開端點沒有頻率限制，驗證信可能被濫發 | v1 不做，有需要再補；靠 SES 退信率／投訴率告警發現，處理方式寫進 runbook |
| 20 | 忘記密碼是否提前到 M1 | 維持 M4 |

---

## 驗證方式（文件階段）
- 確認拆分後的 7 份文件涵蓋上述 6 個階段，Mermaid 圖在 GitHub 上能正常顯示，並 commit
- 之後實作時，以階段 1 的驗收條件和階段 4 的測試策略作為完成標準
