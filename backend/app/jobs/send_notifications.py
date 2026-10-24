"""寄出待寄的通知信（含之前失敗待重試的）：python -m app.jobs.send_notifications"""

import asyncio
import logging
import sys

import app.db.models  # noqa: F401  獨立執行時也要註冊所有表
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.modules.notifications.email import get_email_sender
from app.modules.notifications.notifier import SendSummary, send_pending


def format_summary(summary: SendSummary) -> str:
    return (
        f"寄信完成：寄出 {summary.sent}、失敗 {summary.failed}、"
        f"略過 {summary.skipped}、待重試 {summary.retry}"
    )


async def _main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    async with get_sessionmaker()() as session:
        summary = await send_pending(session, get_email_sender(settings), settings.app_base_url)
    print(format_summary(summary))


if __name__ == "__main__":
    # psycopg async 不支援 Windows 預設的 ProactorEventLoop
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(_main(), loop_factory=loop_factory)
