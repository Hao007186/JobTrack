"""notifier：把 alert_deliveries 裡 pending 的信一封一封寄出，每封各自 commit。"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import TAIPEI_TZ
from app.modules.alerts.models import Alert, AlertDelivery
from app.modules.notifications.email import EmailError, EmailMessage, EmailSender
from app.modules.notifications.models import Notification
from app.modules.notifications.service import email_enabled
from app.modules.prices.models import PriceSnapshot
from app.modules.users.models import User

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
MAX_ERROR_LENGTH = 1000
FOOTER = "可在設定頁關閉 Email 通知。"


@dataclass
class SendSummary:
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    retry: int = 0


def build_email(
    to: str,
    notification: Notification,
    checked_at: datetime,
    booking_url: str | None,
    base_url: str,
) -> EmailMessage:
    # 重試或補寄時信會晚到，標出查價時間，讀者才不會把舊價格當成現在的價格
    checked = f"查價時間：{checked_at.astimezone(TAIPEI_TZ):%Y-%m-%d %H:%M}（台灣時間）"
    links = []
    if booking_url:
        links.append(f"訂票：{booking_url}")
    if notification.link:
        links.append(f"查看追蹤：{base_url.rstrip('/')}{notification.link}")
    parts = [f"{notification.body}\n{checked}", "\n".join(links), FOOTER]
    return EmailMessage(to=to, subject=notification.title, text="\n\n".join(p for p in parts if p))


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def send_pending(
    session: AsyncSession,
    sender: EmailSender,
    base_url: str,
    now: Callable[[], datetime] = _utcnow,
) -> SendSummary:
    summary = SendSummary()
    # 這次執行失敗過的不再取出，留給下次執行重試
    failed_ids: list[int] = []
    while True:
        row = (
            await session.execute(
                select(
                    AlertDelivery,
                    Notification,
                    User.email,
                    Alert.created_at,
                    PriceSnapshot.booking_url,
                )
                .join(Alert, Alert.id == AlertDelivery.alert_id)
                .join(Notification, Notification.alert_id == Alert.id)
                .join(User, User.id == Notification.user_id)
                .outerjoin(PriceSnapshot, PriceSnapshot.id == Alert.snapshot_id)
                .where(
                    AlertDelivery.status == "pending",
                    AlertDelivery.id.not_in(failed_ids) if failed_ids else true(),
                )
                .order_by(AlertDelivery.id)
                .limit(1)
                # 兩個 notifier 同時跑時，各自拿不同的信
                .with_for_update(skip_locked=True, of=AlertDelivery)
                .execution_options(populate_existing=True)
            )
        ).first()
        if row is None:
            return summary
        delivery, notification, to, checked_at, booking_url = row

        if not await email_enabled(session, notification.user_id):
            delivery.status = "skipped"
            summary.skipped += 1
            await session.commit()
            continue

        delivery.attempts += 1
        try:
            await sender.send(build_email(to, notification, checked_at, booking_url, base_url))
        except EmailError as e:
            delivery.last_error = str(e)[:MAX_ERROR_LENGTH]
            if delivery.attempts >= MAX_ATTEMPTS:
                delivery.status = "failed"
                summary.failed += 1
                logger.error(
                    "通知信寄送失敗 %s 次，不再重試（delivery %s）", delivery.attempts, delivery.id
                )
            else:
                summary.retry += 1
                failed_ids.append(delivery.id)
        else:
            delivery.status = "sent"
            delivery.sent_at = now()
            summary.sent += 1
        await session.commit()
