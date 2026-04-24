import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictException, NotFoundException
from app.organisations.models import Organisation
from app.organisations.schemas import OrganisationCreate, OrganisationUpdate


class OrganisationService:
    async def get_by_id(self, db: AsyncSession, org_id: uuid.UUID) -> Organisation:
        """Fetch a single organisation by primary key, raising 404 if not found."""
        result = await db.execute(select(Organisation).where(Organisation.id == org_id))
        org = result.scalar_one_or_none()
        if not org:
            raise NotFoundException(f"Organisation {org_id} not found")
        return org

    async def get_all(self, db: AsyncSession) -> list[Organisation]:
        """Return all organisations."""
        result = await db.execute(select(Organisation))
        return list(result.scalars().all())

    async def create(self, db: AsyncSession, data: OrganisationCreate) -> Organisation:
        """Create a new organisation after checking for name/slug conflicts."""
        existing = await db.execute(
            select(Organisation).where(
                (Organisation.name == data.name) | (Organisation.slug == data.slug)
            )
        )
        if existing.scalar_one_or_none():
            raise ConflictException("Organisation with this name or slug already exists")
        org = Organisation(**data.model_dump())
        db.add(org)
        await db.flush()
        await db.refresh(org)
        return org

    async def update(
        self, db: AsyncSession, org_id: uuid.UUID, data: OrganisationUpdate
    ) -> Organisation:
        """Apply partial updates to an organisation record."""
        org = await self.get_by_id(db, org_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(org, field, value)
        await db.flush()
        await db.refresh(org)
        return org


organisation_service = OrganisationService()
