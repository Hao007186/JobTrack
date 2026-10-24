from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 同時也是優先順序：同一筆價格符合多個原因時，排在前面的當主要原因
ALERT_REASONS: tuple[str, ...] = ("below_target", "record_low", "below_typical")
DELIVERY_CHANNELS: tuple[str, ...] = ("email",)
DELIVERY_STATUSES: tuple[str, ...] = ("pending", "sent", "failed", "skipped")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class WatchAlertState(Base):
    """每個追蹤的通知狀態；沒有資料 = 初始狀態，重置就是刪掉這筆。"""

    __tablename__ = "watch_alert_states"

    watch_id: Mapped[int] = mapped_column(
        ForeignKey("watches.id", ondelete="CASCADE"), primary_key=True
    )
    below_target: Mapped[bool] = mapped_column(server_default=false(), default=False)
    below_typical: Mapped[bool] = mapped_column(server_default=false(), default=False)
    last_notified_price: Mapped[int | None]
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Alert(Base):
    """價格警示的業務紀錄；同一筆價格對同一個追蹤只會有一則。"""

    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("watch_id", "snapshot_id", name="uq_alerts_watch_snapshot"),
        CheckConstraint(_in("reason", ALERT_REASONS), name="alerts_reason_check"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"))
    # 快照因保留期限被刪除時設為 NULL，alert 自帶一份 price
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_snapshots.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(String(16))
    price: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertDelivery(Base):
    """每則 alert 在每個外部管道的寄送狀態，也是 notifier 的寄件匣。"""

    __tablename__ = "alert_deliveries"
    __table_args__ = (
        UniqueConstraint("alert_id", "channel", name="uq_alert_deliveries_alert_channel"),
        CheckConstraint(_in("channel", DELIVERY_CHANNELS), name="alert_deliveries_channel_check"),
        CheckConstraint(_in("status", DELIVERY_STATUSES), name="alert_deliveries_status_check"),
        CheckConstraint("attempts >= 0", name="alert_deliveries_attempts_check"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="pending", default="pending")
    attempts: Mapped[int] = mapped_column(server_default="0", default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
