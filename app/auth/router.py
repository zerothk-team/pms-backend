from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)
from app.auth.service import auth_service
from app.database import get_db

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RegisterResponse:
    """Register a new user together with their organisation."""
    return await auth_service.register(db, data)


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Authenticate and return an access token. Sets the refresh token as an httpOnly cookie."""
    access_token, refresh_token = await auth_service.login(db, data)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,  # Set True in production (HTTPS only)
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    refresh_token: Annotated[str | None, Cookie()] = None,
    body: RefreshRequest | None = None,
) -> TokenResponse:
    """Rotate the refresh token and return a new access token."""
    from app.exceptions import UnauthorisedException

    token = refresh_token or (body.refresh_token if body else None)
    if not token:
        raise UnauthorisedException("No refresh token provided")
    access_token = await auth_service.refresh(token)
    return TokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
    body: RefreshRequest | None = None,
) -> None:
    """Invalidate the refresh token and clear the cookie."""
    token = refresh_token or (body.refresh_token if body else None)
    if token:
        await auth_service.logout(token)
    response.delete_cookie("refresh_token")


@router.post("/token", response_model=TokenResponse, include_in_schema=False)
async def token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """OAuth2 password-flow endpoint consumed by Swagger UI's Authorize dialog."""
    access_token, refresh_token = await auth_service.login(
        db, LoginRequest(username=form.username, password=form.password)
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )
    return TokenResponse(access_token=access_token)


@router.post("/verify-email", status_code=status.HTTP_200_OK)
async def verify_email() -> dict:
    """Verify a user's email address. (Stub — not yet implemented.)"""
    # TODO: implement email verification flow in a future part
    return {"detail": "Email verification not yet implemented"}
