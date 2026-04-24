import pytest
from httpx import AsyncClient

from app.auth.utils import create_access_token


@pytest.mark.asyncio
async def test_get_me_without_token_returns_401(async_client: AsyncClient) -> None:
    """Accessing /users/me without an Authorization header should return 401."""
    response = await async_client.get("/api/v1/users/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me_with_valid_token(async_client: AsyncClient, test_user) -> None:
    """An authenticated user should be able to retrieve their own profile."""
    token = create_access_token({"sub": str(test_user.id)})
    response = await async_client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_user.email
    assert "hashed_password" not in data
