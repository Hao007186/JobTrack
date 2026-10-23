import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, false, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('user', 'admin')", name="users_role_check"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # 對外（API、前端網址）一律用 public_id，不露出流水號 id
    public_id: Mapped[uuid.UUID] = mapped_column(unique=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str]
    display_name: Mapped[str | None] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(16), server_default="user")
    is_demo: Mapped[bool] = mapped_column(server_default=false())
    is_active: Mapped[bool] = mapped_column(server_default=true())
    failed_login_count: Mapped[int] = mapped_column(server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
