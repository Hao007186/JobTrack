import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import Select, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.alerts.models import Alert
from app.modules.auth.deps import CurrentUser, WritableUser
from app.modules.notifications.models import Notification, NotificationSetting
from app.modules.notifications.schemas import (
    NotificationOut,
    NotificationPage,
    NotificationSettingsOut,
    NotificationSettingsUpdate,
)
from app.modules.notifications.service import email_enabled
from app.modules.prices.models import PriceSnapshot
from app.modules.users.models import User

router = APIRouter(tags=["notifications"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _with_booking_url(user: User) -> Select[Notification, str | None]:
    # 追蹤或快照被刪除後 alert／快照不存在，booking_url 為 NULL
    return (
        select(Notification, PriceSnapshot.booking_url)
        .outerjoin(Alert, Alert.id == Notification.alert_id)
        .outerjoin(PriceSnapshot, PriceSnapshot.id == Alert.snapshot_id)
        .where(Notification.user_id == user.id)
    )


def _out(notification: Notification, booking_url: str | None) -> NotificationOut:
    return NotificationOut(
        id=notification.public_id,
        type=notification.type,
        title=notification.title,
        body=notification.body,
        link=notification.link,
        booking_url=booking_url,
        is_read=notification.is_read,
        created_at=notification.created_at,
    )


@router.get("/notifications")
async def list_notifications(
    user: CurrentUser,
    session: SessionDep,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    before: uuid.UUID | None = None,
) -> NotificationPage:
    stmt = _with_booking_url(user)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    if before is not None:
        cursor = (
            await session.execute(
                select(Notification.created_at, Notification.id).where(
                    Notification.public_id == before, Notification.user_id == user.id
                )
            )
        ).first()
        if cursor is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "before：找不到這則通知")
        # created_at 可能相同，連同 id 一起比才不會漏掉或重複
        stmt = stmt.where(tuple_(Notification.created_at, Notification.id) < tuple(cursor))
    rows = await session.execute(
        stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .execution_options(populate_existing=True)
    )
    unread = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
    )
    return NotificationPage(items=[_out(n, url) for n, url in rows], unread_count=unread or 0)


@router.patch("/notifications/{public_id}/read")
async def mark_read(
    public_id: uuid.UUID, user: WritableUser, session: SessionDep
) -> NotificationOut:
    row = (
        await session.execute(
            _with_booking_url(user)
            .where(Notification.public_id == public_id)
            .execution_options(populate_existing=True)
        )
    ).first()
    # 別人的通知也回「找不到」，不透露它存在
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到通知")
    notification, booking_url = row
    notification.is_read = True
    await session.commit()
    return _out(notification, booking_url)


@router.post("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(user: WritableUser, session: SessionDep) -> Response:
    await session.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/notification-settings")
async def get_settings(user: CurrentUser, session: SessionDep) -> NotificationSettingsOut:
    return NotificationSettingsOut(email_enabled=await email_enabled(session, user.id))


@router.patch("/me/notification-settings")
async def update_settings(
    body: NotificationSettingsUpdate, user: WritableUser, session: SessionDep
) -> NotificationSettingsOut:
    values: dict[str, Any] = {"email_enabled": body.email_enabled}
    await session.execute(
        insert(NotificationSetting)
        .values(user_id=user.id, **values)
        .on_conflict_do_update(index_elements=[NotificationSetting.user_id], set_=values)
    )
    await session.commit()
    return NotificationSettingsOut(email_enabled=await email_enabled(session, user.id))
