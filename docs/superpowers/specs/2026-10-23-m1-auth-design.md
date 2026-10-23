# M1 子專案 #2：帳號系統 + 示範帳號 — 設計

日期：2026-10-23
狀態：待審閱
相關文件：[architecture.md](../../architecture.md)、[01-requirements.md](../../01-requirements.md)、[02-design.md](../../02-design.md)、[2026-10-22 backend 骨架設計](2026-10-22-m1-backend-skeleton-design.md)

## 背景與目標
M1 的第 2 個子專案，對應 US-01（註冊、登入、登出）和 US-11（示範帳號）。

**計畫變更：取消 Email 驗證。** 原本第二次審閱第 6 項把 Email 驗證放進 M1，現在改為「在網站直接註冊就能使用」。價格通知 Email 照寄（#5 實作），寄信服務用 SES 或 Gmail SMTP 到 #5 再選。代價是任何人可以用別人的信箱註冊，價格通知會寄到那個信箱；使用者只有本人和極少數人、每人最多 3 個追蹤，這個風險可以接受。#2 本身完全不寄信。

**完成標準：**
- 下方〈測試〉列出的案例全部通過，涵蓋 US-01、US-11 的驗收條件
- 本機 `docker compose up` 後，可以用 API 註冊、登入、refresh、登出，以及用 `POST /auth/demo` 進入示範帳號
- PR 上的 CI 全綠

## 不在範圍內
Email 驗證與任何寄信功能、忘記密碼（M4）、`notification_settings`（#5）、示範帳號的追蹤／價格／通知資料（#3～#5 各自補進 seed）、admin 設定腳本與 `require_admin`（#4）、過期 refresh token 的定期清理（#4 的每日維護）、端點頻率限制（照第二次審閱第 19 項，v1 不做）。

## 技術決定
| 項目 | 決定 | 理由 |
|---|---|---|
| 做法 | 自己組裝，不用 fastapi-users 等框架 | 照 02-design 的設計實作，refresh 輪換、示範帳號、失敗鎖定都不用繞著框架改；每一步都能說明原理 |
| 密碼雜湊 | `pwdlib[argon2]` | 02-design 指定 Argon2；pwdlib 是 FastAPI 官方文件目前推薦的套件 |
| JWT | `PyJWT`，HS256 | 單一服務自己簽、自己驗，不需要非對稱金鑰 |
| Email 格式檢查 | Pydantic `EmailStr`（需要 `email-validator`） | 內建支援 |

## 資料表
| 表 | 欄位 | 說明 |
|---|---|---|
| `users` | id、public_id（UUID，唯一）、email（唯一，存小寫）、password_hash、display_name（NULL）、role（`user`／`admin`，預設 `user`）、is_demo（預設 false）、is_active（預設 true）、failed_login_count（預設 0）、locked_until（NULL）、created_at、updated_at | 對外（API、前端網址）一律用 `public_id`，不露出流水號 id |
| `refresh_tokens` | id、user_id（FK，`ON DELETE CASCADE`）、token_hash（唯一）、expires_at、revoked_at（NULL）、created_at | DB 只存 token 原文的 SHA-256 雜湊；DB 外洩也拿不到可用的 token |

時間欄位一律 `timestamptz`。email 在寫入和查詢前都先轉小寫，所以大小寫不同視為同一個帳號。

和 02-design 原本的資料模型相比，拿掉 `email_verifications` 表和 `users.email_verified_at` 欄位。

## 程式結構
```
backend/app/
├─ core/config.py           # 新增 JWT 與 cookie 相關設定
├─ modules/
│  ├─ users/
│  │  ├─ models.py          # User
│  │  ├─ router.py          # GET /me
│  │  └─ schemas.py
│  └─ auth/
│     ├─ models.py          # RefreshToken
│     ├─ security.py        # 密碼雜湊、JWT、refresh token 產生與雜湊（純函式，不碰 DB）
│     ├─ service.py         # 註冊、登入、refresh、登出、示範登入（碰 DB）
│     ├─ deps.py            # get_current_user、require_writable_user
│     ├─ router.py          # /auth/* 端點與 cookie 處理
│     └─ schemas.py
├─ seeds/demo.py            # 建立示範帳號，可重複執行
└─ main.py                  # 掛上 auth、users 路由
backend/migrations/versions/<rev>_create_users_and_refresh_tokens.py
```
- `security.py` 是純函式，不用 DB 就能測；`service.py` 處理業務規則；`router.py` 只負責 HTTP 的輸入輸出和 cookie
- `migrations/env.py` 要 import 所有模型，讓 `Base.metadata` 包含新表

### 新設定
| 環境變數 | 預設 | 說明 |
|---|---|---|
| `JWT_SECRET` | 無（必填） | 簽 access token 的密鑰；缺少時啟動失敗 |
| `ACCESS_TOKEN_MINUTES` | 15 | |
| `REFRESH_TOKEN_DAYS` | 7 | |
| `COOKIE_SECURE` | true | 本機 http 開發時在 `.env` 設 false |

`backend/.env.example`、CI 的 `env`、`tests/conftest.py` 都要補上 `JWT_SECRET`。

## API
所有端點在 `/api/v1` 底下。錯誤沿用 FastAPI 預設格式 `{"detail": "..."}`，訊息用繁體中文；欄位格式錯誤沿用預設 422。

### 兩種 token 的分工
- **access token**：JWT，15 分鐘。前端放在記憶體，呼叫 API 時放在 `Authorization: Bearer <token>`。伺服器驗簽章即可確認身分，不用查 refresh token 或 session 表（仍會用 `sub` 查一次使用者，見下方〈驗證 access token〉）。內容為 `sub`（使用者 public_id）、`iat`、`exp`
- **refresh token**：32 bytes 隨機值（`secrets.token_urlsafe`），7 天。放在 cookie，JavaScript 讀不到。access token 過期時用它換新的

登入類端點（register、login、refresh、demo）成功時都回同一個格式：body `{"access_token": "...", "token_type": "bearer"}`，並設定 refresh cookie。

### Cookie
名稱 `refresh_token`；`HttpOnly`、`SameSite=Strict`、`Secure`（依 `COOKIE_SECURE`）、`Path=/api/v1/auth`（只有呼叫 auth 端點時瀏覽器才會送出）、`Max-Age` 等於 refresh token 有效期。

### 端點
| 端點 | 行為 |
|---|---|
| `POST /auth/register` | body：`email`、`password`（8～128 字元）、`display_name`（選填，最多 50 字元）。email 已存在 → 409「此 Email 已註冊」。成功 → 201，直接登入 |
| `POST /auth/login` | body：`email`、`password`。見下方〈登入失敗與鎖定〉 |
| `POST /auth/refresh` | 讀 cookie。見下方〈refresh 輪換〉 |
| `POST /auth/logout` | 作廢 cookie 對應的 refresh token、清除 cookie，回 204。沒帶 cookie 或 token 無效也回 204 |
| `POST /auth/demo` | 不需要 body。發示範帳號的 token；示範帳號不存在 → 503「示範帳號尚未建立」 |
| `GET /me` | 需要 access token。回 `public_id`、`email`、`display_name`、`role`、`is_demo` |

### 登入失敗與鎖定
- email 不存在、密碼錯誤、帳號停用（`is_active=false`）、示範帳號，一律回 401「Email 或密碼錯誤」
- email 不存在時仍對一個固定的假雜湊做一次比對，讓回應時間和密碼錯誤時相近，無法用回應快慢推測哪些 email 已註冊
- 密碼錯誤時 `failed_login_count + 1`；達到 **5 次**時設定 `locked_until = 現在 + 15 分鐘` 並把次數歸零
- `locked_until` 晚於現在時，不論密碼是否正確都回 423「登入失敗次數過多，請稍後再試」
- 登入成功時 `failed_login_count` 歸零、`locked_until` 清空

### refresh 輪換
1. 沒帶 cookie，或雜湊在 DB 找不到 → 401
2. 找到但**已作廢**（`revoked_at` 有值）→ 視為 token 可能被偷：一般使用者把該使用者所有未作廢的 refresh token 全部作廢；示範帳號只拒絕這一次，不影響其他人（多位訪客共用示範帳號，避免一人重用就把所有人踢出）。兩者都回 401
3. 已過期，或使用者已停用 → 401
4. 有效 → 作廢這張、發新的 refresh token 和 access token

所有回 401 的情況都同時清除 cookie。

### 驗證 access token（`get_current_user`）
- 沒有 `Authorization` 標頭、格式錯誤、簽章不符、過期 → 401，帶 `WWW-Authenticate: Bearer`
- `sub` 對應的使用者不存在或已停用 → 401
- 每次都用 `sub` 查使用者：之後的端點本來就需要內部 user id 檢查資料擁有者；順帶讓停用帳號已發出的 access token 立即失效，不用等到過期

## 示範帳號
- seed 腳本 `python -m app.seeds.demo` 建立 email 為 `demo@farewatch.local`、`is_demo=true` 的使用者；已存在就跳過，可重複執行
- 密碼雜湊用一串隨機值產生，不告訴任何人，而且登入流程直接拒絕示範帳號，所以只能走 `POST /auth/demo`
- 本機 compose 的 api 啟動指令改成 `alembic upgrade head` → `python -m app.seeds.demo` → uvicorn；正式環境到 #7 放進部署流程
- 多位訪客共用同一個示範帳號，但每人有自己的 refresh token，登出只影響自己
- #3～#5 建好追蹤、價格、通知的資料表後，把示範資料加進同一支 seed 腳本

### 寫入權限
- `require_writable_user` dependency：建立在 `get_current_user` 之上，示範帳號回 403「示範帳號為唯讀」
- #3 起所有寫入端點都掛上它；登出和 refresh 不經過 access token 驗證，不受影響
- #2 本身沒有用到它的業務端點，用測試內建立的小路由驗證

## 測試
沿用骨架的方式：連真實 Postgres，每個測試包在 transaction 裡、結束時 rollback。

| 範圍 | 案例 |
|---|---|
| `security.py` | 密碼雜湊後能驗證、錯誤密碼驗證失敗；JWT 簽發後能解出 `sub`；過期、竄改、用不同密鑰簽的 JWT 被拒；同一個 refresh token 的雜湊一致 |
| 註冊 | 成功回 201、token 與 cookie（含 HttpOnly、SameSite=Strict、Path）；重複 email（含大小寫不同）→ 409；密碼 7 字元、email 格式錯誤 → 422 |
| 登入 | 成功；密碼錯誤與 email 不存在回相同的 401；連錯 5 次後第 6 次 → 423；鎖定中密碼正確也 423；把 `locked_until` 改成過去後可以登入；成功後失敗次數歸零；停用帳號 → 401 |
| refresh | 成功並輪換，新 cookie 和舊的不同；舊 token 再用 → 401，且該使用者其他 refresh token 也被作廢；示範帳號重用舊 token → 401，但其他訪客的 token 仍有效；過期、沒帶 cookie → 401 |
| 登出 | 登出後用同一個 cookie refresh → 401；沒帶 cookie 也回 204 |
| `/me` | 有效 token 回使用者資料；沒 token、過期 token、竄改 token → 401 |
| 示範帳號 | seed 執行兩次只有一筆；`/auth/demo` 成功且 `/me` 回 `is_demo=true`；seed 前呼叫 → 503；用 email 帳密登入示範帳號 → 401；`require_writable_user` 對示範帳號回 403、一般帳號通過 |
| migration | 既有的 upgrade → downgrade 測試自動涵蓋新表 |

## 文件更新（同一個分支）
- `docs/architecture.md`：新增〈2026-10-23 決策紀錄〉——取消 Email 驗證（推翻第二次審閱第 6 項）、價格通知 Email 照寄、寄信服務到 #5 再選
- `docs/01-requirements.md`：「帳號」決策、US-01 描述與驗收條件
- `docs/02-design.md`：〈帳號與驗證設計〉段落與時序圖、ERD 與欄位清單拿掉 `email_verifications` 和 `email_verified_at`、API 清單拿掉 `verify-email` 和 `resend-verification`
- `CLAUDE.md`：〈目前狀態〉改為 M1 進行中
- `docs/03-development.md`：開發規範補上 branch protection 為「需 PR、0 approvals、CI 必須通過」
