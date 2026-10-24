import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class NotificationOut(BaseModel):
    # 對外用 public_id，不露出流水號
    id: uuid.UUID
    type: Literal["price_alert", "system"]
    title: str
    body: str
    link: str | None
    booking_url: str | None
    is_read: bool
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    unread_count: int


class NotificationSettingsOut(BaseModel):
    email_enabled: bool


class NotificationSettingsUpdate(BaseModel):
    email_enabled: bool
