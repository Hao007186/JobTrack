"""通知設定與系統通知。只 flush，由呼叫端 commit。"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.messages import (
    ACTIVATED_BODY,
    QUOTA_BODY,
    QUOTA_TITLE,
    activated_title,
    watch_link,
)
from app.modules.notifications.models import Notification, NotificationSetting
from app.modules.watches.models import Watch


async def email_enabled(session: AsyncSession, user_id: int) -> bool:
    enabled = await session.scalar(
        select(NotificationSetting.email_enabled).where(NotificationSetting.user_id == user_id)
    )
    # 沒有設定 = 預設開啟
    return True if enabled is None else enabled


async def create_system_notification(
    session: AsyncSession,
    user_id: int,
    title: str,
    body: str,
    *,
    link: str | None = None,
    dedupe_key: str | None = None,
) -> bool:
    """回傳是否新增；同一位使用者已有相同 dedupe_key 的通知時不新增。"""
    created = await session.scalar(
        insert(Notification)
        .values(
            public_id=uuid.uuid4(),
            user_id=user_id,
            type="system",
            title=title,
            body=body,
            link=link,
            dedupe_key=dedupe_key,
        )
        .on_conflict_do_nothing(constraint="uq_notifications_user_dedupe")
        .returning(Notification.id)
    )
    return created is not None


async def notify_activated(session: AsyncSession, watch_ids: Sequence[int]) -> None:
    if not watch_ids:
        return
    watches = await session.scalars(select(Watch).where(Watch.id.in_(watch_ids)).order_by(Watch.id))
    for watch in list(watches):
        await create_system_notification(
            session,
            watch.user_id,
            activated_title(watch.price_query),
            ACTIVATED_BODY,
            link=watch_link(watch),
        )


async def notify_quota_exhausted(
    session: AsyncSession, query_ids: Sequence[int], month: str
) -> int:
    """這些 query 上有 active 追蹤的使用者各發一則，同一個月只發一次。回傳新增數。"""
    if not query_ids:
        return 0
    user_ids = await session.scalars(
        select(Watch.user_id)
        .where(Watch.price_query_id.in_(query_ids), Watch.status == "active")
        .distinct()
        .order_by(Watch.user_id)
    )
    created = 0
    for user_id in list(user_ids):
        if await create_system_notification(
            session, user_id, QUOTA_TITLE, QUOTA_BODY, dedupe_key=f"quota_exhausted:{month}"
        ):
            created += 1
    return created
