from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user, require_roles
from app.users.models import User, UserRole
from app.users.schemas import PaginatedUsers, UserCreate, UserRead, UserReadWithManager, UserUpdate
from app.users.service import user_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("hr_admin"))],
) -> UserRead:
    """Create a new user. Restricted to HR Admins."""
    user = await user_service.create(db, data)
    return UserRead.model_validate(user)


@router.get("/", response_model=PaginatedUsers)
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("manager", "hr_admin", "executive"))],
    page: int = 1,
    size: int = Query(20, le=100),
    role: UserRole | None = None,
    org_id: UUID | None = None,
) -> PaginatedUsers:
    """List users with pagination. Accessible by managers, HR admins, and executives."""
    return await user_service.get_all(db, page=page, size=size, role_filter=role, org_id=org_id)


@router.get("/me", response_model=UserRead)
async def get_me(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserRead:
    """Get the current authenticated user's profile."""
    return UserRead.model_validate(current_user)


@router.put("/me", response_model=UserRead)
async def update_me(
    data: UserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserRead:
    """Update own profile. Only full_name may be changed via this endpoint."""
    safe_data = UserUpdate(full_name=data.full_name)
    user = await user_service.update(db, current_user.id, safe_data)
    return UserRead.model_validate(user)


@router.get("/{user_id}", response_model=UserReadWithManager)
async def get_user(
    user_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserReadWithManager:
    """Get a user by ID. Managers may only view their own team; HR admins see all."""
    from app.exceptions import ForbiddenException

    user = await user_service.get_by_id(db, user_id)
    if current_user.role == UserRole.manager and user.id != current_user.id:
        if user.manager_id != current_user.id:
            raise ForbiddenException("You can only view users in your team")
    return UserReadWithManager.model_validate(user)


@router.put("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: UUID,
    data: UserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("hr_admin"))],
) -> UserRead:
    """Update a user by ID. Restricted to HR Admins."""
    user = await user_service.update(db, user_id, data)
    return UserRead.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("hr_admin"))],
) -> None:
    """Deactivate (soft-delete) a user. Restricted to HR Admins."""
    await user_service.deactivate(db, user_id)


@router.get("/{user_id}/direct-reports", response_model=list[UserRead])
async def get_direct_reports(
    user_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_active_user)],
) -> list[UserRead]:
    """List all direct reports for the specified user."""
    from sqlalchemy import select

    result = await db.execute(select(User).where(User.manager_id == user_id))
    users = result.scalars().all()
    return [UserRead.model_validate(u) for u in users]
