from datetime import UTC, date, datetime

from app.core.clock import taipei_today


def test_taipei_today_crosses_midnight() -> None:
    # 台灣是 UTC+8：UTC 16:00 已經是隔天 00:00
    assert taipei_today(datetime(2026, 10, 31, 16, 30, tzinfo=UTC)) == date(2026, 11, 1)
    assert taipei_today(datetime(2026, 10, 31, 15, 59, tzinfo=UTC)) == date(2026, 10, 31)
