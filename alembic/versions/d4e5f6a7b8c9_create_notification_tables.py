"""create_notification_tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-25 00:00:00.000000

Creates all tables required for Part 5 — Notifications & Background Tasks:

    notifications                — per-user notification inbox
    notification_preferences     — per-user channel preferences

New PostgreSQL enum types created:
    notificationtype     — kpi_at_risk | team_kpi_at_risk | actual_entry_due |
                           target_acknowledgement_due | period_closing_soon |
                           approval_pending | target_achieved |
                           stretch_target_achieved | scoring_complete |
                           calibration_required | score_finalised | score_adjusted
    notificationchannel  — in_app | email
    notificationstatus   — unread | read | dismissed

Indexes added:
    ix_notif_recipient_status    (recipient_id, status)
    ix_notif_recipient_created   (recipient_id, created_at)
    ix_notif_organisation        (organisation_id)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enum types ---------------------------------------------------------
    notificationtype = postgresql.ENUM(
        "kpi_at_risk",
        "team_kpi_at_risk",
        "actual_entry_due",
        "target_acknowledgement_due",
        "period_closing_soon",
        "approval_pending",
        "target_achieved",
        "stretch_target_achieved",
        "scoring_complete",
        "calibration_required",
        "score_finalised",
        "score_adjusted",
        name="notificationtype",
    )
    notificationtype.create(op.get_bind(), checkfirst=True)

    notificationchannel = postgresql.ENUM(
        "in_app",
        "email",
        name="notificationchannel",
    )
    notificationchannel.create(op.get_bind(), checkfirst=True)

    notificationstatus = postgresql.ENUM(
        "unread",
        "read",
        "dismissed",
        name="notificationstatus",
    )
    notificationstatus.create(op.get_bind(), checkfirst=True)

    # --- notifications -------------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "notification_type",
            postgresql.ENUM(
                "kpi_at_risk", "team_kpi_at_risk", "actual_entry_due",
                "target_acknowledgement_due", "period_closing_soon",
                "approval_pending", "target_achieved", "stretch_target_achieved",
                "scoring_complete", "calibration_required", "score_finalised",
                "score_adjusted",
                name="notificationtype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "channel",
            postgresql.ENUM("in_app", "email", name="notificationchannel", create_type=False),
            nullable=False,
            server_default="in_app",
        ),
        sa.Column(
            "status",
            postgresql.ENUM("unread", "read", "dismissed", name="notificationstatus", create_type=False),
            nullable=False,
            server_default="unread",
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("action_url", sa.String(500), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"], ["organisations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notif_recipient_status",
        "notifications",
        ["recipient_id", "status"],
    )
    op.create_index(
        "ix_notif_recipient_created",
        "notifications",
        ["recipient_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_notif_organisation",
        "notifications",
        ["organisation_id"],
    )

    # --- notification_preferences --------------------------------------------
    op.create_table(
        "notification_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kpi_at_risk_in_app", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("kpi_at_risk_email", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("actual_due_in_app", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("actual_due_email", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("target_achieved_in_app", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("target_achieved_email", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("period_closing_in_app", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("period_closing_email", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("score_finalised_in_app", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("score_finalised_email", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("score_adjusted_in_app", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("score_adjusted_email", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("period_closing_days_before", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("email_digest_frequency", sa.String(20), nullable=False, server_default="immediate"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organisation_id"], ["organisations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_notification_preferences_user"),
    )


def downgrade() -> None:
    op.drop_table("notification_preferences")
    op.drop_index("ix_notif_organisation", table_name="notifications")
    op.drop_index("ix_notif_recipient_created", table_name="notifications")
    op.drop_index("ix_notif_recipient_status", table_name="notifications")
    op.drop_table("notifications")

    op.execute("DROP TYPE IF EXISTS notificationstatus")
    op.execute("DROP TYPE IF EXISTS notificationchannel")
    op.execute("DROP TYPE IF EXISTS notificationtype")
