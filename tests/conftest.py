import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.utils import hash_password
from app.database import Base, get_db
from app.main import app
from app.users.models import User, UserRole

# Named shared-memory SQLite: the "file:..." URI form lets multiple connections
# see the same in-memory database as long as at least one connection is open.
# This avoids the cross-event-loop isolation problem that occurs with
# "sqlite+aiosqlite:///:memory:" and StaticPool.
TEST_DATABASE_URL = (
    "sqlite+aiosqlite:///file:test_pms_db?mode=memory&cache=shared&uri=true"
)

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        username="testuser",
        email="testuser@example.com",
        full_name="Test User",
        role=UserRole.hr_admin,
        hashed_password=hash_password("password123"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user
