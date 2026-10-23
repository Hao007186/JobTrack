from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PriceSnapshot(Base):
    """每次查價存一筆，只新增不修改；價格一律 TWD。"""

    __tablename__ = "price_snapshots"
    __table_args__ = (
        CheckConstraint("price > 0", name="price_snapshots_price_check"),
        CheckConstraint("stops >= 0", name="price_snapshots_stops_check"),
        Index("ix_price_snapshots_query_observed", "price_query_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    price_query_id: Mapped[int] = mapped_column(ForeignKey("price_queries.id"))
    provider: Mapped[str] = mapped_column(String(16))
    price: Mapped[int]
    airline_iata: Mapped[str | None] = mapped_column(String(2))
    stops: Mapped[int]
    booking_url: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PriceBaseline(Base):
    """每個 price_query 一筆，記錄判斷「便宜」和「歷史新低」用的基準。"""

    __tablename__ = "price_baselines"

    price_query_id: Mapped[int] = mapped_column(ForeignKey("price_queries.id"), primary_key=True)
    typical_low: Mapped[int | None]
    typical_high: Mapped[int | None]
    record_low: Mapped[int | None]
    # 歷史最低價是否已用 Google 的 price_history 打底
    history_seeded: Mapped[bool] = mapped_column(server_default=false(), default=False)
    sample_count: Mapped[int] = mapped_column(server_default="0", default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApiUsage(Base):
    """自己記錄的呼叫次數，僅供紀錄；預算以 SerpApi 回報的剩餘次數為準。"""

    __tablename__ = "api_usage"

    provider: Mapped[str] = mapped_column(String(16), primary_key=True)
    # 台灣時間的 YYYY-MM
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    count: Mapped[int]
