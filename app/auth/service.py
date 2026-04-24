from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import LoginRequest, RegisterRequest, RegisterResponse, TokenResponse
from app.auth.utils import create_access_token, create_refresh_token, decode_token, verify_password
from app.config import settings
from app.exceptions import UnauthorisedException
from app.organisations.service import organisation_service
from app.users.schemas import UserRead
from app.users.service import user_service


class AuthService:
    async def register(self, db: AsyncSession, data: RegisterRequest) -> RegisterResponse:
        """Register a new organisation and its first user together."""
        org = await organisation_service.create(db, data.organisation)
        user = await user_service.create(db, data.user)
        user.organisation_id = org.id
        await db.flush()
        await db.refresh(user)
        access_token = create_access_token({"sub": str(user.id)})
        return RegisterResponse(user=UserRead.model_validate(user), access_token=access_token)

    async def login(self, db: AsyncSession, data: LoginRequest) -> tuple[str, str]:
        """Authenticate credentials and return (access_token, refresh_token)."""
        user = await user_service.get_by_username(db, data.username)
        if not user or not verify_password(data.password, user.hashed_password):
            raise UnauthorisedException("Invalid username or password")
        if not user.is_active:
            raise UnauthorisedException("User account is inactive")
        await user_service.update_last_login(db, user.id)
        access_token = create_access_token({"sub": str(user.id)})
        refresh_token = create_refresh_token({"sub": str(user.id)})
        return access_token, refresh_token

    async def refresh(self, refresh_token: str) -> str:
        """Validate a refresh token and return a new access token."""
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise UnauthorisedException("Invalid token type")
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            is_blacklisted = await redis_client.get(f"blacklist:{refresh_token}")
        finally:
            await redis_client.aclose()
        if is_blacklisted:
            raise UnauthorisedException("Token has been revoked")
        user_id = payload.get("sub")
        return create_access_token({"sub": user_id})

    async def logout(self, refresh_token: str) -> None:
        """Blacklist the refresh token in Redis so it cannot be reused."""
        try:
            payload = decode_token(refresh_token)
            exp = payload.get("exp", 0)
            ttl = max(0, exp - int(datetime.now(timezone.utc).timestamp()))
        except Exception:
            ttl = 60 * 60 * 24 * 7  # default 7 days TTL
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            await redis_client.setex(f"blacklist:{refresh_token}", ttl, "1")
        finally:
            await redis_client.aclose()


auth_service = AuthService()
