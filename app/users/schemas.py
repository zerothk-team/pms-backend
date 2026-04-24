import re
import uuid
from datetime import datetime
from typing import Annotated, Optional

from email_validator import EmailNotValidError
from email_validator import validate_email as _validate_email_lib
from pydantic import BaseModel, field_validator
from pydantic.functional_validators import AfterValidator

from app.users.models import UserRole


def _check_email(v: str) -> str:
    """Validate email format without checking domain deliverability."""
    try:
        return _validate_email_lib(v, check_deliverability=False).normalized
    except EmailNotValidError as e:
        raise ValueError(str(e))


EmailField = Annotated[str, AfterValidator(_check_email)]


class UserBase(BaseModel):
    username: str
    email: EmailField
    full_name: str
    role: UserRole

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_.\-]{3,50}$", v):
            raise ValueError("Username must be 3–50 characters: letters, digits, _ . - only")
        return v.lower()


class UserCreate(UserBase):
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    manager_id: Optional[uuid.UUID] = None


class UserRead(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    organisation_id: Optional[uuid.UUID] = None
    manager_id: Optional[uuid.UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserReadWithManager(UserRead):
    manager: Optional[UserRead] = None


class PaginatedUsers(BaseModel):
    items: list[UserRead]
    total: int
    page: int
    size: int
    pages: int
