"""add_username_to_users

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-24 00:00:00.000000

Adds a unique, indexed `username` column to the users table.
Existing seed users are backfilled with their well-known usernames;
any other existing rows get a username derived from the local part of
their email address (with a numeric suffix if there is a clash).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Known seed-user IDs → usernames (deterministic backfill)
_SEED_USERNAMES = {
    "00000000-0000-0000-0000-000000000010": "hr_admin",
    "00000000-0000-0000-0000-000000000020": "executive",
    "00000000-0000-0000-0000-000000000030": "manager",
    "00000000-0000-0000-0000-000000000040": "employee",
}


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add column as nullable so existing rows don't immediately violate NOT NULL
    op.add_column("users", sa.Column("username", sa.String(100), nullable=True))

    # 2. Backfill known seed users with their canonical usernames
    for uid, uname in _SEED_USERNAMES.items():
        conn.execute(
            sa.text("UPDATE users SET username = :username WHERE id = :id"),
            {"username": uname, "id": uid},
        )

    # 3. Derive username from email local-part for any remaining rows
    #    Use split_part (PostgreSQL) and a counter suffix for duplicates.
    conn.execute(
        sa.text("""
            UPDATE users
            SET username = split_part(email, '@', 1)
            WHERE username IS NULL
        """)
    )
    # Resolve collisions: append _2, _3 … for duplicate derived usernames
    conn.execute(
        sa.text("""
            WITH ranked AS (
                SELECT id,
                       username,
                       ROW_NUMBER() OVER (PARTITION BY username ORDER BY created_at) AS rn
                FROM users
            )
            UPDATE users
            SET username = ranked.username || '_' || ranked.rn
            FROM ranked
            WHERE users.id = ranked.id
              AND ranked.rn > 1
        """)
    )

    # 4. Now enforce NOT NULL, UNIQUE, and create index
    op.alter_column("users", "username", nullable=False)
    op.create_unique_constraint("uq_users_username", "users", ["username"])
    op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_constraint("uq_users_username", "users", type_="unique")
    op.drop_column("users", "username")
