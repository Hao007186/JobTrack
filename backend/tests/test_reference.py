import csv
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reference.models import Airline, Airport
from app.seeds.reference import DATA_DIR, seed_reference


def _rows(name: str) -> int:
    with (DATA_DIR / name).open(encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


async def _count(session: AsyncSession, model: type[Airport] | type[Airline]) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_seed_idempotent(db_session: AsyncSession) -> None:
    await seed_reference(db_session)
    await seed_reference(db_session)
    assert await _count(db_session, Airport) == _rows("airports.csv")
    assert await _count(db_session, Airline) == _rows("airlines.csv")


async def test_seed_updates_names(db_session: AsyncSession, tmp_path: Path) -> None:
    await seed_reference(db_session)
    (tmp_path / "airports.csv").write_text(
        "iata,name_zh,city_zh,country\nTPE,舊名,舊城,TW\n", encoding="utf-8"
    )
    (tmp_path / "airlines.csv").write_text("iata,name_zh\nBR,舊航空\n", encoding="utf-8")
    await seed_reference(db_session, tmp_path)

    tpe = await db_session.scalar(
        select(Airport).where(Airport.iata == "TPE").execution_options(populate_existing=True)
    )
    assert tpe is not None
    assert tpe.name_zh == "舊名"
    # CSV 沒列到的不刪除（可能已被 price_query 引用）
    assert await _count(db_session, Airport) == _rows("airports.csv")


async def test_airports_endpoint(client: AsyncClient, db_session: AsyncSession) -> None:
    await seed_reference(db_session)
    resp = await client.get("/api/v1/airports")
    assert resp.status_code == 200
    airports = resp.json()
    by_iata = {a["iata"]: a for a in airports}
    assert by_iata["TPE"]["is_origin"] is True
    assert by_iata["TPE"]["name_zh"] == "桃園國際機場"
    assert by_iata["NRT"]["is_origin"] is False
    assert [a["iata"] for a in airports] == sorted(by_iata)


async def test_airlines_endpoint(client: AsyncClient, db_session: AsyncSession) -> None:
    await seed_reference(db_session)
    resp = await client.get("/api/v1/airlines")
    assert resp.status_code == 200
    airlines = resp.json()
    assert {a["iata"]: a["name_zh"] for a in airlines}["BR"] == "長榮航空"
    assert [a["iata"] for a in airlines] == sorted(a["iata"] for a in airlines)
