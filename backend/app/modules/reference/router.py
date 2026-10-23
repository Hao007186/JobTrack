from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.reference.models import ORIGIN_COUNTRY, Airline, Airport
from app.modules.reference.schemas import AirlineOut, AirportOut

router = APIRouter(tags=["reference"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


# 清單很小，一次回傳全部，由前端篩選；不需登入
@router.get("/airports")
async def list_airports(session: SessionDep) -> list[AirportOut]:
    airports = await session.scalars(select(Airport).order_by(Airport.iata))
    return [
        AirportOut(
            iata=a.iata,
            name_zh=a.name_zh,
            city_zh=a.city_zh,
            country=a.country,
            is_origin=a.country == ORIGIN_COUNTRY,
        )
        for a in airports
    ]


@router.get("/airlines")
async def list_airlines(session: SessionDep) -> list[AirlineOut]:
    airlines = await session.scalars(select(Airline).order_by(Airline.iata))
    return [AirlineOut(iata=a.iata, name_zh=a.name_zh) for a in airlines]
