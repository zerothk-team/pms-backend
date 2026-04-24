import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_unknown_username_returns_401(async_client: AsyncClient) -> None:
    """Login with a non-existent username should return 401."""
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"username": "nobody", "password": "wrongpassword"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_register_creates_user_and_org(async_client: AsyncClient) -> None:
    """Registering with valid data should return 201 with access_token and user details."""
    response = await async_client.post(
        "/api/v1/auth/register",
        json={
            "user": {
                "username": "acmefounder",
                "email": "founder@acme.com",
                "full_name": "Acme Founder",
                "role": "hr_admin",
                "password": "securepass123",
            },
            "organisation": {
                "name": "Acme Corp",
                "slug": "acme-corp",
            },
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == "founder@acme.com"
    assert data["user"]["username"] == "acmefounder"
    assert data["token_type"] == "bearer"
