# PMS Backend

FastAPI-based backend for the Performance Management System (PMS).  
See [ARCHITECTURE.md](../ARCHITECTURE.md) for full system design reference.

---

## Quick Start

### Prerequisites

- Python 3.11+, PostgreSQL 15+, Redis 7+, Node 18+

### Backend Setup

```bash
cd pms-backend
cp .env.example .env       # edit DATABASE_URL, JWT_SECRET_KEY
docker-compose up -d db redis
python -m venv .venv && source .venv/bin/activate
pip install -e .
alembic upgrade head
uvicorn app.main:app --reload
```

### Frontend Setup

```bash
cd pms-frontend
npm install
npm run dev
```

### First Login

- Default HR Admin: `admin@company.com` / `changeme` (set in seed data)
- Change password on first login
- Create your org, KPI library, and first review cycle

---

## Features

### Core KPI Module

- **KPI Library** — Define KPIs with 6 measurement units, 6 frequencies, formula engine
- **Formula Variables** — Named variables in formulas, bound to ERP/HRMS/IoT or manual entry
- **External Data Adapters** — REST API, SQL database, InfluxDB, webhook push, CSV upload
- **Review Cycles** — Annual/quarterly/custom cycles with target-setting and scoring phases
- **Cascading Targets** — Org → Dept → Team → Individual with 3 distribution strategies
- **Per-KPI Scoring** — 5 built-in presets (Standard/Strict/Lenient/Binary/Sales) + custom
- **Scoring Engine** — Achievement%, weighted scores, composite rating, calibration sessions
- **Role-Based Dashboards** — Employee / Manager / Org views with real-time KPI heatmap
- **Notifications** — At-risk alerts, actuals reminders, period-close warnings

---

## Environment Variables (.env)

```env
# Database
DATABASE_URL=postgresql+asyncpg://pms_user:pms_pass@localhost:5432/pms_db

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
JWT_SECRET_KEY=your-very-long-random-string-here
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# CORS
CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]

# Integration secrets (referenced as {SECRET:KEY_NAME} in adapter configs)
# PMS_SECRET_ERP_API_TOKEN=your-erp-token
# PMS_SECRET_SALES_DB_CONN=postgresql://user:pass@erp-db:5432/sales
# PMS_SECRET_HRMS_KEY=your-hrms-api-key

# Debug (disable in production)
DEBUG=false
```

---

## Project Structure

- `app/` — Main application package (see [ARCHITECTURE.md](../ARCHITECTURE.md) for module map)
- `alembic/` — Database migrations
- `tests/` — pytest test suite (262 tests, asyncio mode)
- `docker-compose.yml` — PostgreSQL + Redis services
- `pyproject.toml` — Project dependencies

## Learn More

- [Architecture Reference](../ARCHITECTURE.md)
- [FastAPI Documentation](https://fastapi.tiangolo.com)
