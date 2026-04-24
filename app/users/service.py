import math
import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.utils import hash_password
from app.exceptions import ConflictException, NotFoundException
from app.users.models import User, UserRole
from app.users.schemas import PaginatedUsers, UserCreate, UserRead, UserUpdate


class UserService:
    async def get_by_id(self, db: AsyncSession, user_id: uuid.UUID) -> User:
        """Fetch a single user by primary key, raising 404 if not found."""
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundException(f"User {user_id} not found")
        return user

    async def get_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        """Fetch a user by email address, returning None if not found."""
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_username(self, db: AsyncSession, username: str) -> Optional[User]:
        """Fetch a user by username, returning None if not found."""
        result = await db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_all(
        self,
        db: AsyncSession,
        page: int = 1,
        size: int = 20,
        role_filter: Optional[UserRole] = None,
        org_id: Optional[uuid.UUID] = None,
    ) -> PaginatedUsers:
        """Return a paginated, optionally filtered list of users."""
        query = select(User)
        if role_filter:
            query = query.where(User.role == role_filter)
        if org_id:
            query = query.where(User.organisation_id == org_id)

        count_result = await db.execute(select(func.count()).select_from(query.subquery()))
        total = count_result.scalar_one()

        offset = (page - 1) * size
        result = await db.execute(query.offset(offset).limit(size))
        users = result.scalars().all()

        return PaginatedUsers(
            items=[UserRead.model_validate(u) for u in users],
            total=total,
            page=page,
            size=size,
            pages=math.ceil(total / size) if total > 0 else 0,
        )

    async def create(self, db: AsyncSession, data: UserCreate) -> User:
        """Create a new user after verifying the email and username are not already taken."""
        if await self.get_by_email(db, data.email):
            raise ConflictException(f"Email '{data.email}' is already registered")
        if await self.get_by_username(db, data.username):
            raise ConflictException(f"Username '{data.username}' is already taken")
        user = User(
            username=data.username,
            email=data.email,
            full_name=data.full_name,
            role=data.role,
            hashed_password=hash_password(data.password),
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user

    async def update(self, db: AsyncSession, user_id: uuid.UUID, data: UserUpdate) -> User:
        """Apply partial updates to a user record."""
        user = await self.get_by_id(db, user_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(user, field, value)
        await db.flush()
        await db.refresh(user)
        return user

    async def deactivate(self, db: AsyncSession, user_id: uuid.UUID) -> User:
        """Soft-delete a user by setting is_active to False."""
        user = await self.get_by_id(db, user_id)
        user.is_active = False
        await db.flush()
        await db.refresh(user)
        return user

    async def update_last_login(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        """Record the timestamp of the most recent successful login."""
        from datetime import datetime, timezone

        user = await self.get_by_id(db, user_id)
        user.last_login_at = datetime.now(timezone.utc)
        await db.flush()


user_service = UserService()
