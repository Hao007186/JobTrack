# M1 子專案 #1：backend 骨架 — 設計

日期：2026-10-22
狀態：待審閱
相關文件：[architecture.md](../../architecture.md)、[02-design.md](../../02-design.md)、[03-development.md](../../03-development.md)、[04-testing.md](../../04-testing.md)

## 背景與目標
M1 拆成 7 個子專案，本文件是第 1 個。AWS 帳號目前無法啟用，所以 #1～#6 先在本機完成，#7（Terraform 與部署）等 AWS 可用再做。

| # | 子專案 | 需要 AWS |
|---|---|---|
| 1 | **backend 骨架**（本文件） | 否 |
| 2 | 帳號系統 + Email 驗證 + 示範帳號 | 否 |
| 3 | 機場／航空公司資料 + 追蹤 CRUD + 生命週期 | 否 |
| 4 | PriceProvider（mock → SerpApi）+ checker + 額度預算 | 否 |
| 5 | 觸發規則 + alerts + notifications + notifier | 否（SQS 用 LocalStack） |
| 6 | 前端 | 否（需先安裝 Node.js） |
| 7 | Terraform + 部署 | 是 |

**目標：** 建好之後每個子專案都能直接加模組的 backend 基礎。完成標準：

- 本機 `docker compose up` 能啟動 api 和 postgres，`GET /api/v1/health` 回 200
- 本機 `uv run pytest` 連真實 Postgres 全部通過
- PR 上的 CI 全綠（ruff、mypy、pytest、Docker build）

## 不在範圍內
MailHog、LocalStack、frontend、Mangum handler（移到 #7）、任何業務資料表、`modules/` 底下的模組資料夾（各子專案用到時再建）。

## 技術決定
| 項目 | 決定 | 理由 |
|---|---|---|
| Python | 3.14 | 和本機版本相同；Lambda 有 3.14 基底 image |
| 套件管理 | uv，`uv.lock` 進 Git | 本機已安裝；CI 用 `uv sync --locked` 確保版本一致 |
| DB 存取 | **非同步**：SQLAlchemy 2.0 `AsyncSession` + **psycopg 3** | 與 httpx 非同步呼叫外部 API 一致，整個 backend 統一用 async；psycopg 3 對 Neon pooler（PgBouncer transaction 模式）只要關掉 prepared statement，Alembic 也用同一個 driver |
| 健康檢查 | 不查 DB | 正式環境每次健康檢查都連 Neon 會把休眠的 DB 叫醒，浪費免費的運算時數 |

## 專案結構
```
backend/
├─ pyproject.toml          # 相依套件與 ruff、mypy、pytest 設定
├─ uv.lock
├─ alembic.ini
├─ alembic/
│  ├─ env.py               # 從 app 設定讀 URL，用 async engine 執行 migration
│  ├─ script.py.mako
│  └─ versions/            # 目前是空的
├─ app/
│  ├─ main.py              # 建立 FastAPI app，掛上 /api/v1 路由
│  ├─ core/config.py       # pydantic-settings
│  ├─ db/base.py           # DeclarativeBase
│  ├─ db/session.py        # async engine、session factory、get_session()
│  └─ api/health.py        # GET /api/v1/health
├─ tests/
├─ Dockerfile
└─ .env.example
deploy/docker-compose.yml
.github/workflows/ci.yml
.pre-commit-config.yaml
```

## 元件設計

### 設定（`app/core/config.py`）
- 以 pydantic-settings 從環境變數讀取，本機另外讀 `backend/.env`
- 欄位：`DATABASE_URL`（必填）、`ENV`（`local`／`ci`／`prod`，預設 `local`）、`LOG_LEVEL`（預設 `INFO`）
- 缺少 `DATABASE_URL` 時啟動直接失敗
- `.env.example` 進 Git；`.env` 已在 `.gitignore`

### 資料庫（`app/db/`）
- `base.py`：`class Base(DeclarativeBase)`，之後所有模型繼承它；Alembic 的 `target_metadata` 指向 `Base.metadata`
- `session.py`：
  - `create_async_engine(DATABASE_URL, connect_args={"prepare_threshold": None})`，URL 格式 `postgresql+psycopg://...`；本機與 Neon 用同一套設定
  - `async_sessionmaker(expire_on_commit=False)`
  - FastAPI dependency `get_session()`：每個請求一個 `AsyncSession`，結束時關閉

### API（`app/main.py`、`app/api/health.py`）
- `main.py` 建立 app，所有路由掛在 `/api/v1` 底下（CloudFront 依 `/api/*` 轉發）
- `GET /api/v1/health` 回 `{"status": "ok"}`

### Alembic
- `env.py` 讀 `app.core.config` 的 `DATABASE_URL`，用 async engine 執行 migration
- 目前沒有 revision；機制先建好，之後每張表都會被 migration 測試涵蓋

### Dockerfile
- 基底：AWS Lambda Python 3.14 image（照 [02-design.md〈容器執行方式〉](../../02-design.md#容器執行方式)，#7 直接沿用）
- 用 uv 依 `uv.lock` 安裝相依套件，複製 `app/`、`alembic/`、`alembic.ini`
- 預設進入點保留 Lambda runtime；本機 compose 覆寫

### docker-compose（`deploy/docker-compose.yml`）
- `postgres`：`postgres:16`，帳密從環境變數讀取，資料放 named volume，加 `pg_isready` healthcheck，對外開 5432
- `api`：build `backend/Dockerfile`；`entrypoint`／`command` 覆寫為「先 `alembic upgrade head`，再 `uvicorn app.main:app --host 0.0.0.0 --reload`」；掛載 `backend/app` 支援熱重載；`depends_on` postgres healthy；對外開 8000
- 兩種本機開發方式都支援：全部用 compose 跑，或只用 compose 跑 postgres、api 在 Windows 上用 `uv run` 執行

## 測試
- pytest + pytest-asyncio；HTTP 測試用 httpx `AsyncClient` + `ASGITransport`
- 整合測試連真實 Postgres：本機用 compose 的 postgres，CI 用 service container
- 測試使用獨立資料庫 `farewatch_test`（由環境變數 `TEST_DATABASE_URL` 指定），不碰開發資料
- 測試 session 開始時跑一次 `alembic upgrade head`；每個測試包在 transaction 裡，結束時 rollback

| 測試 | 驗證內容 |
|---|---|
| health | `GET /api/v1/health` 回 200 與 `{"status": "ok"}` |
| config | 缺少 `DATABASE_URL` 時拋出驗證錯誤 |
| db | session 能執行 `SELECT 1`（確認 psycopg async 與 `prepare_threshold` 設定正確） |
| migration | `alembic upgrade head` 後 `downgrade base` 都成功 |

## 程式碼品質與 CI
- ruff（lint + format）、mypy strict
- pre-commit：commit 前本機執行 ruff 與 mypy
- `.github/workflows/ci.yml`：PR 與 push 到 `main` 時觸發
  1. 安裝 uv → `uv sync --locked`
  2. `ruff check`、`ruff format --check`
  3. `mypy`
  4. `pytest`（postgres:16 service container）
  5. build Docker image（amd64，不 push）
- branch protection（CI 全綠才能 merge）需由使用者在 GitHub 網頁設定，寫在 PR 說明中
