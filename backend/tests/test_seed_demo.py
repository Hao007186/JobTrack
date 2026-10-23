from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import DEMO_EMAIL
from app.modules.users.models import User
from app.seeds.demo import ensure_demo_user


async def test_seed_idempotent(db_session: AsyncSession) -> None:
    first = await ensure_demo_user(db_session)
    second = await ensure_demo_user(db_session)
    assert first.id == second.id
    assert first.is_demo is True
    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.email == DEMO_EMAIL)
    )
    assert count == 1
