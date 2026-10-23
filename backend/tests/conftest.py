import asyncio
import os
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent

# 必須在 import app 之前設定，讓 get_settings() 讀到測試資料庫
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://farewatch:farewatch@localhost:5432/farewatch_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789")
# 環境變數優先於 .env；避免本機 .env 的 COOKIE_SECURE=false 讓 cookie 測試在本機和 CI 結果不同
os.environ["COOKIE_SECURE"] = "true"

from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import CONNECT_ARGS, get_session  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.auth.security import hash_password  # noqa: E402
from app.modules.users.models import User  # noqa: E402

get_settings.cache_clear()


def pytest_configure(config: pytest.Config) -> None:
    # 守門：避免設錯環境變數時 rollback／downgrade 動到開發資料
    db_name = make_url(TEST_DATABASE_URL).database or ""
    if not db_name.endswith("_test"):
        pytest.exit("TEST_DATABASE_URL 必須指向 *_test 資料庫", returncode=2)


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> Mapping[str, type[asyncio.AbstractEventLoop]]:
    # psycopg async 不支援 Windows 預設的 ProactorEventLoop；Linux 預設本來就是 SelectorEventLoop
    # 有實作這個 hook 就必須回傳非空 mapping，回傳 None 會讓 pytest-asyncio 報 UsageError
    return {"selector": asyncio.SelectorEventLoop}


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return TEST_DATABASE_URL


@pytest.fixture(scope="session", autouse=True)
def migrated(test_database_url: str) -> None:
    command.upgrade(alembic_config(test_database_url), "head")


@pytest.fixture(scope="session")
async def engine(migrated: None, test_database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(test_database_url, connect_args=CONNECT_ARGS)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    # 每個測試包在 transaction 裡，結束時 rollback；程式內的 commit 會變成 savepoint
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        yield session
        await session.close()
        await trans.rollback()


@pytest.fixture
def app(db_session: AsyncSession) -> FastAPI:
    application = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    application.dependency_overrides[get_session] = _override_session
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    # 用 https：refresh cookie 帶 Secure，http 下 httpx 不會送出
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        yield c


async def create_user(
    session: AsyncSession,
    *,
    email: str = "alice@example.com",
    password: str = "correct-horse",
    is_demo: bool = False,
    is_active: bool = True,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password),
        is_demo=is_demo,
        is_active=is_active,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user
