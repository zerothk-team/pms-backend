"""Enums for the Notifications module."""

from enum import Enum


class NotificationType(str, Enum):
    # At-risk alerts
    KPI_AT_RISK = "kpi_at_risk"                           # employee's KPI below threshold
    TEAM_KPI_AT_RISK = "team_kpi_at_risk"                 # manager: team member at risk

    # Reminders
    ACTUAL_ENTRY_DUE = "actual_entry_due"                 # period entry overdue
    TARGET_ACKNOWLEDGEMENT_DUE = "target_acknowledgement_due"
    PERIOD_CLOSING_SOON = "period_closing_soon"           # cycle closing in N days
    APPROVAL_PENDING = "approval_pending"                 # actual awaiting manager review

    # Positive
    TARGET_ACHIEVED = "target_achieved"                   # 100% hit
    STRETCH_TARGET_ACHIEVED = "stretch_target_achieved"   # stretch target hit

    # Admin
    SCORING_COMPLETE = "scoring_complete"
    CALIBRATION_REQUIRED = "calibration_required"
    SCORE_FINALISED = "score_finalised"
    SCORE_ADJUSTED = "score_adjusted"                     # manager changed employee's score


class NotificationChannel(str, Enum):
    IN_APP = "in_app"   # stored in DB, shown in UI
    EMAIL = "email"     # sent via SMTP (stubbed with logging in dev)


class NotificationStatus(str, Enum):
    UNREAD = "unread"
    READ = "read"
    DISMISSED = "dismissed"
