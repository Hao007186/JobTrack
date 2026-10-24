"""通知設定與系統通知。只 flush，由呼叫端 commit。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import NotificationSetting


async def email_enabled(session: AsyncSession, user_id: int) -> bool:
    enabled = await session.scalar(
        select(NotificationSetting.email_enabled).where(NotificationSetting.user_id == user_id)
    )
    # 沒有設定 = 預設開啟
    return True if enabled is None else enabled
