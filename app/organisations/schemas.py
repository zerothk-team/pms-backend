import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.organisations.models import SizeBand


class OrganisationBase(BaseModel):
    name: str
    slug: str
    industry: Optional[str] = None
    size_band: Optional[SizeBand] = None


class OrganisationCreate(OrganisationBase):
    pass


class OrganisationUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    industry: Optional[str] = None
    size_band: Optional[SizeBand] = None
    is_active: Optional[bool] = None


class OrganisationRead(OrganisationBase):
    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
