from pydantic import BaseModel

from app.organisations.schemas import OrganisationCreate
from app.users.schemas import UserCreate, UserRead


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class RegisterRequest(BaseModel):
    user: UserCreate
    organisation: OrganisationCreate


class RegisterResponse(BaseModel):
    user: UserRead
    access_token: str
    token_type: str = "bearer"
