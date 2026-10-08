# FareWatch 最低價機票即時通知網站 — 架構規劃（依 SDLC 6 階段）

## Context
舊的 `docs/architecture.md`（JobTrack 求職網站）作廢，改做新專案：
使用者註冊帳號 → 設定航線／日期／目標價／航空公司 → 系統每 6 小時查價、累積價格歷史 → 價格**低於目標價、低於歷史平均，或創下歷史新低**時，發送站內通知 + Email；**有綁定 LINE 的使用者額外收到 LINE 推播**，訊息附訂票連結。
定位是**單人維護的展示型作品集**，**預算約 US$0**，同時涵蓋 前端／後端／API／Docker／CI/CD／k8s／AWS／DevOps，並依**軟體開發生命週期（SDLC）6 階段**組織。
本階段**不寫程式碼**，只產出架構文件。

## 文件狀態
- 目前為**待審閱草稿**，6 個階段都放在這份文件裡
- 審閱確認後，拆成 `docs/architecture.md`（總覽）+ `docs/01-requirements.md` ~ `docs/06-operations.md`，並補上 Mermaid 圖

---

# 階段 1：需求分析（Requirements）

## 已確定的決策
| 項目 | 決定 | 理由 |
|---|---|---|
| 價格來源 | **只用 API，不寫爬蟲**：Travelpayouts（免費、快取資料）+ SerpApi Google Flights（250 次／月免費、即時） | Skyscanner 只開放商業合作夥伴且禁止快取；Amadeus Self-Service 已在 2026/7 關閉；爬蟲違反條款且會被封鎖 |
| 航空公司 | 使用者可勾選，不勾就是全部 | SerpApi `include_airlines` 篩選；Travelpayouts 結果在程式端過濾 |
| 追蹤條件 v1 | 台灣出發、單程或來回、**固定日期** + 目標價 | 日期區間會讓 API 用量倍增，列為擴充 |
| 帳號 | **網站自有帳號**：Email + 密碼 | LINE 是可選的綁定項目 |
| 通知管道 | 站內通知中心 + Email 一律提供；有綁 LINE 就額外推播 | LINE Notify 已在 2025/3 停止服務，改用 Messaging API |
| 查價頻率 | 每 6 小時 | 搭配額度策略（見階段 2） |

## 使用者故事（v1）
| ID | 身為… | 我想要… | 以便… |
|---|---|---|---|
| US-01 | 訪客 | 用 Email + 密碼註冊、登入、登出 | 擁有自己的追蹤清單 |
| US-02 | 會員 | 新增追蹤（出發地、目的地、日期、單程／來回、艙等、目標價、航空公司） | 系統幫我盯價格 |
| US-03 | 會員 | 編輯、暫停、刪除追蹤 | 管理我的行程 |
| US-04 | 會員 | 看到每個追蹤的目前最低價和歷史平均價 | 判斷現在買划不划算 |
| US-05 | 會員 | 看價格歷史折線圖（含平均線、目標價線） | 了解價格走勢 |
| US-06 | 會員 | 價格符合條件時收到站內通知和 Email | 不用一直盯著網頁 |
| US-07 | 會員 | 綁定或解除綁定 LINE | 在手機上即時收到通知 |
| US-08 | 已綁 LINE 的會員 | 收到附訂票連結的 LINE 訊息 | 立刻去訂票 |
| US-09 | 會員 | 分別開關 Email 和 LINE 通知 | 控制打擾程度 |
| US-10 | 管理員 | 查看 API 額度用量和通知發送量 | 避免額度用完 |

**v2：** Email 驗證、忘記密碼、用 LINE 登入（已綁定的帳號）。**擴充：** 日期區間、任意出發地、Duffel adapter。

## 驗收條件（範例）
- US-06：給定追蹤目標價 10,000，checker 查到 9,500 → 5 分鐘內產生 1 筆 alert，站內通知和 Email 各送出 1 次；同一追蹤 24 小時內不會重複通知，除非價格再降 ≥5%
- US-07：綁定時 `state` 遭竄改 → 拒絕綁定；一個 LINE 帳號只能綁一個會員；使用者封鎖官方帳號 → 停止 LINE 推播

## 非功能需求
| 類別 | 需求 |
|---|---|
| 成本 | AWS 每月約 US$0（ECR 免費期結束後每月幾分錢）；所有外部 API 用免費方案 |
| 額度 | SerpApi ≤ 250 次／月；LINE ≤ 200 則／月 |
| 效能 | API p95 < 500ms（Lambda 冷啟動除外）；從偵測到降價到發出通知 < 5 分鐘 |
| 可靠性 | 通知不漏發（SQS 重試 + DLQ）、不重發（冪等鍵） |
| 安全 | Argon2 密碼雜湊、HttpOnly Cookie、LINE webhook 簽章驗證、機密資料不進 Git、使用者之間資料隔離 |
| 可維護性 | 單人可維護；全部 AWS 資源用 Terraform 管理 |
| 規模 | 初期 < 50 人、< 20 個不同查詢組合 |

---

# 階段 2：系統設計（Design）

## 技術選型
| 層 | 選擇 | 理由 |
|---|---|---|
| 前端 | React + TypeScript + Vite、TanStack Query、Recharts、Tailwind | 主流、型別安全、能純靜態部署到 S3；Recharts 用來畫價格圖 |
| 後端 | FastAPI + Mangum、SQLAlchemy 2.0 + Alembic、Pydantic、httpx | 非同步呼叫外部 API；Mangum 讓同一份程式在 Lambda 上執行；Alembic 讓本機 DB 和 Neon 結構一致 |
| DB | PostgreSQL 16：本機用 Docker，正式環境用 **Neon 免費版** | 只換連線字串 |
| 背景任務 | EventBridge Scheduler + SQS | 取代 Celery/Redis，AWS 代管且免費 |
| 容器 | 單一 backend image（AWS Lambda Python arm64 基底）推到 **ECR**；frontend 用 Nginx image（只給 k8s 用） | 本機、k8s、Lambda 都跑同一個 image |
| k8s | **本機 kind + CI 驗證**，用 Helm chart 部署 | 單人維護正式環境的 k8s 成本高；用來學習和展示 |
| IaC | Terraform（state 存 S3） | 一鍵建立／刪除所有 AWS 資源 |

## 系統架構（正式環境）
```
使用者 ──► CloudFront ──► S3（React 靜態檔）
             │ /api/*、/line/webhook
             ▼
        Lambda Function URL ──► Lambda: api（FastAPI + Mangum，含 LINE webhook 路由）

EventBridge Scheduler（每 6 小時）──► Lambda: price-checker
     1. 把啟用中的追蹤依（航線, 日期, 艙等, 航空公司組合）合併成 price_queries
     2. Travelpayouts 查價 → 寫入 price_snapshots
     3. 可能觸發通知的候選 → SerpApi 確認即時價格 + price_insights → 寫入快照
     4. 確認後仍符合條件 → 寫入 alerts，送到 SQS
SQS ──► Lambda: notifier ──► 站內通知（DB）+ Email（SES）+ LINE Messaging API（有綁定才發）
        （每個管道各自記錄狀態；失敗由 SQS 重試，最後進 DLQ）

所有 Lambda ──► Neon PostgreSQL（新加坡區），Lambda 不放進 VPC，用 TLS 連線
機密資料 ──► SSM Parameter Store 標準版
CloudWatch：錯誤、DLQ 堆積、額度 → SNS 寄 Email 告警
```

## 核心邏輯設計
**額度策略：** Travelpayouts 每 6 小時當「便宜的雷達」→ 只在可能觸發通知時才用 SerpApi 確認，另外每個 query 每天校準 1 次 → 相同 query 合併 → `api_usage` 用量超過 80% 自動降頻。供應商用 `PriceProvider` 介面（adapter pattern）抽象化。

**歷史基準：** ① 冷啟動用 SerpApi `price_insights`（typical_price_range、price_history）② 自己累積的快照逐步滾動成 2 年 ③ `baseline = 近 730 天同航線、同出發月份的平均值／最低值`，樣本數不足時用 ①。
**觸發條件（任一成立）：** `price ≤ 目標價`、`price < 歷史平均`、`price < 歷史最低`。

**通知去重：** 同一個追蹤 24 小時內最多通知 1 次，價格再降 ≥5% 才例外；`alerts` 唯一鍵 + `alert_deliveries` UQ(alert_id, channel) 確保冪等；收到 unfollow 事件 → 停止 LINE 推播。

## 帳號與驗證設計
- v1：註冊、登入、Argon2、JWT access token（15 分鐘）+ refresh token（7 天，HttpOnly Cookie，存 DB，可撤銷）、登出、連續失敗鎖定
- LINE 綁定：`GET /me/line/link` → LINE 授權頁（`bot_prompt=aggressive` 引導加好友）→ callback 驗證 `state`（使用者 + 一次性 nonce）→ 寫入 `line_accounts`
- v2：Email 驗證、忘記密碼、LINE 登入（共用同一個 callback，用 `state` 區分）
- 權限：資料一律檢查 owner；`admin` 只能看用量和統計

## 資料模型（ERD 會在文件中用 Mermaid 繪製）
- `users`(id, public_id, email UQ, password_hash, display_name, role, is_active, failed_login_count, locked_until, email_verified_at NULL, timestamps)
- `refresh_tokens`(id, user_id, token_hash, expires_at, revoked_at)
- `line_accounts`(user_id PK/FK, line_user_id UQ, display_name, is_friend, linked_at)
- `notification_settings`(user_id, email_enabled, line_enabled)
- `airports`(iata PK, name_zh, city, country)、`airlines`(iata PK, name_zh)
- `watches`(id, public_id, user_id, origin, destination, depart_date, return_date NULL, trip_type, cabin, adults, target_price NULL, currency, is_active, timestamps)、`watch_airlines`(watch_id, airline_iata)
- `price_queries`(id, query_hash UQ, origin, destination, depart_date, return_date, cabin, airlines_key, last_checked_at, next_check_at)
- `price_snapshots`(id, price_query_id, provider, price, currency, airline_iata, stops, booking_url, observed_at)：只新增不修改
- `price_baselines`(price_query_id, avg_price, min_price, sample_count, source, computed_at)
- `alerts`(id, watch_id, snapshot_id, reason, price, is_read, created_at, UQ 去重鍵)：同時當作站內通知中心
- `alert_deliveries`(alert_id, channel, status, attempts, sent_at)，UQ(alert_id, channel)
- `api_usage`(provider, month, count)

## API 草案（/api/v1，FastAPI 自動產生 OpenAPI 文件）
- Auth：`POST /auth/register|login|refresh|logout`、`GET /me`
- LINE：`GET /me/line/link`、`GET /auth/line/callback`、`GET/DELETE /me/line`、`POST /line/webhook`
- Watches：`GET/POST /watches`、`GET/PATCH/DELETE /watches/{id}`、`GET /watches/{id}/prices?range=`、`GET /watches/{id}/baseline`
- 通知：`GET /alerts`、`PATCH /alerts/{id}/read`、`GET/PATCH /me/notification-settings`
- 參考資料：`GET /airports?q=`、`GET /airlines`；Admin：`GET /admin/usage`

## 前端頁面
註冊／登入 → 我的追蹤列表 → 新增／編輯追蹤 → 追蹤詳情（價格歷史圖、最近通知、訂票連結）→ 通知中心（鈴鐺 + 未讀數）→ 設定（個人資料、LINE 綁定與 QR code、通知開關）

## 設計文件附圖（Mermaid）
系統架構圖、ERD、時序圖（① 註冊 → 綁 LINE ② 查價 → 觸發 → 通知）、通知狀態機

---

# 階段 3：開發實作（Development）

## 專案結構（monorepo）
```
Project_TicketTrack/
├─ backend/app/
│  ├─ core/  db/
│  ├─ modules/{auth,users,watches,prices,providers,alerts,line,admin}/   # 每個模組：router / schemas / models / service
│  ├─ handlers/{api.py,checker.py,notifier.py}                          # Lambda 進入點
│  └─ alembic/  tests/  Dockerfile
├─ frontend/  src/{pages,components,api,hooks}  Dockerfile
├─ deploy/  docker-compose.yml（api + postgres + frontend + MailHog + LocalStack）  helm/farewatch/
├─ infra/terraform/  （ECR、Lambda + Function URL、EventBridge、SQS、S3、CloudFront、SSM、IAM、CloudWatch、Budgets）
├─ .github/  workflows/  pull_request_template.md
└─ docs/
```

## 開發規範
- **分支策略：** GitHub Flow。`main` 隨時可部署；功能分支 `feat/*`、`fix/*` → PR → CI 全綠才能 merge（設定 branch protection）
- **Commit 格式：** Conventional Commits（`feat:`、`fix:`、`docs:`…），方便自動產生 CHANGELOG
- **程式碼品質：** 後端 ruff + mypy，前端 eslint + prettier；pre-commit hook 在本機先檢查
- **設定管理：** 12-Factor，所有設定走環境變數；`.env.example` 進 Git，`.env` 不進 Git
- **追蹤進度：** GitHub Issues + Projects 看板，每個使用者故事一張卡

## 實作順序（對應使用者故事）
1. 骨架 + docker-compose + CI（ci.yml）
2. 帳號系統（US-01）
3. 機場／航空公司資料 + 追蹤 CRUD（US-02、US-03）
4. PriceProvider：mock → Travelpayouts → SerpApi；checker、查詢合併、額度控管（US-10）
5. 基準計算 + 觸發規則 + alerts + notifier（站內、Email）（US-04、US-06、US-09）
6. LINE 綁定 + Messaging API + webhook（本機用 Cloudflare Tunnel）（US-07、US-08）
7. 前端頁面 + 價格歷史圖（US-05）
8. Helm chart + kind e2e（階段 5）
9. Terraform + deploy pipeline + 監控（階段 5、6）
10. README、v2 功能

---

# 階段 4：測試（Testing）

## 測試金字塔
| 層級 | 工具 | 範圍 | 目標 |
|---|---|---|---|
| 單元測試 | pytest、Vitest | 基準計算、觸發規則、去重、查詢合併、JWT、元件 | 核心邏輯（prices、alerts）覆蓋率 ≥ 90%，整體 ≥ 70% |
| 整合測試 | pytest + 真實 Postgres（CI service container）、httpx mock 外部 API | API 端點、DB 交易、Alembic migration、LINE 簽章驗證 | 每個端點都有正常、錯誤和權限案例 |
| 契約測試 | 錄製的 Travelpayouts／SerpApi 回應（fixtures） | adapter 能正確解析真實格式 | 供應商改格式時能及早發現 |
| E2E 測試 | **Playwright** | 註冊 → 建立追蹤 → mock 降價 → 通知中心出現通知 | 核心流程 3–5 條 |
| k8s 冒煙測試 | kind + Helm | 部署後 API 健康檢查 + checker 跑一次 | 每個 PR |

## 必測案例
- 安全：token 過期／撤銷、帳號鎖定、使用者 A 讀不到 B 的追蹤、非 admin 打 admin API 回 403、綁定 `state` 遭竄改時拒絕、webhook 簽章錯誤回 401
- 業務：三種觸發條件、24 小時去重 + 降 5% 例外、SQS 重送不重複發送、額度超過 80% 自動降頻
- 外部 API 一律 mock，CI 不消耗真實額度

---

# 階段 5：部署（Deployment）

## 環境
| 環境 | 內容 |
|---|---|
| local | docker-compose（Postgres、MailHog、LocalStack SQS、mock provider） |
| k8s-demo | kind + Helm（本機和 CI） |
| prod | AWS Serverless + Neon |

（單人專案不另外建 staging；Neon 免費版可以開 branch，給 migration 預演用）

## CI/CD
- `ci.yml`（PR）：lint + 型別檢查 + 單元／整合測試 + 前端 build + docker build + `terraform fmt/validate/plan`
- `k8s-e2e.yml`（PR）：kind → `helm install` → 冒煙測試 + Playwright E2E
- `deploy.yml`（merge 到 main）：backend image 推上 ECR（tag = git SHA）→ 在 Neon branch 預演 migration → `alembic upgrade head` → `terraform apply` 更新 Lambda → 前端 `s3 sync` + CloudFront invalidation → 部署後冒煙測試
- AWS 認證用 GitHub OIDC（不存長期金鑰）

## 回滾策略
- 程式：Lambda 改回上一個 image tag（ECR 保留 3 個版本）→ `terraform apply -var image_tag=<上一版>`
- 資料庫：migration 一律向後相容（先加欄位、再改程式、最後才刪欄位）；必要時用 Neon point-in-time restore
- 前端：S3 開啟版本控制，可以還原上一版

## 成本控管
- **免費方案期間**（新帳號最多 6 個月）：費用由抵用金支付，信用卡不會被扣款
- **之後**：除了 ECR 每月約 US$0.03，其他都在永久免費額度內

| 會產生費用的項目 | 怎麼避免 |
|---|---|
| API Gateway（免費額度只有 12 個月） | 改用 Lambda Function URL |
| ECR 儲存費 | lifecycle 規則只保留 3 個 image（約 250–350MB，低於 500MB 免費額度） |
| Secrets Manager | 改用 SSM Parameter Store 標準版 |
| CloudWatch Logs 超過 5GB | log 只保留 7–14 天 |
| NAT Gateway | Lambda 不放進 VPC |
| KMS 自訂金鑰 | 使用 AWS 管理的金鑰 |
| 忘記關掉的資源 | AWS Budgets US$1 告警 + 全部用 Terraform 管理 |

---

# 階段 6：維運（Operations / Maintenance）

## 監控與告警（CloudWatch + SNS Email）
| 指標 | 告警條件 |
|---|---|
| Lambda 錯誤率 | 5 分鐘內錯誤 > 5 次 |
| checker 是否有在跑 | 超過 7 小時沒有成功執行 |
| DLQ 訊息數 | > 0 |
| SerpApi／LINE 額度 | 用量 > 80% |
| AWS 費用 | > US$1 |
- 結構化日誌（JSON，帶 request_id、watch_id），用 CloudWatch Logs Insights 查詢
- `/health` 健康檢查端點；Admin 頁面顯示額度和通知成功率

## 事件處理手冊（`docs/06-operations.md` 中的 runbook）
| 狀況 | 處理方式 |
|---|---|
| SerpApi 額度用完 | 自動降級成只用 Travelpayouts，通知標註「價格為參考值」；下個月 1 號恢復 |
| LINE 推播失敗或額度用完 | 改由 Email 送達；DLQ 告警後人工檢查 |
| 外部 API 格式改變 | 契約測試會在 CI 失敗；adapter 記錄錯誤並跳過，不影響其他供應商 |
| 部署後出錯 | 依階段 5 回滾 |
| Neon 資料異常 | point-in-time restore；每週用 `pg_dump` 備份到 S3（保留 4 份） |

## 維護
- **相依套件更新：** Dependabot 每週發 PR，CI 全綠才 merge
- **安全掃描：** CI 加上 `pip-audit`、`npm audit`、Trivy 掃描 image
- **版本發布：** 用 Git tag（語意化版本）+ CHANGELOG（從 Conventional Commits 產生）
- **資料保留：** `price_snapshots` 保留 2 年，超過的由排程彙總成每日最低價後刪除，控制在 Neon 0.5GB 內
- **擴充路線：** 日期區間、ArgoCD、Prometheus/Grafana、Duffel adapter、v2 帳號功能

---

## 驗證方式（文件階段）
- 確認舊的 `docs/architecture.md` 已刪除，新的 7 份文件涵蓋上述 6 個階段，Mermaid 圖在 GitHub 上能正常顯示，並 commit
- 之後實作時，以階段 1 的驗收條件和階段 4 的測試策略作為完成標準
