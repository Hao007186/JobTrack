"""把機場與航空公司 CSV 寫進 DB，可重複執行：python -m app.seeds.reference"""

import asyncio
import csv
import sys
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_sessionmaker
from app.modules.reference.models import Airline, Airport

DATA_DIR = Path(__file__).resolve().parent / "data"


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


async def seed_reference(session: AsyncSession, data_dir: Path = DATA_DIR) -> None:
    # 以 IATA 代碼 upsert；CSV 沒列到的列不刪除，可能已被 price_query 引用
    airports = _read(data_dir / "airports.csv")
    if airports:
        stmt = insert(Airport).values(airports)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Airport.iata],
                set_={
                    "name_zh": stmt.excluded.name_zh,
                    "city_zh": stmt.excluded.city_zh,
                    "country": stmt.excluded.country,
                },
            )
        )
    airlines = _read(data_dir / "airlines.csv")
    if airlines:
        stmt = insert(Airline).values(airlines)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Airline.iata], set_={"name_zh": stmt.excluded.name_zh}
            )
        )
    await session.commit()


async def _main() -> None:
    async with get_sessionmaker()() as session:
        await seed_reference(session)
    print(
        f"參考資料已就緒：機場 {len(_read(DATA_DIR / 'airports.csv'))} 筆、"
        f"航空公司 {len(_read(DATA_DIR / 'airlines.csv'))} 筆"
    )


if __name__ == "__main__":
    # psycopg async 不支援 Windows 預設的 ProactorEventLoop
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(_main(), loop_factory=loop_factory)
