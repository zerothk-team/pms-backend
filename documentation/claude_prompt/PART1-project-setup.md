# Copilot Prompt — Part 1: Project Setup & Architecture
> **Model**: Claude Sonnet 4.6 | **Stack**: FastAPI · PostgreSQL · SQLAlchemy · Alembic · Redis · JWT

---

## Context

You are building the **KPI module** of a Performance Management System (PMS). This is Part 1 of a multi-part build. Your job in this part is to scaffold the entire project structure, install dependencies, configure settings, set up the database connection, and wire up the FastAPI application factory.

The backend will be consumed by a React frontend (built separately). All endpoints must be REST, return JSON, and follow OpenAPI standards.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI (latest stable) |
| ORM | SQLAlchemy 2.x (async, with `asyncpg`) |
| Migrations | Alembic |
| Database | PostgreSQL 15+ |
| Cache / sessions | Redis (via `redis[asyncio]`) |
| Auth | JWT (access + refresh tokens via `python-jose`) |
| Password hashing | `passlib[bcrypt]` |
| Validation | Pydantic v2 |
| Settings | `pydantic-settings` (`.env` file) |
| CORS | FastAPI `CORSMiddleware` |
| Testing | `pytest` + `pytest-asyncio` + `httpx` |
| Linting | `ruff` |
| Container | Docker + `docker-compose.yml` |

---

## Project Directory Structure

Generate **exactly** this file/folder layout. Create all files even if they start empty (with a `# TODO` comment):

```
pms-backend/
├── alembic/
│   ├── env.py
│   └── versions/          # empty, migrations go here
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI app factory
│   ├── config.py          # Settings via pydantic-settings
│   ├── database.py        # Async SQLAlchemy engine + session
│   ├── dependencies.py    # Shared FastAPI dependencies (get_db, get_current_user)
│   ├── exceptions.py      # Custom exception classes + handlers
│   ├── middleware.py      # Request logging, timing middleware
│   │
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── router.py
│   │   ├── service.py
│   │   ├── schemas.py
│   │   └── utils.py       # JWT create/decode, password hash/verify
│   │
│   ├── users/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── router.py
│   │   ├── service.py
│   │   └── schemas.py
│   │
│   ├── organisations/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── router.py
│   │   ├── service.py
│   │   └── schemas.py
│   │
│   ├── kpis/              # Core KPI module — built in Part 2
│   │   └── __init__.py
│   │
│   ├── targets/           # Built in Part 3
│   │   └── __init__.py
│   │
│   ├── actuals/           # Built in Part 3
│   │   └── __init__.py
│   │
│   ├── scoring/           # Built in Part 4
│   │   └── __init__.py
│   │
│   └── notifications/     # Built in Part 5
│       └── __init__.py
│
├── tests/
│   ├── conftest.py
│   ├── test_auth.py
│   └── test_users.py
│
├── .env.example
├── .gitignore
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── README.md
```

---

## Files to Generate in Full

### 1. `pyproject.toml`

Use this exact dependency list:

```toml
[tool.poetry]
name = "pms-backend"
version = "0.1.0"
description = "Performance Management System — KPI Backend"
authors = ["Your Name"]
python = "^3.11"

[tool.poetry.dependencies]
fastapi = "^0.111.0"
uvicorn = {extras = ["standard"], version = "^0.29.0"}
sqlalchemy = {extras = ["asyncio"], version = "^2.0.0"}
asyncpg = "^0.29.0"
alembic = "^1.13.0"
pydantic = {extras = ["email"], version = "^2.7.0"}
pydantic-settings = "^2.2.0"
python-jose = {extras = ["cryptography"], version = "^3.3.0"}
passlib = {extras = ["bcrypt"], version = "^1.7.4"}
redis = {extras = ["asyncio"], version = "^5.0.0"}
python-multipart = "^0.0.9"
httpx = "^0.27.0"

[tool.poetry.dev-dependencies]
pytest = "^8.2.0"
pytest-asyncio = "^0.23.0"
ruff = "^0.4.0"

[tool.ruff]
line-length = 100
select = ["E", "F", "I"]
```

---

### 2. `app/config.py`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # App
    APP_NAME: str = "PMS KPI API"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str                     # async: postgresql+asyncpg://...
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS — comma-separated list
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Pagination
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
```

---

### 3. `app/database.py`

Generate a fully async SQLAlchemy 2.x setup:
- `create_async_engine` with pool settings from config
- `AsyncSession` factory using `async_sessionmaker`
- `Base = DeclarativeBase()` subclass — all models will inherit from this
- `get_db()` async generator dependency that yields a session and handles commit/rollback/close
- `init_db()` async function that creates all tables (for dev/testing only; production uses Alembic)

```python
# Full implementation expected — not a stub
```

---

### 4. `app/main.py`

- Create `app = FastAPI(...)` with title, version, description from settings
- Add `CORSMiddleware` using `settings.CORS_ORIGINS`
- Add request timing middleware from `app/middleware.py`
- Register all routers with the `API_V1_PREFIX` prefix:
  - `/auth` → auth router
  - `/users` → users router
  - `/organisations` → organisations router
  - (stub routes for kpis, targets, actuals, scoring — return 501 Not Implemented)
- Add a `GET /health` endpoint that returns `{"status": "ok", "version": "..."}` and also pings the DB
- Register custom exception handlers from `app/exceptions.py`
- On startup: initialise Redis connection pool

---

### 5. `app/exceptions.py`

Define these custom exceptions and their FastAPI handlers:

| Exception class | HTTP status | When used |
|---|---|---|
| `NotFoundException` | 404 | Resource not found |
| `ConflictException` | 409 | Duplicate record |
| `ForbiddenException` | 403 | Access denied |
| `UnauthorisedException` | 401 | Invalid/expired token |
| `ValidationException` | 422 | Business logic validation fail |
| `BadRequestException` | 400 | Malformed input |

Each handler must return: `{"detail": str, "code": str, "timestamp": ISO8601}`.

---

### 6. `app/middleware.py`

Create `LoggingMiddleware(BaseHTTPMiddleware)`:
- Log request: method, path, client IP
- Log response: status code, duration ms
- Use Python's `logging` module, structured as JSON strings
- Do not log request bodies (security)

---

### 7. `app/dependencies.py`

```python
async def get_db() -> AsyncSession: ...          # yields db session
async def get_current_user(...) -> User: ...     # decodes JWT, loads user from DB
async def get_current_active_user(...): ...      # asserts user.is_active
async def require_roles(*roles: str):            # returns dependency that checks user.role
```

---

### 8. Users Module — `app/users/models.py`

Generate a `User` SQLAlchemy model with these columns:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | `default=uuid4`, server_default for DB |
| `email` | String(255) | unique, indexed, not null |
| `full_name` | String(255) | not null |
| `hashed_password` | String(255) | not null |
| `role` | Enum | `hr_admin`, `executive`, `manager`, `employee` |
| `is_active` | Boolean | default True |
| `is_verified` | Boolean | default False |
| `organisation_id` | UUID FK | → `organisations.id`, nullable |
| `manager_id` | UUID FK | → `users.id` (self-ref), nullable |
| `created_at` | DateTime | UTC, server_default=now |
| `updated_at` | DateTime | UTC, auto-update on change |
| `last_login_at` | DateTime | nullable |

Add `__repr__` and `__tablename__ = "users"`. Add SQLAlchemy relationships: `organisation`, `manager`, `direct_reports`, `kpis` (back-populates from KPI model — use string reference for now).

---

### 9. Users Module — `app/users/schemas.py`

Using Pydantic v2, generate:

- `UserBase` — shared fields (email, full_name, role)
- `UserCreate` — extends base, adds `password` (min 8 chars, validated)
- `UserUpdate` — all optional fields (full_name, role, is_active, manager_id)
- `UserRead` — response schema (id, email, full_name, role, is_active, organisation_id, manager_id, created_at) — **no password**
- `UserReadWithManager` — extends `UserRead`, nests manager as `UserRead | None`
- `PaginatedUsers` — `{"items": list[UserRead], "total": int, "page": int, "size": int, "pages": int}`

---

### 10. Users Module — `app/users/service.py`

Async service class `UserService` with methods:
- `get_by_id(db, user_id) -> User`
- `get_by_email(db, email) -> User | None`
- `get_all(db, page, size, role_filter, org_id) -> PaginatedUsers`
- `create(db, data: UserCreate) -> User` — hashes password, checks duplicate email
- `update(db, user_id, data: UserUpdate) -> User`
- `deactivate(db, user_id) -> User`
- `update_last_login(db, user_id) -> None`

---

### 11. Users Module — `app/users/router.py`

```
POST   /users/               → create user (hr_admin only)
GET    /users/               → list users, paginated (manager, hr_admin, executive)
GET    /users/me             → get current user profile
PUT    /users/me             → update own profile (full_name only)
GET    /users/{user_id}      → get user by id (manager sees own team; hr_admin sees all)
PUT    /users/{user_id}      → update user (hr_admin only)
DELETE /users/{user_id}      → deactivate user (hr_admin only) — soft delete
GET    /users/{user_id}/direct-reports → list direct reports
```

---

### 12. Organisations Module — `app/organisations/models.py`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | String(255) | unique, not null |
| `slug` | String(100) | unique, url-safe |
| `industry` | String(100) | nullable |
| `size_band` | Enum | `1-10`, `11-50`, `51-200`, `201-500`, `500+` |
| `is_active` | Boolean | default True |
| `created_at` | DateTime | UTC |
| `updated_at` | DateTime | UTC |

---

### 13. Auth Module — `app/auth/utils.py`

- `hash_password(plain: str) -> str` — bcrypt
- `verify_password(plain: str, hashed: str) -> bool`
- `create_access_token(data: dict, expires_delta) -> str` — JWT HS256
- `create_refresh_token(data: dict) -> str`
- `decode_token(token: str) -> dict` — raises `UnauthorisedException` on invalid/expired

### 14. Auth Module — `app/auth/router.py`

```
POST /auth/register     → register new user + organisation
POST /auth/login        → returns access_token + refresh_token (set refresh in httpOnly cookie)
POST /auth/refresh      → rotate refresh token, return new access token
POST /auth/logout       → invalidate refresh token (blacklist in Redis)
POST /auth/verify-email → (stub for now)
```

---

### 15. `docker-compose.yml`

Services:
- `db`: `postgres:15-alpine`, port 5432, volume `pgdata`, env vars from `.env`
- `redis`: `redis:7-alpine`, port 6379
- `api`: builds from `Dockerfile`, port 8000, depends on `db` and `redis`, mounts `./app` for hot-reload

### 16. `Dockerfile`

Multi-stage:
1. `base` — python 3.11-slim, install poetry, copy pyproject.toml, install deps
2. `development` — copy source, run with `uvicorn --reload`
3. `production` — copy source, run with `uvicorn` (no reload, 4 workers)

### 17. `alembic.ini` + `alembic/env.py`

Configure Alembic for async SQLAlchemy:
- `sqlalchemy.url` reads from `settings.DATABASE_URL`
- `env.py` uses `run_async_migrations()` pattern with `AsyncEngine`
- Import `Base` from `app.database` so Alembic can autogenerate migrations from models

### 18. `.env.example`

```env
DATABASE_URL=postgresql+asyncpg://pms_user:pms_pass@localhost:5432/pms_db
REDIS_URL=redis://localhost:6379/0
JWT_SECRET_KEY=change-me-to-a-long-random-string
DEBUG=true
CORS_ORIGINS=["http://localhost:3000"]
```

### 19. `tests/conftest.py`

- Async pytest fixtures: `async_client` (uses `httpx.AsyncClient` with `app`), `db_session` (uses test DB / in-memory SQLite for speed), `test_user` (pre-seeded user)
- Override `get_db` dependency to use test session
- Auto-create all tables before tests, drop after

---

## Coding Standards to Follow Throughout

1. **All DB calls must be async** — use `await session.execute(select(...))`, never sync queries.
2. **Services never import routers; routers never import each other.**
3. **Never return SQLAlchemy model objects directly from routers** — always serialize to Pydantic schemas.
4. **Use `Annotated` dependencies** in router function signatures: `current_user: Annotated[User, Depends(get_current_active_user)]`.
5. **All UUIDs as `uuid.UUID` Python type**, not strings, in Pydantic schemas.
6. **All datetimes as UTC `datetime`**, use `datetime.now(timezone.utc)`.
7. **Passwords never logged, never returned in any schema.**
8. **HTTP 201 for POST creates, 200 for updates, 204 for deletes.**
9. **Paginated endpoints always accept `page: int = 1` and `size: int = Query(20, le=100)`**.
10. **Every router function has a docstring** used as the OpenAPI operation description.

---

## What to Build Next (Do NOT build these yet)

- Part 2: KPI definition, library, formula engine, categorisation
- Part 3: Target setting, cascading, actuals / data entry
- Part 4: Scoring engine, period management, calibration
- Part 5: Alerts, notifications, dashboards/reporting endpoints