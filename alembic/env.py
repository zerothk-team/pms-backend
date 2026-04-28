import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# -- App imports --
from app.config import settings
from app.database import Base  # noqa: F401 — registers Base.metadata

# Import all models so Alembic can detect them for autogenerate
import app.users.models  # noqa: F401
import app.organisations.models  # noqa: F401
import app.kpis.models  # noqa: F401
import app.review_cycles.models  # noqa: F401
import app.targets.models  # noqa: F401
import app.actuals.models  # noqa: F401
import app.scoring.models  # noqa: F401
import app.scoring.kpi_scoring_model  # noqa: F401
import app.notifications.models  # noqa: F401
import app.integrations.models  # noqa: F401

config = context.config

# Override the URL from settings (reads .env)
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without an active DB connection (SQL script output)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations against a live async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
