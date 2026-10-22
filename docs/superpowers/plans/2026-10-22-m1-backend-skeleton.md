# M1 backend 骨架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal：** 建立 FastAPI backend 骨架（設定、async DB、Alembic、`/api/v1/health`、Dockerfile、docker-compose、CI），之後各子專案直接在上面加模組。

**Architecture：** `backend/` 是 uv 管理的 Python 3.14 專案。設定由 pydantic-settings 從環境變數讀取；DB 用 SQLAlchemy 2.0 `AsyncSession` + psycopg 3，engine 延遲建立（`lru_cache`），讓測試可以先設好環境變數。整合測試連真實 Postgres 的 `farewatch_test` 資料庫，每個測試在 transaction 裡跑完就 rollback。

**Tech Stack：** Python 3.14、uv、FastAPI、uvicorn、SQLAlchemy 2.0（asyncio）、psycopg 3（binary）、Alembic、pydantic-settings、pytest + pytest-asyncio + httpx、ruff、mypy、pre-commit、Docker（AWS Lambda Python 3.14 基底）、docker compose、GitHub Actions。

**Spec：** [docs/superpowers/specs/2026-10-22-m1-backend-skeleton-design.md](../specs/2026-10-22-m1-backend-skeleton-design.md)

## Global Constraints
- Python **3.14**；套件用 **uv**，`backend/uv.lock` 進 Git，CI 用 `uv sync --locked`
- DB URL 格式 `postgresql+psycopg://...`；engine 一律 `connect_args={"prepare_threshold": None}`
- 所有路由掛在 `/api/v1` 底下；`GET /api/v1/health` 回 `{"status": "ok"}`，**不查 DB**
- 環境變數：`DATABASE_URL`（必填）、`ENV`（`local`／`ci`／`prod`，預設 `local`）、`LOG_LEVEL`（預設 `INFO`）；測試用 `TEST_DATABASE_URL`
- 測試資料庫名稱 `farewatch_test`；Postgres image `postgres:16`
- ruff（lint + format）、mypy strict；不建 `modules/`、不加 Mangum、MailHog、LocalStack
- Commit 用 Conventional Commits，訊息結尾加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`；所有指令在 `backend/` 下執行，除非另外註明
- 文件、註解、commit 訊息用繁體中文

## Review Focus
1. **Windows 本機跑 pytest**：psycopg async 不支援 Windows 預設的 ProactorEventLoop，會出現 `Psycopg cannot use the 'ProactorEventLoop'`。使用者期待在 Windows 上 `uv run pytest` 就能通過 → Task 3 的 conftest 在 win32 改用 SelectorEventLoop，Alembic `env.py` 也一樣（Task 4）
2. **從 Neon 主控台直接複製的 URL 是 `postgresql://...`**：沒有指定 driver，SQLAlchemy 會去找沒安裝的 psycopg2 → 設定要自動改成 `postgresql+psycopg://`（Task 1 加測試）
3. **Neon pooler（PgBouncer）遇到 prepared statement 會出錯**：本機 Postgres 不會重現 → Task 3 加測試，斷言實際連線的 `prepare_threshold is None`
4. **測試誤連開發資料庫**：`TEST_DATABASE_URL` 設錯會 rollback 不到、甚至在 downgrade 時刪掉開發資料 → conftest 檢查資料庫名稱結尾必須是 `_test`，否則直接中止（Task 3）
5. **compose 的 api 比 postgres 先啟動**：migration 連不上就失敗 → `depends_on: condition: service_healthy`（Task 5 驗證）

---

### Task 1：Python 專案與設定

**Files:**
- Create: `backend/pyproject.toml`（由 `uv init` 產生後修改）、`backend/uv.lock`、`backend/.python-version`
- Create: `backend/app/__init__.py`、`backend/app/core/__init__.py`、`backend/app/core/config.py`
- Create: `backend/tests/__init__.py`、`backend/tests/test_config.py`
- Create: `backend/.env.example`
- Modify: `.gitignore`（加上 `.venv/`、`.mypy_cache/`、`.pytest_cache/`、`.ruff_cache/`）

**Interfaces:**
- Produces:
  - `class Settings(BaseSettings)`：`database_url: str`、`env: Literal["local", "ci", "prod"] = "local"`、`log_level: str = "INFO"`；`model_config = SettingsConfigDict(env_file=".env", extra="ignore")`
  - `def get_settings() -> Settings`（`functools.lru_cache`）

- [ ] **Step 1：建立 uv 專案**

在 repo 根目錄執行 `uv init --app --no-readme --python 3.14 backend`，刪掉產生的 `main.py`。專案名稱改成 `farewatch-backend`。
加相依：`uv add fastapi uvicorn "sqlalchemy[asyncio]" "psycopg[binary]" alembic pydantic-settings`
加開發相依：`uv add --dev pytest pytest-asyncio httpx ruff mypy pre-commit`

在 `pyproject.toml` 加上：
- `[tool.ruff]`：`target-version = "py314"`、`line-length = 100`；`[tool.ruff.lint] select = ["E", "F", "I", "UP", "B", "ASYNC"]`
- `[tool.mypy]`：`strict = true`、`plugins = ["pydantic.mypy"]`、`files = ["app", "tests", "alembic"]`
- `[tool.pytest.ini_options]`：`asyncio_mode = "auto"`、`asyncio_default_fixture_loop_scope = "session"`、`testpaths = ["tests"]`

- [ ] **Step 2：寫失敗的測試** `tests/test_config.py`

```python
def test_missing_database_url_raises(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)

def test_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/db")
    s = Settings(_env_file=None)
    assert s.env == "local"
    assert s.log_level == "INFO"

@pytest.mark.parametrize("raw", ["postgresql://u:p@h:5432/db", "postgres://u:p@h:5432/db"])
def test_plain_postgres_url_gets_psycopg_driver(monkeypatch, raw):
    monkeypatch.setenv("DATABASE_URL", raw)
    assert Settings(_env_file=None).database_url == "postgresql+psycopg://u:p@h:5432/db"

def test_invalid_env_rejected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/db")
    monkeypatch.setenv("ENV", "staging")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

（mypy strict 下測試函式要加型別註記，例如 `monkeypatch: pytest.MonkeyPatch`、`-> None`。）

- [ ] **Step 3：執行測試，確認失敗**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.core.config'`

- [ ] **Step 4：實作 `app/core/config.py`**

`Settings` 和 `get_settings()` 如 Interfaces。`database_url` 用 `field_validator`：開頭是 `postgresql://` 或 `postgres://` 時換成 `postgresql+psycopg://`，其他保持原樣。

`.env.example`（註解說明本機與 compose 的差別）：
```
DATABASE_URL=postgresql+psycopg://farewatch:farewatch@localhost:5432/farewatch
TEST_DATABASE_URL=postgresql+psycopg://farewatch:farewatch@localhost:5432/farewatch_test
ENV=local
LOG_LEVEL=INFO
POSTGRES_USER=farewatch
POSTGRES_PASSWORD=farewatch
POSTGRES_DB=farewatch
```

- [ ] **Step 5：執行測試、lint、型別檢查**

Run: `uv run pytest tests/test_config.py -v; uv run ruff check; uv run ruff format --check; uv run mypy`
Expected: 4 個測試（parametrize 算 2 個，共 5 筆）PASS；ruff、mypy 無錯誤。`alembic/` 還不存在時 mypy 若報找不到路徑，先暫時從 `files` 拿掉，Task 4 再加回。

- [ ] **Step 6：Commit**

```bash
git add .gitignore backend/
git commit -m "feat: 建立 backend 專案與環境變數設定"
```

---

### Task 2：FastAPI app 與健康檢查

**Files:**
- Create: `backend/app/main.py`、`backend/app/api/__init__.py`、`backend/app/api/health.py`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Produces:
  - `app.api.health.router: APIRouter`，路徑 `/health`
  - `app.main.create_app() -> FastAPI`：以 `include_router(..., prefix="/api/v1")` 掛上路由；`app.main.app = create_app()`
  - `create_app()` **不可**呼叫 `get_settings()` 或建立 engine（測試和 import 都不應該需要 DB）

- [ ] **Step 1：寫失敗的測試** `tests/test_health.py`

```python
async def test_health_ok():
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        r = await c.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

async def test_health_not_mounted_at_root():
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        r = await c.get("/health")
    assert r.status_code == 404
```

- [ ] **Step 2：執行測試，確認失敗**

Run: `uv run pytest tests/test_health.py -v`
Expected: FAIL，`No module named 'app.main'`

- [ ] **Step 3：實作 `health.py`、`main.py`**

health handler 是 `async def health() -> dict[str, str]`。`create_app()` 設 `title="FareWatch API"`。

- [ ] **Step 4：執行測試**

Run: `uv run pytest -v; uv run ruff check; uv run mypy`
Expected: 全部 PASS，無錯誤

- [ ] **Step 5：Commit**

```bash
git add backend/app backend/tests
git commit -m "feat: 新增 FastAPI app 與 /api/v1/health"
```

---

### Task 3：async DB session、本機 Postgres、測試基礎設施

**Files:**
- Create: `backend/app/db/__init__.py`、`backend/app/db/base.py`、`backend/app/db/session.py`
- Create: `deploy/docker-compose.yml`（先只有 `postgres`）、`deploy/postgres-init/01-create-test-db.sql`
- Create: `backend/tests/conftest.py`、`backend/tests/test_db.py`

**Interfaces:**
- Consumes: `get_settings()`（Task 1）、`create_app()`（Task 2）
- Produces:
  - `app.db.base.Base(DeclarativeBase)`
  - `app.db.session.get_engine() -> AsyncEngine`（`lru_cache`；`create_async_engine(settings.database_url, connect_args={"prepare_threshold": None}, pool_pre_ping=True)`）
  - `app.db.session.get_sessionmaker() -> async_sessionmaker[AsyncSession]`（`lru_cache`；`expire_on_commit=False`）
  - `app.db.session.get_session() -> AsyncIterator[AsyncSession]`：FastAPI dependency，`async with get_sessionmaker()() as s: yield s`
  - conftest fixtures：`test_database_url: str`（session scope）、`engine: AsyncEngine`（session scope）、`db_session: AsyncSession`（function scope，transaction 包住、結束 rollback，並用 `app.dependency_overrides[get_session]` 讓 API 測試共用同一個 session）、`client: AsyncClient`

- [ ] **Step 1：compose 的 postgres**

`deploy/docker-compose.yml`：
- `postgres`：`image: postgres:16`；`env_file: ../backend/.env`（只用到 `POSTGRES_*`）；`ports: ["5432:5432"]`；volume `pgdata:/var/lib/postgresql/data`；`./postgres-init:/docker-entrypoint-initdb.d:ro`；healthcheck `pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}`，interval 2s，retries 15
- `01-create-test-db.sql`：`CREATE DATABASE farewatch_test;`

Run（repo 根目錄）：先 `Copy-Item backend/.env.example backend/.env`，再 `docker compose -f deploy/docker-compose.yml up -d postgres`，接著 `docker compose -f deploy/docker-compose.yml exec postgres psql -U farewatch -l`
Expected: 列表中有 `farewatch` 和 `farewatch_test`

- [ ] **Step 2：寫失敗的測試** `tests/test_db.py`

```python
async def test_select_one(db_session):
    assert (await db_session.execute(text("SELECT 1"))).scalar_one() == 1

async def test_prepared_statements_disabled(db_session):
    conn = await db_session.connection()
    raw = await conn.get_raw_connection()
    assert raw.driver_connection.prepare_threshold is None

async def test_rollback_isolation_part1(db_session):
    await db_session.execute(text("CREATE TABLE _iso_probe (id int)"))

async def test_rollback_isolation_part2(db_session):
    exists = (await db_session.execute(text("SELECT to_regclass('_iso_probe')"))).scalar_one()
    assert exists is None
```

`conftest.py` 另外加一個測試函式不能涵蓋的守門：讀到 `TEST_DATABASE_URL` 後，用 `sqlalchemy.engine.make_url(url).database` 檢查名稱結尾是 `_test`，不是就 `pytest.exit("TEST_DATABASE_URL 必須指向 *_test 資料庫")`。

- [ ] **Step 3：執行測試，確認失敗**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL，`fixture 'db_session' not found` 或 `No module named 'app.db'`

- [ ] **Step 4：實作 `base.py`、`session.py`、`conftest.py`**

conftest 要點：
- 在 import `app` 之前：`TEST_DATABASE_URL` 預設 `postgresql+psycopg://farewatch:farewatch@localhost:5432/farewatch_test`，並 `os.environ["DATABASE_URL"] = TEST_DATABASE_URL`，然後 `get_settings.cache_clear()`
- **Windows**：`sys.platform == "win32"` 時讓 pytest-asyncio 使用 `asyncio.SelectorEventLoop`。依安裝的 pytest-asyncio 版本選用它支援的方式（loop factory 設定，或覆寫 `event_loop_policy` fixture 回傳 `asyncio.WindowsSelectorEventLoopPolicy()`）；若因此出現 DeprecationWarning，用 `filterwarnings` 只過濾這一條
- `db_session`：`async with engine.connect() as conn: trans = await conn.begin(); session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)`，yield 後 `await session.close(); await trans.rollback()`
- `client`：`create_app()` + `dependency_overrides[get_session] = lambda: db_session`（用 async generator 包一層），`AsyncClient(transport=ASGITransport(app), base_url="http://test")`
- `engine` fixture 結束時 `await engine.dispose()`

- [ ] **Step 5：執行測試**

Run: `uv run pytest -v; uv run ruff check; uv run mypy`
Expected: 全部 PASS（含 Windows 本機）；無錯誤

- [ ] **Step 6：驗證守門**

Run: `$env:TEST_DATABASE_URL="postgresql+psycopg://farewatch:farewatch@localhost:5432/farewatch"; uv run pytest tests/test_db.py; Remove-Item Env:TEST_DATABASE_URL`
Expected: pytest 立即結束並顯示「TEST_DATABASE_URL 必須指向 *_test 資料庫」，沒有執行任何測試

- [ ] **Step 7：Commit**

```bash
git add backend deploy
git commit -m "feat: 新增 async DB session 與 Postgres 整合測試基礎設施"
```

---

### Task 4：Alembic

**Files:**
- Create: `backend/alembic.ini`、`backend/alembic/env.py`、`backend/alembic/script.py.mako`、`backend/alembic/versions/.gitkeep`
- Modify: `backend/tests/conftest.py`（session 開始時 `upgrade head`）
- Test: `backend/tests/test_migrations.py`

**Interfaces:**
- Consumes: `Base.metadata`（Task 3）、`get_settings()`（Task 1）
- Produces:
  - `env.py` 取 URL 的順序：`config.get_main_option("sqlalchemy.url")` 有值就用，否則 `get_settings().database_url`；`alembic.ini` 裡**不寫** `sqlalchemy.url`
  - conftest helper `def alembic_config(url: str) -> alembic.config.Config`（指向 `backend/alembic.ini`，並 `set_main_option("sqlalchemy.url", url)`）

- [ ] **Step 1：初始化**

Run: `uv run alembic init -t async alembic`
修改 `env.py`：`target_metadata = Base.metadata`；URL 依 Interfaces 的順序取得；online 模式用 `async_engine_from_config(..., connect_args={"prepare_threshold": None})`；執行時用 `asyncio.run(run_async_migrations(), loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None)`。`alembic.ini` 刪掉 `sqlalchemy.url`，`file_template` 設為 `%%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s`。`env.py` 要通過 mypy strict（若 Task 1 暫時拿掉了 `alembic`，加回 `files`）。

- [ ] **Step 2：寫失敗的測試** `tests/test_migrations.py`（同步測試，不加 async）

```python
def test_upgrade_then_downgrade(test_database_url):
    cfg = alembic_config(test_database_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
```

- [ ] **Step 3：執行測試，確認失敗**

Run: `uv run pytest tests/test_migrations.py -v`
Expected: FAIL，`alembic_config` 未定義

- [ ] **Step 4：實作**

conftest 加 `alembic_config()`，以及 session scope、`autouse=True` 的同步 fixture `migrated(test_database_url)`：呼叫 `command.upgrade(alembic_config(url), "head")`。`engine` fixture 依賴 `migrated`。

- [ ] **Step 5：執行測試、手動跑一次 CLI**

Run: `uv run pytest -v; uv run alembic upgrade head; uv run alembic current; uv run mypy`
Expected: 全部 PASS；`alembic current` 正常結束、沒有 revision（目前沒有 migration）；mypy 無錯誤

- [ ] **Step 6：Commit**

```bash
git add backend
git commit -m "feat: 設定 Alembic async migration"
```

---

### Task 5：Dockerfile 與 compose 的 api 服務

**Files:**
- Create: `backend/Dockerfile`、`backend/.dockerignore`
- Modify: `deploy/docker-compose.yml`（加 `api`）

**Interfaces:**
- Consumes: `app.main:app`（Task 2）、`alembic.ini`（Task 4）
- Produces：image 內程式碼與相依套件都在 `${LAMBDA_TASK_ROOT}`（`/var/task`）；`ENV PYTHONPATH=/var/task`；預設 `CMD` 保留 Lambda runtime（#7 再指定 handler）

- [ ] **Step 1：寫 Dockerfile**

- builder stage：`ghcr.io/astral-sh/uv` image（版本固定，例如 `0.12.17`）只用來取 `uv` 執行檔
- 主 stage：`FROM public.ecr.aws/lambda/python:3.14`；`COPY --from=uv /uv /bin/uv`；複製 `pyproject.toml`、`uv.lock` 後執行 `uv export --frozen --no-dev --no-hashes -o requirements.txt && uv pip install --system --target ${LAMBDA_TASK_ROOT} -r requirements.txt`（先裝相依套件，善用 layer cache）；再複製 `app/`、`alembic/`、`alembic.ini`
- `.dockerignore`：`.venv`、`.env`、`tests`、`__pycache__`、各種 cache 資料夾

Run（repo 根目錄）：`docker build -t farewatch-backend:dev backend`
Expected: build 成功

- [ ] **Step 2：compose 加 `api`**

- `build: ../backend`；`env_file: ../backend/.env`；`environment: DATABASE_URL: postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}`（容器內 host 是 `postgres`，不是 localhost）
- `entrypoint: ["sh", "-c"]`；`command: ["python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]`；`working_dir: /var/task`
- `volumes: ["../backend/app:/var/task/app"]`；`ports: ["8000:8000"]`
- `depends_on: postgres: condition: service_healthy`

- [ ] **Step 3：驗證整套啟動**

Run（repo 根目錄）：`docker compose -f deploy/docker-compose.yml down -v; docker compose -f deploy/docker-compose.yml up -d --build`，等到 api 起來後執行 `Invoke-RestMethod http://localhost:8000/api/v1/health`
Expected: 回 `status: ok`；`docker compose -f deploy/docker-compose.yml logs api` 看得到 alembic 執行與 uvicorn 啟動；`down -v` 後從零啟動也成功（驗證 Review Focus 第 5 點）

- [ ] **Step 4：驗證熱重載**

暫時改 `health.py` 的回應（不要 commit），看 log 出現 reload，`Invoke-RestMethod` 回新值，再改回來。
Expected: 不需要重新 build 就生效

- [ ] **Step 5：Commit**

```bash
git add backend/Dockerfile backend/.dockerignore deploy/docker-compose.yml
git commit -m "feat: 新增 backend Dockerfile 與 compose api 服務"
```

---

### Task 6：pre-commit 與 CI

**Files:**
- Create: `.pre-commit-config.yaml`、`.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 1～5 的所有指令

- [ ] **Step 1：`.pre-commit-config.yaml`**

用 `repo: local` hooks，透過 uv 跑 backend 裡已鎖定的版本，避免和 `uv.lock` 版本不一致：
- `ruff check --fix`、`ruff format`：`entry: uv run --directory backend ruff ...`，`files: ^backend/`
- `mypy`：`entry: uv run --directory backend mypy`，`pass_filenames: false`，`files: ^backend/`

Run（repo 根目錄）：`uv run --directory backend pre-commit install`，然後 `uv run --directory backend pre-commit run --all-files`
Expected: 全部 Passed

- [ ] **Step 2：`.github/workflows/ci.yml`**

- `on: pull_request`、`push: branches: [main]`
- job `backend`（`ubuntu-latest`，`defaults.run.working-directory: backend`）：
  - service `postgres:16`，`POSTGRES_USER/PASSWORD=farewatch`、`POSTGRES_DB=farewatch_test`，health-cmd `pg_isready`，port 5432
  - env：`ENV=ci`、`DATABASE_URL` 和 `TEST_DATABASE_URL` 都設 `postgresql+psycopg://farewatch:farewatch@localhost:5432/farewatch_test`
  - steps：`actions/checkout@v4` → `astral-sh/setup-uv@v6`（`enable-cache: true`）→ `uv sync --locked` → `uv run ruff check` → `uv run ruff format --check` → `uv run mypy` → `uv run pytest -v`
- job `docker-build`：checkout → `docker build -t farewatch-backend:ci backend`（不 push）

- [ ] **Step 3：本機模擬 CI 步驟**

Run（`backend/`）：`uv sync --locked; uv run ruff check; uv run ruff format --check; uv run mypy; uv run pytest -v`，以及在 repo 根目錄 `docker build -t farewatch-backend:ci backend`
Expected: 全部成功。真正的 GitHub Actions 要 push 後才會跑，push 前先問使用者

- [ ] **Step 4：Commit**

```bash
git add .pre-commit-config.yaml .github/workflows/ci.yml
git commit -m "ci: 新增 pre-commit 與 GitHub Actions CI"
```

---

## 完成後
- push 分支並在 GitHub 網頁開 PR（使用者本機沒有 `gh`）。PR 說明要提醒使用者設定 branch protection：`main` 要求 CI 的 `backend`、`docker-build` 通過才能 merge
- 對照 spec 的完成標準，三項都要有實際執行結果才能宣稱完成
