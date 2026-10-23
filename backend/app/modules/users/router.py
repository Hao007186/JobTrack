from fastapi import APIRouter

from app.modules.auth.deps import CurrentUser
from app.modules.users.schemas import UserOut

router = APIRouter(tags=["users"])


@router.get("/me")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
