from datetime import datetime
from typing import Literal

from pydantic import BaseModel

PriceRange = Literal["30d", "90d", "all"]


class PricePoint(BaseModel):
    observed_at: datetime
    price: int
    airline_iata: str | None


class BaselineOut(BaseModel):
    latest_price: int | None
    latest_observed_at: datetime | None
    last_checked_at: datetime | None
    typical_low: int | None
    typical_high: int | None
    record_low: int | None
    # false 時前端顯示「歷史資料累積中」
    history_ready: bool
