# ── base: Python 3.12 slim + dependencies ──────────────────────────────────────
FROM python:3.12-slim AS base

WORKDIR /app

# Install system deps for asyncpg (libpq) and bcrypt
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# ── development: hot-reload for local work ─────────────────────────────────────
FROM base AS development

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── production: multi-worker, no reload ───────────────────────────────────────
FROM base AS production

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
