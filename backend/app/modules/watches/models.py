import uuid
from datetime import date, datetime
from typing import Literal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

Cabin = Literal["economy", "premium_economy", "business", "first"]
WatchStatus = Literal["active", "queued", "paused", "expired"]
CABINS: tuple[str, ...] = ("economy", "premium_economy", "business", "first")
WATCH_STATUSES: tuple[str, ...] = ("active", "queued", "paused", "expired")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class PriceQuery(Base):
    """「查什麼」：條件相同的追蹤共用一筆，查價額度只花一次。"""

    __tablename__ = "price_queries"
    __table_args__ = (
        CheckConstraint(_in("cabin", CABINS), name="price_queries_cabin_check"),
        CheckConstraint("adults BETWEEN 1 AND 9", name="price_queries_adults_check"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    query_hash: Mapped[str] = mapped_column(String(64), unique=True)
    origin: Mapped[str] = mapped_column(ForeignKey("airports.iata"))
    destination: Mapped[str] = mapped_column(ForeignKey("airports.iata"))
    depart_date: Mapped[date] = mapped_column(Date)
    return_date: Mapped[date | None] = mapped_column(Date)
    cabin: Mapped[str] = mapped_column(String(16))
    adults: Mapped[int] = mapped_column(SmallInteger)
    # 排序後的 IATA 代碼；空陣列代表不限航空公司
    airlines: Mapped[list[str]] = mapped_column(ARRAY(String(2)), server_default="{}")
    is_demo: Mapped[bool] = mapped_column(server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Watch(Base):
    """「誰在追、目標價多少、什麼狀態」；查價條件只存在 price_queries。"""

    __tablename__ = "watches"
    __table_args__ = (
        CheckConstraint("target_price BETWEEN 1 AND 1000000", name="watches_target_price_check"),
        CheckConstraint(_in("status", WATCH_STATUSES), name="watches_status_check"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(unique=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    price_query_id: Mapped[int] = mapped_column(ForeignKey("price_queries.id"), index=True)
    target_price: Mapped[int]
    status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # async 不能延遲載入，查 watch 時一併 join 出查價條件
    price_query: Mapped[PriceQuery] = relationship(lazy="joined")
