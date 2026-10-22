from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_select_one(db_session: AsyncSession) -> None:
    assert (await db_session.execute(text("SELECT 1"))).scalar_one() == 1


# Neon pooler（PgBouncer transaction 模式）遇到 prepared statement 會出錯，本機 Postgres 不會重現
async def test_prepared_statements_disabled(db_session: AsyncSession) -> None:
    conn = await db_session.connection()
    raw = await conn.get_raw_connection()
    assert raw.driver_connection.prepare_threshold is None  # type: ignore[union-attr]


async def test_rollback_isolation_part1(db_session: AsyncSession) -> None:
    await db_session.execute(text("CREATE TABLE _iso_probe (id int)"))


async def test_rollback_isolation_part2(db_session: AsyncSession) -> None:
    exists = (await db_session.execute(text("SELECT to_regclass('_iso_probe')"))).scalar_one()
    assert exists is None
