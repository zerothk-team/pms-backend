import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from app.actuals.router import router as actuals_router
from app.auth.router import router as auth_router
from app.config import settings
from app.dashboards.router import router as dashboards_router
from app.scoring.router import router as scoring_router
from app.scoring.kpi_scoring_router import router as kpi_scoring_router
from app.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorisedException,
    ValidationException,
    bad_request_handler,
    conflict_handler,
    forbidden_handler,
    not_found_handler,
    unauthorised_handler,
    validation_handler,
)
from app.kpis.router import router as kpis_router
from app.kpis.seeds import seed_kpi_templates
from app.middleware import LoggingMiddleware
from app.notifications.router import router as notifications_router
from app.organisations.router import router as organisations_router
from app.review_cycles.router import router as review_cycles_router
from app.targets.router import router as targets_router
from app.tasks.router import router as tasks_router
from app.users.router import router as users_router
from app.integrations.router import router as integrations_router

logging.basicConfig(level=logging.INFO)

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Return the application-level Redis connection. Raises if not initialised."""
    if _redis is None:
        raise RuntimeError("Redis connection not initialised")
    return _redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _redis
    _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    # Register pluggable data adapters
    from app.integrations.adapter_registry import register_builtin_adapters
    register_builtin_adapters()

    if settings.DEBUG:
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await seed_kpi_templates(db)
            from app.scoring.kpi_scoring_service import KPIScoringConfigService
            await KPIScoringConfigService().seed_system_presets(db)

    # Start background scheduler (disabled in test/debug to avoid noise)
    if not settings.DEBUG:
        from app.tasks.scheduler import start_scheduler
        start_scheduler(app)

    yield

    if not settings.DEBUG:
        from app.tasks.scheduler import stop_scheduler
        stop_scheduler(app)

    if _redis:
        await _redis.aclose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Performance Management System — KPI Backend API",
    docs_url=f"{settings.API_V1_PREFIX}/docs",
    redoc_url=f"{settings.API_V1_PREFIX}/redoc",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    lifespan=lifespan,
)

# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LoggingMiddleware)

# --- Exception handlers ---
app.add_exception_handler(NotFoundException, not_found_handler)
app.add_exception_handler(ConflictException, conflict_handler)
app.add_exception_handler(ForbiddenException, forbidden_handler)
app.add_exception_handler(UnauthorisedException, unauthorised_handler)
app.add_exception_handler(ValidationException, validation_handler)
app.add_exception_handler(BadRequestException, bad_request_handler)

# --- Routers ---
app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
app.include_router(users_router, prefix=settings.API_V1_PREFIX)
app.include_router(organisations_router, prefix=settings.API_V1_PREFIX)
app.include_router(kpis_router, prefix=settings.API_V1_PREFIX)
app.include_router(review_cycles_router, prefix=settings.API_V1_PREFIX)
app.include_router(targets_router, prefix=settings.API_V1_PREFIX)
app.include_router(actuals_router, prefix=settings.API_V1_PREFIX)
app.include_router(scoring_router, prefix=settings.API_V1_PREFIX)
app.include_router(kpi_scoring_router, prefix=settings.API_V1_PREFIX)
app.include_router(dashboards_router, prefix=settings.API_V1_PREFIX)
app.include_router(notifications_router, prefix=settings.API_V1_PREFIX)
app.include_router(tasks_router, prefix=settings.API_V1_PREFIX)
app.include_router(integrations_router, prefix=settings.API_V1_PREFIX)


# --- Health check ---
@app.get("/health", tags=["Health"])
async def health_check() -> dict:
    """Health check — pings the database and returns app version."""
    from sqlalchemy import text

    from app.database import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:
        db_status = f"error: {exc}"
    return {"status": "ok", "version": settings.APP_VERSION, "db": db_status}


# ---------------------------------------------------------------------------
# Custom OpenAPI schema — expose both OAuth2 password flow (username/password
# form in Swagger) AND a plain Bearer token field side-by-side in the
# Authorize dialog.
# ---------------------------------------------------------------------------
def _custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})

    # Add an explicit HTTP Bearer scheme so Swagger shows a "Value" token input
    # alongside the OAuth2 username/password form.
    schemes["BearerToken"] = {"type": "http", "scheme": "bearer"}

    # For every operation that already requires OAuth2PasswordBearer, also
    # accept BearerToken so the user can authenticate with either method.
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            sec = operation.get("security", [])
            has_oauth2 = any("OAuth2PasswordBearer" in s for s in sec)
            has_bearer = any("BearerToken" in s for s in sec)
            if has_oauth2 and not has_bearer:
                operation["security"].append({"BearerToken": []})

    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi  # type: ignore[method-assign]
