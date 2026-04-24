# 03 — Notification Types

This document describes all 12 notification types supported by the system.
For each type you will find: when it fires, who receives it, what the rendered
message looks like, whether Redis debouncing applies, and which preference flag
controls it.

---

## Overview Table

| Enum value | Trigger | Audience | Debounce TTL | Preference flag |
|------------|---------|----------|--------------|-----------------|
| `kpi_at_risk` | Actual value ≤ 60% of target | Target owner (employee) | 24 hours per target | `kpi_at_risk` |
| `team_kpi_at_risk` | Same — subordinate's target | Manager of target owner | 24 hours per target | `kpi_at_risk` |
| `actual_entry_due` | No actual submitted for current period | Target owner | 7 days per target+period | `entry_reminders` |
| `target_acknowledgement_due` | Target not yet acknowledged by assignee | Target owner | 7 days per target+period | `target_acknowledgement` |
| `period_closing_soon` | N days before period end (configurable) | All users in org | 24 hours per cycle+days | `period_closing` |
| `approval_pending` | Target submitted, awaiting manager approval | Assigned manager | None | `approvals` |
| `target_achieved` | Actual ≥ 100% of target | Target owner | 72 hours per target | `achievements` |
| `stretch_target_achieved` | Actual ≥ 120% of target | Target owner | 72 hours per target | `achievements` |
| `scoring_complete` | Scoring run finalised for a review cycle | All scored users | None | `scoring_updates` |
| `calibration_required` | Score variance detected post-calibration | HR Admin / managers | None | `calibration` |
| `score_finalised` | Final score approved and locked | Scored employee | None | `scoring_updates` |
| `score_adjusted` | Previously-finalised score changed | Scored employee | None | `scoring_updates` |

---

## Detailed Type Reference

### `KPI_AT_RISK`

**Business meaning**: The employee's KPI is performing below expectations and may
miss its target.  The system defines "at risk" as the current actual value being
≤ 60% of the target value for the current measurement period.

**When fired**: Daily by `check_at_risk_kpis_job` (runs at 08:00 UTC).

**Who receives it**: The employee who owns the target.

**Rendered notification example**:
```
Title:  KPI At Risk: Revenue Growth
Body:   Your KPI "Revenue Growth" is currently at 45% of target.
        Immediate attention may be required.
URL:    /targets/{target_id}
```

**Debounce**: Redis key `notif:at_risk:{target_id}`, TTL 24 hours.
One alert per target, per day maximum.

**Preference flag**: `kpi_at_risk = True`

---

### `TEAM_KPI_AT_RISK`

**Business meaning**: One of the manager's direct reports has a KPI at risk.
Managers need visibility of team performance without having to review every
employee's dashboard manually.

**When fired**: Same job as `KPI_AT_RISK` — immediately after the employee is
notified.

**Who receives it**: The manager of the target owner's department, if a manager
exists in the organisation tree.

**Rendered notification example**:
```
Title:  Team KPI At Risk: Revenue Growth (Jane Smith)
Body:   Jane Smith's KPI "Revenue Growth" is at 45% of target.
        This may affect team performance. Review is recommended.
URL:    /targets/{target_id}
```

**Debounce**: Shares the same Redis key as `KPI_AT_RISK` (`notif:at_risk:{target_id}`), TTL 24 hours.

**Preference flag**: `kpi_at_risk = True`

---

### `ACTUAL_ENTRY_DUE`

**Business meaning**: An employee has not yet submitted the actual value for
their KPI in the current measurement period.  If they do not record the actual,
scoring cannot be performed.

**When fired**: Weekdays at 09:00 UTC by `send_entry_reminder_job`.  The job
only fires if today falls within an active review cycle's measurement window
and no actual has been submitted for the current period.

**Who receives it**: The employee who owns the target.

**Rendered notification example**:
```
Title:  Action Required: KPI Data Entry Due
Body:   You have not yet submitted your actual for "Revenue Growth"
        in the current period. Please submit as soon as possible.
URL:    /targets/{target_id}/actuals/new
```

**Debounce**: Redis key `notif:reminder:{target_id}:{period_label}`, TTL 7 days.
Maximum one reminder per target per measurement period.

**Preference flag**: `entry_reminders = True`

---

### `TARGET_ACKNOWLEDGEMENT_DUE`

**Business meaning**: A target has been assigned to the employee but they have
not yet formally acknowledged (accepted) it.  Target ownership is not valid until
acknowledged, and scoring cannot proceed for unacknowledged targets.

**When fired**: Same job as `ACTUAL_ENTRY_DUE` (weekdays at 09:00 UTC).

**Who receives it**: The employee who owns the target.

**Rendered notification example**:
```
Title:  Please Acknowledge Your Target
Body:   Your target "Revenue Growth" requires your acknowledgement.
        Please review and confirm your acceptance.
URL:    /targets/{target_id}
```

**Debounce**: Redis key `notif:reminder:{target_id}:ack`, TTL 7 days.

**Preference flag**: `target_acknowledgement = True`

---

### `PERIOD_CLOSING_SOON`

**Business meaning**: The current review cycle's measurement period is about to
close.  This is a heads-up for all staff to submit outstanding actuals before
the deadline.  The default warning window is 3 days before period end.

**When fired**: Daily at 07:00 UTC by `send_period_closing_reminders_job`.

**Who receives it**: All active users in the organisation.

**Rendered notification example**:
```
Title:  Period Closing in 3 Days
Body:   The current measurement period ends on 31 March 2025.
        Please ensure all KPI actuals are submitted before the deadline.
URL:    /review-cycles/{cycle_id}
```

**Debounce**: Redis key `notif:period_closing:{cycle_id}:{days}`, TTL 24 hours.
One notification per cycle per days-remaining value — so if the default is 3 days,
users get at most one per day as `days` decreases.

**Preference flag**: `period_closing = True`

**User-configurable**: `period_closing_days_before` in preferences (default 3).
Users who want earlier warning can set this to 5 or 7.

---

### `APPROVAL_PENDING`

**Business meaning**: An employee has submitted a target or actual record that
requires manager approval before it becomes official.  The manager must act to
unblock the workflow.

**When fired**: Triggered directly by service-layer code when a submission is
made (not by a background job).

**Who receives it**: The approving manager.

**Rendered notification example**:
```
Title:  Approval Required
Body:   A target "Revenue Growth" submitted by Jane Smith requires your approval.
URL:    /targets/{target_id}
```

**Debounce**: None — each submission creates a new approval request.

**Preference flag**: `approvals = True`

---

### `TARGET_ACHIEVED`

**Business meaning**: The employee has hit 100% of their target.  This is a
positive recognition notification to celebrate the achievement.

**When fired**: Daily by `check_at_risk_kpis_job` (alongside at-risk checks).

**Who receives it**: The target owner.

**Rendered notification example**:
```
Title:  Target Achieved!
Body:   Congratulations! You have achieved your target for "Revenue Growth".
        Your performance score for this KPI will reflect this achievement.
URL:    /targets/{target_id}
```

**Debounce**: Redis key `notif:achieved:{target_id}`, TTL 72 hours.

**Preference flag**: `achievements = True`

---

### `STRETCH_TARGET_ACHIEVED`

**Business meaning**: The employee has exceeded 120% of their target — an
exceptional performance result.  Differentiated from `TARGET_ACHIEVED` to
allow managers and HR to identify top performers.

**When fired**: Same job as `TARGET_ACHIEVED`.

**Who receives it**: The target owner.

**Rendered notification example**:
```
Title:  Stretch Target Achieved!
Body:   Outstanding! You have exceeded your stretch target for "Revenue Growth"
        (120%+). This will be highlighted in your performance review.
URL:    /targets/{target_id}
```

**Debounce**: Shares `notif:achieved:{target_id}`, TTL 72 hours.

**Preference flag**: `achievements = True`

---

### `SCORING_COMPLETE`

**Business meaning**: The system has finished calculating all KPI scores for a
review cycle.  Employees can now view their preliminary scores.

**When fired**: Triggered by `auto_close_review_cycle_job` when a cycle is moved
to "scoring".

**Who receives it**: All employees with a score in the cycle.

**Rendered notification example**:
```
Title:  Performance Scoring Complete
Body:   Performance scoring for Q1 2025 is now complete.
        Your scores are available for review.
URL:    /review-cycles/{cycle_id}/scores
```

**Debounce**: None.

**Preference flag**: `scoring_updates = True`

---

### `CALIBRATION_REQUIRED`

**Business meaning**: After automated scoring, some scores may require human
review and calibration — for example, when an automatic score is significantly
different from the manager's qualitative assessment.

**When fired**: During the scoring workflow when calibration flags are set.

**Who receives it**: HR Admin users and department managers.

**Rendered notification example**:
```
Title:  Score Calibration Required
Body:   Performance scores for Q1 2025 require calibration before finalisation.
        Please review and approve or adjust as needed.
URL:    /review-cycles/{cycle_id}/calibration
```

**Debounce**: None.

**Preference flag**: `calibration = True`

---

### `SCORE_FINALISED`

**Business meaning**: The employee's final performance score has been approved,
locked, and is now official.  This triggers the formal communication to the employee
that their review process is complete.

**When fired**: When HR Admin finalises scores after the calibration step.

**Who receives it**: The individual employee whose score was finalised.

**Rendered notification example**:
```
Title:  Your Performance Score is Finalised
Body:   Your performance score for Q1 2025 has been finalised.
        Please review your score and discuss with your manager.
URL:    /review-cycles/{cycle_id}/my-score
```

**Debounce**: None.

**Preference flag**: `scoring_updates = True`

---

### `SCORE_ADJUSTED`

**Business meaning**: A previously finalised score has been changed — this can
happen as a result of a formal appeal or administrative correction.  Employees
must be notified when their official score changes after finalisation.

**When fired**: When an HR Admin changes a finalised score.

**Who receives it**: The affected employee.

**Rendered notification example**:
```
Title:  Your Performance Score Has Been Adjusted
Body:   Your performance score for Q1 2025 has been adjusted.
        Please log in to review the updated score.
URL:    /review-cycles/{cycle_id}/my-score
```

**Debounce**: None — every adjustment must be communicated.

**Preference flag**: `scoring_updates = True`

---

## Notification Templates

Templates are implemented as pure functions in `app/notifications/templates.py`.

Each template is a callable with signature:
```python
def _(ctx: dict) -> tuple[str, str, str | None]:
    # Returns: (title, body, action_url)
    ...
```

The public API is:
```python
from app.notifications.templates import render_notification
from app.notifications.enums import NotificationType

title, body, action_url = render_notification(
    notification_type=NotificationType.KPI_AT_RISK,
    context={
        "kpi_name": "Revenue Growth",
        "target_id": "550e8400-...",
        "percentage": 45,
    }
)
```

### Template Context Variables

| Notification type | Required context keys |
|-------------------|-----------------------|
| `kpi_at_risk` | `kpi_name`, `target_id`, `percentage` |
| `team_kpi_at_risk` | `kpi_name`, `target_id`, `employee_name`, `percentage` |
| `actual_entry_due` | `kpi_name`, `target_id` |
| `target_acknowledgement_due` | `kpi_name`, `target_id` |
| `period_closing_soon` | `days_remaining`, `period_end_date`, `cycle_id` |
| `approval_pending` | `kpi_name`, `target_id`, `submitter_name` |
| `target_achieved` | `kpi_name`, `target_id` |
| `stretch_target_achieved` | `kpi_name`, `target_id` |
| `scoring_complete` | `cycle_name`, `cycle_id` |
| `calibration_required` | `cycle_name`, `cycle_id` |
| `score_finalised` | `cycle_name`, `cycle_id` |
| `score_adjusted` | `cycle_name`, `cycle_id` |

> If a required key is missing the template falls back gracefully — most use
> `.get("kpi_name", "your KPI")` style access to avoid `KeyError` at runtime.
