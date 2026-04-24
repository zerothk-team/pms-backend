"""seed_initial_data

Revision ID: a1b2c3d4e5f6
Revises: 056808cbd83f
Create Date: 2026-04-24 00:00:00.000000

Creates one demo organisation and one user per role for testing.

Test credentials
----------------
hr_admin@pms.test    / HrAdmin123!
executive@pms.test   / Executive123!
manager@pms.test     / Manager123!
employee@pms.test    / Employee123!
"""
from typing import Sequence, Union
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "056808cbd83f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Fixed UUIDs so re-running seed on a clean DB is deterministic
ORG_ID       = "00000000-0000-0000-0000-000000000001"
HR_ID        = "00000000-0000-0000-0000-000000000010"
EXEC_ID      = "00000000-0000-0000-0000-000000000020"
MANAGER_ID   = "00000000-0000-0000-0000-000000000030"
EMPLOYEE_ID  = "00000000-0000-0000-0000-000000000040"

NOW = datetime.now(timezone.utc)


def upgrade() -> None:
    conn = op.get_bind()

    # --- Organisation ---
    conn.execute(
        sa.text("""
            INSERT INTO organisations (id, name, slug, industry, size_band, is_active, created_at, updated_at)
            VALUES (:id, :name, :slug, :industry, :size_band, :is_active, :created_at, :updated_at)
            ON CONFLICT (id) DO NOTHING
        """),
        {
            "id": ORG_ID,
            "name": "Demo Organisation",
            "slug": "demo-org",
            "industry": "Technology",
            "size_band": "medium",
            "is_active": True,
            "created_at": NOW,
            "updated_at": NOW,
        },
    )

    # --- Users (one per role) ---
    users = [
        {
            "id": HR_ID,
            "email": "hr_admin@pms.test",
            "full_name": "HR Admin",
            "hashed_password": "$2b$12$eEVb6fquhecBE0A5QzSWs.0u94xhSVoHjHxqxZbtfZHxIcm8opBiu",
            "role": "hr_admin",
            "manager_id": None,
        },
        {
            "id": EXEC_ID,
            "email": "executive@pms.test",
            "full_name": "Executive User",
            "hashed_password": "$2b$12$BoQ/aNYpQzAPPmmpzK6w4OzGyEgEnkFucg4U79u2P1NQSkj2R96KS",
            "role": "executive",
            "manager_id": None,
        },
        {
            "id": MANAGER_ID,
            "email": "manager@pms.test",
            "full_name": "Manager User",
            "hashed_password": "$2b$12$hcsjcRoJVLfcGnNCbQqSPeHWpSLEkurLXdSmFRNYlVlJIOWl9AVk2",
            "role": "manager",
            "manager_id": HR_ID,
        },
        {
            "id": EMPLOYEE_ID,
            "email": "employee@pms.test",
            "full_name": "Employee User",
            "hashed_password": "$2b$12$BYUNKkfEsv1EHLlfz6m9Le6U7SjWIaE4soplOT.uinzs2WYFhAOTO",
            "role": "employee",
            "manager_id": MANAGER_ID,
        },
    ]

    for u in users:
        conn.execute(
            sa.text("""
                INSERT INTO users (
                    id, email, full_name, hashed_password, role,
                    is_active, is_verified, organisation_id, manager_id,
                    created_at, updated_at
                )
                VALUES (
                    :id, :email, :full_name, :hashed_password, :role,
                    :is_active, :is_verified, :organisation_id, :manager_id,
                    :created_at, :updated_at
                )
                ON CONFLICT (id) DO NOTHING
            """),
            {
                **u,
                "is_active": True,
                "is_verified": True,
                "organisation_id": ORG_ID,
                "created_at": NOW,
                "updated_at": NOW,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM users WHERE id IN (:hr, :exec, :mgr, :emp)"),
        {"hr": HR_ID, "exec": EXEC_ID, "mgr": MANAGER_ID, "emp": EMPLOYEE_ID},
    )
    conn.execute(
        sa.text("DELETE FROM organisations WHERE id = :id"),
        {"id": ORG_ID},
    )
