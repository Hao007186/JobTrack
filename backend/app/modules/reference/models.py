from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# v1 只追蹤台灣出發的航班
ORIGIN_COUNTRY = "TW"


class Airport(Base):
    __tablename__ = "airports"

    iata: Mapped[str] = mapped_column(String(3), primary_key=True)
    name_zh: Mapped[str] = mapped_column(String(50))
    city_zh: Mapped[str] = mapped_column(String(50))
    # ISO 3166-1 alpha-2
    country: Mapped[str] = mapped_column(String(2))


class Airline(Base):
    __tablename__ = "airlines"

    iata: Mapped[str] = mapped_column(String(2), primary_key=True)
    name_zh: Mapped[str] = mapped_column(String(50))
