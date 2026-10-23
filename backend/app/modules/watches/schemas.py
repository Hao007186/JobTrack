import uuid
from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.watches.models import Cabin, Watch, WatchStatus


def _upper_codes(codes: list[str]) -> list[str]:
    return sorted({c.strip().upper() for c in codes})


class WatchCreate(BaseModel):
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    depart_date: date
    return_date: date | None = None
    cabin: Cabin = "economy"
    adults: int = Field(default=1, ge=1, le=9)
    target_price: int = Field(ge=1, le=1_000_000)
    airlines: list[str] = []

    @field_validator("origin", "destination")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("airlines")
    @classmethod
    def _airlines(cls, v: list[str]) -> list[str]:
        return _upper_codes(v)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.origin == self.destination:
            raise ValueError("目的地不能和出發地相同")
        if self.return_date is not None and self.return_date < self.depart_date:
            raise ValueError("回程日不能早於出發日")
        return self


class WatchUpdate(BaseModel):
    """只處理有送出的欄位；組合後的完整條件在 service 層驗證。"""

    origin: str | None = Field(default=None, min_length=3, max_length=3)
    destination: str | None = Field(default=None, min_length=3, max_length=3)
    depart_date: date | None = None
    # 明確送 null 代表改成單程；沒送代表不改（用 model_fields_set 區分）
    return_date: date | None = None
    cabin: Cabin | None = None
    adults: int | None = Field(default=None, ge=1, le=9)
    target_price: int | None = Field(default=None, ge=1, le=1_000_000)
    airlines: list[str] | None = None
    # expired、queued 只能由系統決定
    status: Literal["active", "paused"] | None = None

    @field_validator("origin", "destination")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.strip().upper() if v is not None else None

    @field_validator("airlines")
    @classmethod
    def _airlines(cls, v: list[str] | None) -> list[str] | None:
        return _upper_codes(v) if v is not None else None


class WatchOut(BaseModel):
    public_id: uuid.UUID
    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    trip_type: Literal["one_way", "round_trip"]
    cabin: str
    adults: int
    airlines: list[str]
    target_price: int
    status: WatchStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_watch(cls, watch: Watch) -> WatchOut:
        q = watch.price_query
        return cls(
            public_id=watch.public_id,
            origin=q.origin,
            destination=q.destination,
            depart_date=q.depart_date,
            return_date=q.return_date,
            trip_type="one_way" if q.return_date is None else "round_trip",
            cabin=q.cabin,
            adults=q.adults,
            airlines=list(q.airlines),
            target_price=watch.target_price,
            status=watch.status,
            created_at=watch.created_at,
            updated_at=watch.updated_at,
        )
