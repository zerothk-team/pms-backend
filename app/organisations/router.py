from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user, require_roles
from app.organisations.schemas import OrganisationCreate, OrganisationRead, OrganisationUpdate
from app.organisations.service import organisation_service
from app.users.models import User

router = APIRouter(prefix="/organisations", tags=["Organisations"])


@router.post("/", response_model=OrganisationRead, status_code=status.HTTP_201_CREATED)
async def create_organisation(
    data: OrganisationCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("hr_admin"))],
) -> OrganisationRead:
    """Create a new organisation. Restricted to HR Admins."""
    org = await organisation_service.create(db, data)
    return OrganisationRead.model_validate(org)


@router.get("/", response_model=list[OrganisationRead])
async def list_organisations(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_active_user)],
) -> list[OrganisationRead]:
    """List all organisations."""
    orgs = await organisation_service.get_all(db)
    return [OrganisationRead.model_validate(o) for o in orgs]


@router.get("/{org_id}", response_model=OrganisationRead)
async def get_organisation(
    org_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_active_user)],
) -> OrganisationRead:
    """Get an organisation by ID."""
    org = await organisation_service.get_by_id(db, org_id)
    return OrganisationRead.model_validate(org)


@router.put("/{org_id}", response_model=OrganisationRead)
async def update_organisation(
    org_id: UUID,
    data: OrganisationUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_roles("hr_admin"))],
) -> OrganisationRead:
    """Update an organisation. Restricted to HR Admins."""
    org = await organisation_service.update(db, org_id, data)
    return OrganisationRead.model_validate(org)
