import calendar
import math
from datetime import date


def days_left_in_month(today: date) -> int:
    """本月剩餘天數，含今天。"""
    last_day = calendar.monthrange(today.year, today.month)[1]
    return last_day - today.day + 1


def daily_budget(remaining: int, today: date) -> int:
    # 無條件進位：月底剩少量額度時不會每天都是 0；結果永遠不超過 remaining，不會超支
    if remaining <= 0:
        return 0
    return math.ceil(remaining / days_left_in_month(today))
