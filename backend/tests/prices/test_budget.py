from datetime import date

import pytest

from app.modules.prices.budget import daily_budget, days_left_in_month


@pytest.mark.parametrize(
    ("today", "expected"),
    [(date(2026, 10, 1), 31), (date(2026, 10, 31), 1), (date(2028, 2, 1), 29)],
)
async def test_days_left(today: date, expected: int) -> None:
    assert days_left_in_month(today) == expected


@pytest.mark.parametrize(
    ("remaining", "today", "expected"),
    [
        (250, date(2026, 10, 1), 9),
        (5, date(2026, 10, 22), 1),
        (0, date(2026, 10, 22), 0),
        (7, date(2026, 10, 31), 7),
        (31, date(2026, 10, 1), 1),
    ],
)
async def test_daily_budget(remaining: int, today: date, expected: int) -> None:
    assert daily_budget(remaining, today) == expected
