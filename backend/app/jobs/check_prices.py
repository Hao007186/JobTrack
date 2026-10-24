"""每日查價：python -m app.jobs.check_prices（PRICE_PROVIDER 決定用 mock 或 SerpApi）

查完價後順便寄出待寄的通知信，從降價到寄信不用等下一個排程。
"""

import asyncio
import logging
import sys

import httpx

import app.db.models  # noqa: F401  獨立執行時也要註冊所有表
from app.core.clock import taipei_today
from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.jobs.send_notifications import format_summary
from app.modules.notifications.email import get_email_sender
from app.modules.notifications.notifier import send_pending
from app.modules.prices.checker import run_checks
from app.modules.prices.providers import SERPAPI_TIMEOUT_SECONDS, get_provider
from app.modules.prices.providers.base import ProviderError


async def _main() -> int:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    exit_code = 0
    async with (
        httpx.AsyncClient(timeout=SERPAPI_TIMEOUT_SECONDS) as client,
        get_sessionmaker()() as session,
    ):
        provider = get_provider(settings, client)
        try:
            summary = await run_checks(session, provider, taipei_today())
        except ProviderError as e:
            print(f"無法取得剩餘額度，這次不查價：{e}", file=sys.stderr)
            exit_code = 1
        else:
            print(
                f"查價完成（{provider.name}）：成功 {summary.checked}、"
                f"查無航班 {summary.no_result}、失敗 {summary.failed}、略過 {summary.skipped}；"
                f"執行前剩餘額度 {summary.remaining}"
            )
        # 查價失敗也照寄：之前失敗待重試的信不該被耽擱
        sent = await send_pending(session, get_email_sender(settings), settings.app_base_url)
    print(format_summary(sent))
    return exit_code


if __name__ == "__main__":
    # psycopg async 不支援 Windows 預設的 ProactorEventLoop
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    sys.exit(asyncio.run(_main(), loop_factory=loop_factory))
