"""
Notification content templates.

Each entry in NOTIFICATION_TEMPLATES is a callable that accepts a context dict
and returns a 3-tuple of (title, body, action_url).

Context keys expected by each template are documented inline.  Templates must
be defensive — fall back gracefully if optional keys are missing so that a
missing piece of context never prevents a notification from being stored.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from app.notifications.enums import NotificationType

# Signature: context_dict → (title, body, action_url | None)
_TemplateFn = Callable[[dict], tuple[str, str, Optional[str]]]


def _kpi_at_risk(ctx: dict) -> tuple[str, str, Optional[str]]:
    kpi_name = ctx.get("kpi_name", "KPI")
    achievement = ctx.get("achievement_pct", 0.0)
    gap = ctx.get("gap", 0.0)
    unit = ctx.get("unit", "units")
    cycle_end = ctx.get("cycle_end_date", "the end of the cycle")
    target_id = ctx.get("target_id")
    return (
        f"⚠️ KPI at risk: {kpi_name}",
        (
            f"Your KPI '{kpi_name}' is at {achievement:.1f}% of target. "
            f"You need {gap:.1f} more {unit} to reach your target by {cycle_end}. "
            "Log your latest actual to keep your progress up to date."
        ),
        f"/dashboard/kpis/{target_id}" if target_id else None,
    )


def _team_kpi_at_risk(ctx: dict) -> tuple[str, str, Optional[str]]:
    employee_name = ctx.get("employee_name", "A team member")
    kpi_name = ctx.get("kpi_name", "KPI")
    achievement = ctx.get("achievement_pct", 0.0)
    target_id = ctx.get("target_id")
    return (
        f"⚠️ Team KPI at risk: {kpi_name}",
        (
            f"{employee_name}'s KPI '{kpi_name}' is at {achievement:.1f}% of target. "
            "Consider supporting them to get back on track."
        ),
        f"/dashboard/team/kpis/{target_id}" if target_id else None,
    )


def _actual_entry_due(ctx: dict) -> tuple[str, str, Optional[str]]:
    kpi_name = ctx.get("kpi_name", "KPI")
    period_label = ctx.get("period_label", "this period")
    frequency = ctx.get("frequency", "periodic")
    deadline = ctx.get("deadline", "soon")
    target_id = ctx.get("target_id")
    return (
        f"Action needed: Enter {kpi_name} for {period_label}",
        (
            f"Your {frequency} entry for '{kpi_name}' ({period_label}) is overdue. "
            f"The deadline was {deadline}. Please submit your actual value as soon as possible."
        ),
        f"/dashboard/actuals/new?target_id={target_id}" if target_id else None,
    )


def _target_acknowledgement_due(ctx: dict) -> tuple[str, str, Optional[str]]:
    kpi_name = ctx.get("kpi_name", "KPI")
    target_value = ctx.get("target_value", "")
    deadline = ctx.get("deadline", "soon")
    target_id = ctx.get("target_id")
    return (
        f"Please acknowledge your target for {kpi_name}",
        (
            f"Your manager has set a target of {target_value} for '{kpi_name}'. "
            f"Please review and acknowledge it by {deadline}."
        ),
        f"/dashboard/targets/{target_id}" if target_id else None,
    )


def _period_closing_soon(ctx: dict) -> tuple[str, str, Optional[str]]:
    cycle_name = ctx.get("cycle_name", "the review cycle")
    days = ctx.get("days_until_close", 0)
    cycle_id = ctx.get("cycle_id")
    day_word = "day" if days == 1 else "days"
    return (
        f"Review cycle closing in {days} {day_word}: {cycle_name}",
        (
            f"'{cycle_name}' closes in {days} {day_word}. "
            "Make sure all your actuals are submitted and targets are acknowledged "
            "before the deadline."
        ),
        f"/dashboard/cycles/{cycle_id}" if cycle_id else None,
    )


def _approval_pending(ctx: dict) -> tuple[str, str, Optional[str]]:
    employee_name = ctx.get("employee_name", "An employee")
    kpi_name = ctx.get("kpi_name", "KPI")
    period_label = ctx.get("period_label", "this period")
    actual_id = ctx.get("actual_id")
    return (
        f"Approval needed: {employee_name} — {kpi_name}",
        (
            f"{employee_name} has submitted their actual for '{kpi_name}' ({period_label}). "
            "Please review and approve or reject it."
        ),
        f"/dashboard/actuals/{actual_id}/review" if actual_id else None,
    )


def _target_achieved(ctx: dict) -> tuple[str, str, Optional[str]]:
    kpi_name = ctx.get("kpi_name", "KPI")
    achievement = ctx.get("achievement_pct", 100.0)
    target_id = ctx.get("target_id")
    return (
        f"🎉 Target achieved: {kpi_name}",
        (
            f"Congratulations! You've reached {achievement:.1f}% of your target "
            f"for '{kpi_name}'. Keep up the great work!"
        ),
        f"/dashboard/kpis/{target_id}" if target_id else None,
    )


def _stretch_target_achieved(ctx: dict) -> tuple[str, str, Optional[str]]:
    kpi_name = ctx.get("kpi_name", "KPI")
    achievement = ctx.get("achievement_pct", 100.0)
    target_id = ctx.get("target_id")
    return (
        f"🏆 Stretch target achieved: {kpi_name}",
        (
            f"Outstanding! You've exceeded 100% and hit your stretch target "
            f"for '{kpi_name}' with {achievement:.1f}% achievement. Excellent performance!"
        ),
        f"/dashboard/kpis/{target_id}" if target_id else None,
    )


def _scoring_complete(ctx: dict) -> tuple[str, str, Optional[str]]:
    cycle_name = ctx.get("cycle_name", "the review cycle")
    cycle_id = ctx.get("cycle_id")
    employee_count = ctx.get("employee_count", 0)
    return (
        f"Scoring complete: {cycle_name}",
        (
            f"Automated scoring for '{cycle_name}' is complete. "
            f"{employee_count} employee score(s) have been computed and are ready for review."
        ),
        f"/dashboard/scoring/{cycle_id}" if cycle_id else None,
    )


def _calibration_required(ctx: dict) -> tuple[str, str, Optional[str]]:
    cycle_name = ctx.get("cycle_name", "a review cycle")
    session_id = ctx.get("session_id")
    return (
        f"Calibration required: {cycle_name}",
        (
            f"A calibration session has been opened for '{cycle_name}'. "
            "Please review and calibrate the scores before final sign-off."
        ),
        f"/dashboard/calibration/{session_id}" if session_id else None,
    )


def _score_finalised(ctx: dict) -> tuple[str, str, Optional[str]]:
    cycle_name = ctx.get("cycle_name", "the review cycle")
    rating = ctx.get("rating", "")
    cycle_id = ctx.get("cycle_id")
    rating_text = f" Your overall rating is: {rating}." if rating else ""
    return (
        f"Your performance score is finalised: {cycle_name}",
        (
            f"Your performance score for '{cycle_name}' has been finalised.{rating_text} "
            "You can now view your full score breakdown."
        ),
        f"/dashboard/my-scores/{cycle_id}" if cycle_id else None,
    )


def _score_adjusted(ctx: dict) -> tuple[str, str, Optional[str]]:
    kpi_name = ctx.get("kpi_name", "a KPI")
    before = ctx.get("before_value", "")
    after = ctx.get("after_value", "")
    manager_name = ctx.get("manager_name", "Your manager")
    score_id = ctx.get("score_id")
    return (
        f"Score adjusted: {kpi_name}",
        (
            f"{manager_name} has adjusted your score for '{kpi_name}' "
            f"from {before} to {after}. "
            "You can view the adjustment details in your score breakdown."
        ),
        f"/dashboard/scores/{score_id}" if score_id else None,
    )


# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------

NOTIFICATION_TEMPLATES: dict[NotificationType, _TemplateFn] = {
    NotificationType.KPI_AT_RISK: _kpi_at_risk,
    NotificationType.TEAM_KPI_AT_RISK: _team_kpi_at_risk,
    NotificationType.ACTUAL_ENTRY_DUE: _actual_entry_due,
    NotificationType.TARGET_ACKNOWLEDGEMENT_DUE: _target_acknowledgement_due,
    NotificationType.PERIOD_CLOSING_SOON: _period_closing_soon,
    NotificationType.APPROVAL_PENDING: _approval_pending,
    NotificationType.TARGET_ACHIEVED: _target_achieved,
    NotificationType.STRETCH_TARGET_ACHIEVED: _stretch_target_achieved,
    NotificationType.SCORING_COMPLETE: _scoring_complete,
    NotificationType.CALIBRATION_REQUIRED: _calibration_required,
    NotificationType.SCORE_FINALISED: _score_finalised,
    NotificationType.SCORE_ADJUSTED: _score_adjusted,
}


def render_notification(
    notification_type: NotificationType, context: dict
) -> tuple[str, str, str | None]:
    """Render title, body and action_url for a notification type and context."""
    template_fn = NOTIFICATION_TEMPLATES.get(notification_type)
    if template_fn is None:
        # Fallback for any future types not yet templated
        return (
            notification_type.value.replace("_", " ").title(),
            "You have a new notification.",
            None,
        )
    return template_fn(context)
