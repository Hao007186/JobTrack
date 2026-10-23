"""每日維護：出發日已過的追蹤標成過期並補位。python -m app.jobs.maintenance"""

import asyncio
import sys

import app.db.models  # noqa: F401  獨立執行時也要註冊所有表
from app.core.clock import taipei_today
from app.db.session import get_sessionmaker
from app.modules.watches.service import expire_watches


async def _main() -> None:
    async with get_sessionmaker()() as session:
        expired, activated = await expire_watches(session, taipei_today())
    print(f"每日維護完成：過期 {expired} 個、啟用 {activated} 個")


if __name__ == "__main__":
    # psycopg async 不支援 Windows 預設的 ProactorEventLoop
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(_main(), loop_factory=loop_factory)
