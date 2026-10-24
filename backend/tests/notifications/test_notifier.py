from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.models import AlertDelivery
from app.modules.alerts.rules import AlertState, Decision
from app.modules.alerts.service import create_alert
from app.modules.notifications.email import EmailError, EmailMessage
from app.modules.notifications.models import NotificationSetting
from app.modules.notifications.notifier import MAX_ATTEMPTS, SendSummary, send_pending
from app.modules.prices.models import PriceSnapshot
from app.modules.watches.models import Watch
from tests.conftest import create_user
from tests.notifications.conftest import insert_watch

NOW = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)
BASE_URL = "http://localhost:5173"
DECISION = Decision(notify=True, reasons=("below_target",), new_state=AlertState())


class FakeSender:
    def __init__(self, error: str | None = None) -> None:
        self.error = error
        self.attempts: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.attempts.append(message)
        if self.error is not None:
            raise EmailError(self.error)


async def _pending(
    session: AsyncSession, booking_url: str | None = "https://example.test"
) -> tuple[Watch, AlertDelivery]:
    user = await create_user(session)
    watch = await insert_watch(session, user, target_price=9500)
    snapshot = PriceSnapshot(
        price_query_id=watch.price_query_id,
        provider="mock",
        price=9000,
        stops=0,
        booking_url=booking_url,
        observed_at=NOW,
    )
    session.add(snapshot)
    await session.flush()
    await create_alert(session, watch, snapshot.id, 9000, DECISION, created_at=NOW, deliver=True)
    delivery = await session.scalar(select(AlertDelivery))
    assert delivery is not None
    return watch, delivery


async def _send(session: AsyncSession, sender: FakeSender) -> SendSummary:
    return await send_pending(session, sender, BASE_URL, now=lambda: NOW)


async def _reload(session: AsyncSession, delivery: AlertDelivery) -> AlertDelivery:
    await session.refresh(delivery)
    return delivery


async def test_send_success(db_session: AsyncSession) -> None:
    watch, delivery = await _pending(db_session)
    sender = FakeSender()

    assert await _send(db_session, sender) == SendSummary(sent=1)

    delivery = await _reload(db_session, delivery)
    assert (delivery.status, delivery.attempts, delivery.sent_at) == ("sent", 1, NOW)
    message = sender.attempts[0]
    assert message.to == "alice@example.com"
    assert "跌破目標價" in message.subject
    assert "訂票：https://example.test" in message.text
    assert f"查看追蹤：{BASE_URL}/watches/{watch.public_id}" in message.text
    assert "可在設定頁關閉 Email 通知。" in message.text

    # 已寄出的不會再被取出
    assert await _send(db_session, sender) == SendSummary()


async def test_no_booking_line_without_url(db_session: AsyncSession) -> None:
    await _pending(db_session, booking_url=None)
    sender = FakeSender()
    await _send(db_session, sender)
    assert "訂票：" not in sender.attempts[0].text
    assert "None" not in sender.attempts[0].text


async def test_failure_keeps_pending(db_session: AsyncSession) -> None:
    _, delivery = await _pending(db_session)
    sender = FakeSender(error="connection refused")

    assert await _send(db_session, sender) == SendSummary(retry=1)

    assert len(sender.attempts) == 1
    delivery = await _reload(db_session, delivery)
    assert (delivery.status, delivery.attempts) == ("pending", 1)
    assert delivery.last_error == "connection refused"


async def test_fifth_failure_marks_failed(db_session: AsyncSession) -> None:
    _, delivery = await _pending(db_session)
    delivery.attempts = MAX_ATTEMPTS - 1
    await db_session.flush()
    sender = FakeSender(error="boom")

    assert await _send(db_session, sender) == SendSummary(failed=1)
    delivery = await _reload(db_session, delivery)
    assert (delivery.status, delivery.attempts) == ("failed", 5)

    assert await _send(db_session, sender) == SendSummary()
    assert len(sender.attempts) == 1


async def test_email_disabled_skips(db_session: AsyncSession) -> None:
    watch, delivery = await _pending(db_session)
    db_session.add(NotificationSetting(user_id=watch.user_id, email_enabled=False))
    await db_session.flush()
    sender = FakeSender()

    assert await _send(db_session, sender) == SendSummary(skipped=1)
    assert sender.attempts == []
    assert (await _reload(db_session, delivery)).status == "skipped"


async def test_deleted_watch_pending_gone(db_session: AsyncSession) -> None:
    watch, _ = await _pending(db_session)
    await db_session.delete(watch)
    await db_session.flush()
    sender = FakeSender()

    assert await _send(db_session, sender) == SendSummary()
    assert sender.attempts == []


async def test_last_error_truncated(db_session: AsyncSession) -> None:
    _, delivery = await _pending(db_session)
    await _send(db_session, FakeSender(error="x" * 2000))
    delivery = await _reload(db_session, delivery)
    assert delivery.last_error == "x" * 1000
