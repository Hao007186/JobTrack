"""建立示範帳號，可重複執行：python -m app.seeds.demo"""

import asyncio
import secrets
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_sessionmaker
from app.modules.auth.security import hash_password
from app.modules.auth.service import DEMO_EMAIL, get_user_by_email
from app.modules.users.models import User


async def ensure_demo_user(session: AsyncSession) -> User:
    existing = await get_user_by_email(session, DEMO_EMAIL)
    if existing is not None:
        return existing
    # 密碼是不公開的隨機值，示範帳號只能走 POST /auth/demo
    user = User(
        email=DEMO_EMAIL,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        display_name="示範帳號",
        is_demo=True,
    )
    session.add(user)
    await session.commit()
    return user


async def _main() -> None:
    async with get_sessionmaker()() as session:
        user = await ensure_demo_user(session)
        print(f"示範帳號已就緒：{user.email}（public_id={user.public_id}）")


if __name__ == "__main__":
    # psycopg async 不支援 Windows 預設的 ProactorEventLoop
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(_main(), loop_factory=loop_factory)
