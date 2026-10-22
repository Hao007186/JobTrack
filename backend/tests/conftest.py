import asyncio
import os
import sys
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

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import CONNECT_ARGS, get_session  # noqa: E402
from app.main import create_app  # noqa: E402

get_settings.cache_clear()


def pytest_configure(config: pytest.Config) -> None:
    # 守門：避免設錯環境變數時 rollback／downgrade 動到開發資料
    db_name = make_url(TEST_DATABASE_URL).database or ""
    if not db_name.endswith("_test"):
        pytest.exit("TEST_DATABASE_URL 必須指向 *_test 資料庫", returncode=2)


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> Mapping[str, type[asyncio.AbstractEventLoop]] | None:
    # psycopg async 不支援 Windows 預設的 ProactorEventLoop
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return None


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
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
