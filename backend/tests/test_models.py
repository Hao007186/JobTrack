import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import RefreshToken
from app.modules.users.models import User


async def test_user_defaults(db_session: AsyncSession) -> None:
    user = User(email="alice@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    assert isinstance(user.public_id, uuid.UUID)
    assert user.role == "user"
    assert user.is_demo is False
    assert user.is_active is True
    assert user.failed_login_count == 0
    assert user.locked_until is None
    assert user.created_at is not None


async def test_email_unique(db_session: AsyncSession) -> None:
    db_session.add(User(email="dup@example.com", password_hash="x"))
    await db_session.flush()
    db_session.add(User(email="dup@example.com", password_hash="x"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_role_check(db_session: AsyncSession) -> None:
    db_session.add(User(email="root@example.com", password_hash="x", role="root"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_refresh_tokens_cascade(db_session: AsyncSession) -> None:
    user = User(email="bob@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        RefreshToken(
            user_id=user.id,
            token_hash="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )
    await db_session.flush()
    await db_session.delete(user)
    await db_session.flush()
    db_session.expunge_all()
    assert (await db_session.scalars(select(RefreshToken))).all() == []
