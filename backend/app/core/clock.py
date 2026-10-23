from datetime import UTC, date, datetime, timedelta, timezone

# 台灣沒有夏令時間，用固定時差即可，不需要時區資料庫（Windows 上沒有內建）
TAIPEI_TZ = timezone(timedelta(hours=8))


def taipei_today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(TAIPEI_TZ).date()


def get_today() -> date:
    """FastAPI dependency；測試可以覆寫成固定日期。"""
    return taipei_today()
