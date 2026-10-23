from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User
from app.modules.watches.models import Watch
from app.modules.watches.slots import count_user_slots, occupied_query_ids
from tests.conftest import create_user
from tests.watches.conftest import (
    TODAY,
    auth_headers,
    demo_headers,
    fill_slots,
    insert_watch,
)

URL = "/api/v1/watches"


def body(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "origin": "TPE",
        "destination": "NRT",
        "depart_date": (TODAY + timedelta(days=30)).isoformat(),
        "target_price": 9000,
    }
    data.update(overrides)
    return data


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


async def _alice(session: AsyncSession) -> User:
    user = await session.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    return user


async def test_create_success(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    resp = await client.post(URL, json=body(), headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "active"
    assert data["trip_type"] == "one_way"
    assert data["cabin"] == "economy"
    assert data["adults"] == 1
    assert data["airlines"] == []
    assert data["return_date"] is None
    assert data["target_price"] == 9000


async def test_create_round_trip(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    resp = await client.post(URL, json=body(return_date=day(35)), headers=headers)
    assert resp.status_code == 201
    assert resp.json()["trip_type"] == "round_trip"


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(3, 201), (330, 201), (2, 422), (331, 422)],
)
async def test_depart_date_window(
    client: AsyncClient, db_session: AsyncSession, offset: int, expected: int
) -> None:
    headers = await auth_headers(client, db_session)
    resp = await client.post(URL, json=body(depart_date=day(offset)), headers=headers)
    assert resp.status_code == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"return_date": day(29)},
        {"return_date": day(331)},
        {"origin": "NRT", "destination": "KIX"},
        {"destination": "TPE"},
        {"destination": "XXX"},
        {"airlines": ["ZZ"]},
        {"adults": 0},
        {"target_price": 0},
    ],
    ids=[
        "return-before-depart",
        "return-too-far",
        "origin-not-taiwan",
        "same-as-origin",
        "unknown-destination",
        "unknown-airline",
        "adults-0",
        "target-price-0",
    ],
)
async def test_invalid_conditions(
    client: AsyncClient, db_session: AsyncSession, overrides: dict[str, Any]
) -> None:
    headers = await auth_headers(client, db_session)
    resp = await client.post(URL, json=body(**overrides), headers=headers)
    assert resp.status_code == 422


async def test_lowercase_codes_normalized(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    lower = await client.post(
        URL,
        json=body(origin="tpe", destination="nrt", airlines=["ci", "BR", "CI"]),
        headers=headers,
    )
    assert lower.status_code == 201
    data = lower.json()
    assert (data["origin"], data["destination"], data["airlines"]) == ("TPE", "NRT", ["BR", "CI"])

    upper = await client.post(URL, json=body(airlines=["BR", "CI"]), headers=headers)
    query_ids = (await db_session.scalars(select(Watch.price_query_id))).all()
    assert upper.status_code == 201
    assert len(set(query_ids)) == 1


async def test_user_limit(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    created = []
    for dest in ["NRT", "KIX", "ICN"]:
        resp = await client.post(URL, json=body(destination=dest), headers=headers)
        created.append(resp.json()["public_id"])
    resp = await client.post(URL, json=body(destination="HKG"), headers=headers)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "每人最多 3 個追蹤"

    first = await db_session.scalar(select(Watch).where(Watch.public_id == created[0]))
    assert first is not None
    first.status = "paused"
    await db_session.flush()
    assert (
        await client.post(URL, json=body(destination="HKG"), headers=headers)
    ).status_code == 201


async def test_global_limit_queues(client: AsyncClient, db_session: AsyncSession) -> None:
    await fill_slots(db_session, 8)
    headers = await auth_headers(client, db_session)
    resp = await client.post(URL, json=body(destination="PUS"), headers=headers)
    assert resp.status_code == 201
    assert resp.json()["status"] == "queued"


async def test_same_conditions_share_slot(client: AsyncClient, db_session: AsyncSession) -> None:
    filled = await fill_slots(db_session, 7)
    owner_id = filled[0].user_id
    owner = await db_session.get(User, owner_id)
    assert owner is not None
    await insert_watch(db_session, owner)  # TPE→NRT TODAY+30，第 8 個名額
    headers = await auth_headers(client, db_session)

    resp = await client.post(URL, json=body(), headers=headers)
    assert resp.json()["status"] == "active"
    assert len(await occupied_query_ids(db_session, TODAY)) == 8


async def test_duplicate_watch_same_user(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await auth_headers(client, db_session)
    first = await client.post(URL, json=body(), headers=headers)
    second = await client.post(URL, json=body(target_price=8000), headers=headers)
    assert first.status_code == second.status_code == 201
    alice = await _alice(db_session)
    assert await count_user_slots(db_session, alice.id) == 2
    assert len(await occupied_query_ids(db_session, TODAY)) == 1


async def test_demo_cannot_create(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await demo_headers(client, db_session)
    assert (await client.post(URL, json=body(), headers=headers)).status_code == 403


async def test_requires_login(client: AsyncClient) -> None:
    assert (await client.post(URL, json=body())).status_code == 401


async def test_freed_slot_goes_to_earlier_queue(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # 跨日後某個 query 的出發日進入 2 天內、不再佔名額，但還沒有任何操作觸發補位
    await fill_slots(db_session, 7)
    early = await create_user(db_session, email="early@example.com")
    waiting = await insert_watch(db_session, early, status="queued", destination="PUS")
    headers = await auth_headers(client, db_session)

    resp = await client.post(URL, json=body(destination="GMP"), headers=headers)
    assert resp.json()["status"] == "queued"
    await db_session.refresh(waiting)
    assert waiting.status == "active"
