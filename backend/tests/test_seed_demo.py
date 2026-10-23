from datetime import date

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import DEMO_EMAIL
from app.modules.users.models import User
from app.modules.watches.models import Watch
from app.seeds.demo import ensure_demo_user, ensure_demo_watches
from app.seeds.reference import seed_reference

TODAY = date(2026, 11, 1)


async def test_seed_idempotent(db_session: AsyncSession) -> None:
    first = await ensure_demo_user(db_session)
    second = await ensure_demo_user(db_session)
    assert first.id == second.id
    assert first.is_demo is True
    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.email == DEMO_EMAIL)
    )
    assert count == 1


async def test_demo_watches_seeded(db_session: AsyncSession) -> None:
    await seed_reference(db_session)
    demo = await ensure_demo_user(db_session)
    await ensure_demo_watches(db_session, demo, TODAY)
    await ensure_demo_watches(db_session, demo, TODAY)

    watches = (await db_session.scalars(select(Watch).where(Watch.user_id == demo.id))).unique()
    watches_list = list(watches)
    assert len(watches_list) == 3
    assert {w.status for w in watches_list} == {"active", "paused", "expired"}
    assert all(w.price_query.is_demo for w in watches_list)


async def test_demo_watches_visible(client: AsyncClient, db_session: AsyncSession) -> None:
    await seed_reference(db_session)
    demo = await ensure_demo_user(db_session)
    await ensure_demo_watches(db_session, demo, TODAY)
    token = (await client.post("/api/v1/auth/demo")).json()["access_token"]
    resp = await client.get("/api/v1/watches", headers={"Authorization": f"Bearer {token}"})
    assert len(resp.json()) == 3
