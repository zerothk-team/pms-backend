"""create_scoring_tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-01 00:00:00.000000

Creates all tables required for Part 4 – Scoring Engine & Dashboards:

    score_configs          — per-org per-cycle rating thresholds
    performance_scores     — per-user per-KPI per-cycle individual scores
    composite_scores       — per-user per-cycle overall weighted average
    score_adjustments      — immutable audit trail for every score change
    calibration_sessions   — group calibration exercises (HR admin)

New PostgreSQL enum types created:
    ratinglabel        — exceptional | exceeds_expectations | meets_expectations
                          | partially_meets | does_not_meet | not_rated
    scorestatus        — computed | manager_reviewed | adjusted | calibrated
                          | final | appealed
    calibrationstatus  — open | in_progress | completed | locked
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enum types ---------------------------------------------------------
    ratinglabel = postgresql.ENUM(
        "exceptional",
        "exceeds_expectations",
        "meets_expectations",
        "partially_meets",
        "does_not_meet",
        "not_rated",
        name="ratinglabel",
    )
    ratinglabel.create(op.get_bind(), checkfirst=True)

    scorestatus = postgresql.ENUM(
        "computed",
        "manager_reviewed",
        "adjusted",
        "calibrated",
        "final",
        "appealed",
        name="scorestatus",
    )
    scorestatus.create(op.get_bind(), checkfirst=True)

    calibrationstatus = postgresql.ENUM(
        "open",
        "in_progress",
        "completed",
        "locked",
        name="calibrationstatus",
    )
    calibrationstatus.create(op.get_bind(), checkfirst=True)

    # --- score_configs -------------------------------------------------------
    op.create_table(
        "score_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exceptional_min", sa.Numeric(precision=6, scale=2), nullable=False, server_default="120.00"),
        sa.Column("exceeds_min", sa.Numeric(precision=6, scale=2), nullable=False, server_default="100.00"),
        sa.Column("meets_min", sa.Numeric(precision=6, scale=2), nullable=False, server_default="80.00"),
        sa.Column("partially_meets_min", sa.Numeric(precision=6, scale=2), nullable=False, server_default="60.00"),
        sa.Column("does_not_meet_min", sa.Numeric(precision=6, scale=2), nullable=False, server_default="0.00"),
        sa.Column("allow_manager_adjustment", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("max_adjustment_points", sa.Numeric(precision=5, scale=2), nullable=False, server_default="10.00"),
        sa.Column("requires_calibration", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["review_cycle_id"], ["review_cycles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "review_cycle_id", name="uq_score_config_org_cycle"),
    )

    # --- performance_scores --------------------------------------------------
    op.create_table(
        "performance_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kpi_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("achievement_percentage", sa.Numeric(precision=8, scale=4), nullable=False, server_default="0.0000"),
        sa.Column("weighted_score", sa.Numeric(precision=8, scale=4), nullable=False, server_default="0.0000"),
        sa.Column("computed_score", sa.Numeric(precision=8, scale=4), nullable=False, server_default="0.0000"),
        sa.Column("adjusted_score", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("final_score", sa.Numeric(precision=8, scale=4), nullable=False, server_default="0.0000"),
        sa.Column(
            "rating",
            sa.Enum(
                "exceptional", "exceeds_expectations", "meets_expectations",
                "partially_meets", "does_not_meet", "not_rated",
                name="ratinglabel",
                create_type=False,
            ),
            nullable=False,
            server_default="not_rated",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "computed", "manager_reviewed", "adjusted", "calibrated",
                "final", "appealed",
                name="scorestatus",
                create_type=False,
            ),
            nullable=False,
            server_default="computed",
        ),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["target_id"], ["kpi_targets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kpi_id"], ["kpis.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["review_cycle_id"], ["review_cycles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_id", "review_cycle_id", name="uq_perf_score_target_cycle"),
    )
    op.create_index("ix_perf_score_user_cycle", "performance_scores", ["user_id", "review_cycle_id"])
    op.create_index("ix_perf_score_kpi_cycle", "performance_scores", ["kpi_id", "review_cycle_id"])
    op.create_index("ix_perf_score_status", "performance_scores", ["status"])

    # --- composite_scores ----------------------------------------------------
    op.create_table(
        "composite_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("weighted_average", sa.Numeric(precision=8, scale=4), nullable=False, server_default="0.0000"),
        sa.Column("final_weighted_average", sa.Numeric(precision=8, scale=4), nullable=False, server_default="0.0000"),
        sa.Column(
            "rating",
            sa.Enum(
                "exceptional", "exceeds_expectations", "meets_expectations",
                "partially_meets", "does_not_meet", "not_rated",
                name="ratinglabel",
                create_type=False,
            ),
            nullable=False,
            server_default="not_rated",
        ),
        sa.Column("kpi_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("kpis_with_actuals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.Enum(
                "computed", "manager_reviewed", "adjusted", "calibrated",
                "final", "appealed",
                name="scorestatus",
                create_type=False,
            ),
            nullable=False,
            server_default="computed",
        ),
        sa.Column("manager_comment", sa.Text(), nullable=True),
        sa.Column("calibration_note", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["review_cycle_id"], ["review_cycles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "review_cycle_id", name="uq_composite_user_cycle"),
    )
    op.create_index("ix_composite_score_org_cycle", "composite_scores", ["organisation_id", "review_cycle_id"])
    op.create_index("ix_composite_score_status", "composite_scores", ["status"])

    # --- score_adjustments ---------------------------------------------------
    op.create_table(
        "score_adjustments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("composite_score_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("adjusted_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("before_value", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("after_value", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("adjustment_type", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["score_id"], ["performance_scores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["composite_score_id"], ["composite_scores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["adjusted_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_score_adj_score", "score_adjustments", ["score_id"])
    op.create_index("ix_score_adj_composite", "score_adjustments", ["composite_score_id"])

    # --- calibration_sessions ------------------------------------------------
    op.create_table(
        "calibration_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "open", "in_progress", "completed", "locked",
                name="calibrationstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="open",
        ),
        sa.Column("facilitator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "scope_user_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["review_cycle_id"], ["review_cycles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["facilitator_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calibration_session_cycle", "calibration_sessions", ["review_cycle_id"])
    op.create_index("ix_calibration_session_org", "calibration_sessions", ["organisation_id"])


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_index("ix_calibration_session_org", table_name="calibration_sessions")
    op.drop_index("ix_calibration_session_cycle", table_name="calibration_sessions")
    op.drop_table("calibration_sessions")

    op.drop_index("ix_score_adj_composite", table_name="score_adjustments")
    op.drop_index("ix_score_adj_score", table_name="score_adjustments")
    op.drop_table("score_adjustments")

    op.drop_index("ix_composite_score_status", table_name="composite_scores")
    op.drop_index("ix_composite_score_org_cycle", table_name="composite_scores")
    op.drop_table("composite_scores")

    op.drop_index("ix_perf_score_status", table_name="performance_scores")
    op.drop_index("ix_perf_score_kpi_cycle", table_name="performance_scores")
    op.drop_index("ix_perf_score_user_cycle", table_name="performance_scores")
    op.drop_table("performance_scores")

    op.drop_table("score_configs")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS calibrationstatus")
    op.execute("DROP TYPE IF EXISTS scorestatus")
    op.execute("DROP TYPE IF EXISTS ratinglabel")
