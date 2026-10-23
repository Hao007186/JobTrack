from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.watches.slots import QueryConditions
from app.seeds.reference import seed_reference

TODAY = date(2026, 11, 1)

_BASE = QueryConditions(
    origin="TPE",
    destination="NRT",
    depart_date=TODAY + timedelta(days=30),
    return_date=None,
    cabin="economy",
    adults=1,
    airlines=(),
    is_demo=False,
)


@pytest.fixture(autouse=True)
async def reference(db_session: AsyncSession) -> None:
    await seed_reference(db_session)


def conditions(**overrides: Any) -> QueryConditions:
    return replace(_BASE, **overrides)
