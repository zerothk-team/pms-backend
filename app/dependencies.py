from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.utils import decode_token
from app.database import get_db
from app.exceptions import ForbiddenException, UnauthorisedException
from app.users.models import User

# tokenUrl is the endpoint Swagger uses for the username/password form in the lock popup
security = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


async def get_current_user(
    token: Annotated[str, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Decode the Bearer JWT and return the corresponding User from the database."""
    payload = decode_token(token)
    user_id: str | None = payload.get("sub")
    if not user_id:
        raise UnauthorisedException("Invalid token payload")
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise UnauthorisedException("User not found")
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Assert that the authenticated user is active."""
    if not current_user.is_active:
        raise ForbiddenException("User account is inactive")
    return current_user


def require_roles(*roles: str):
    """Return a FastAPI dependency that enforces the user has one of the given roles."""

    async def role_checker(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> User:
        if current_user.role.value not in roles:
            raise ForbiddenException(
                f"Role '{current_user.role.value}' is not permitted for this action"
            )
        return current_user

    return role_checker
