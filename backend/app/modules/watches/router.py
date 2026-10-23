import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import get_today
from app.db.session import get_session
from app.modules.auth.deps import CurrentUser, WritableUser
from app.modules.watches import service
from app.modules.watches.models import WatchStatus
from app.modules.watches.schemas import WatchCreate, WatchOut, WatchUpdate

router = APIRouter(prefix="/watches", tags=["watches"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
TodayDep = Annotated[date, Depends(get_today)]


def _http_error(e: Exception) -> HTTPException:
    match e:
        case service.WatchNotFound():
            return HTTPException(status.HTTP_404_NOT_FOUND, "找不到追蹤")
        case service.WatchLimitReached():
            return HTTPException(status.HTTP_409_CONFLICT, "每人最多 3 個追蹤")
        case service.WatchExpired():
            return HTTPException(status.HTTP_409_CONFLICT, "已過期的追蹤不能修改")
        case service.InvalidWatchInput(message=message):
            return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)
    raise e


_ERRORS = (
    service.WatchNotFound,
    service.WatchLimitReached,
    service.WatchExpired,
    service.InvalidWatchInput,
)


@router.get("")
async def list_watches(
    user: CurrentUser,
    session: SessionDep,
    status_: Annotated[list[WatchStatus] | None, Query(alias="status")] = None,
) -> list[WatchOut]:
    watches = await service.list_watches(session, user, status_)
    return [WatchOut.from_watch(w) for w in watches]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_watch(
    body: WatchCreate, user: WritableUser, session: SessionDep, today: TodayDep
) -> WatchOut:
    try:
        watch = await service.create_watch(session, user, body, today)
    except _ERRORS as e:
        raise _http_error(e) from None
    return WatchOut.from_watch(watch)


@router.get("/{public_id}")
async def get_watch(public_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> WatchOut:
    try:
        watch = await service.get_watch(session, user, public_id)
    except _ERRORS as e:
        raise _http_error(e) from None
    return WatchOut.from_watch(watch)


@router.patch("/{public_id}")
async def update_watch(
    public_id: uuid.UUID,
    body: WatchUpdate,
    user: WritableUser,
    session: SessionDep,
    today: TodayDep,
) -> WatchOut:
    try:
        watch = await service.update_watch(session, user, public_id, body, today)
    except _ERRORS as e:
        raise _http_error(e) from None
    return WatchOut.from_watch(watch)


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watch(
    public_id: uuid.UUID, user: WritableUser, session: SessionDep, today: TodayDep
) -> Response:
    try:
        await service.delete_watch(session, user, public_id, today)
    except _ERRORS as e:
        raise _http_error(e) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
