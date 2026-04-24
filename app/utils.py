"""
Shared utility helpers for the PMS backend.

Period utilities are used by both the review_cycles and actuals modules to
generate human-readable labels and enumerate expected measurement periods
inside a cycle.
"""

from datetime import date, timedelta

from app.kpis.enums import MeasurementFrequency


def generate_period_label(period_date: date, frequency: MeasurementFrequency) -> str:
    """
    Return a human-readable label for a measurement period.

    Examples:
        daily      → "01 Jan 2025"
        weekly     → "Week 1, Jan 2025"
        monthly    → "January 2025"
        quarterly  → "Q1 2025"
        yearly     → "2025"
        on_demand  → "01 Jan 2025"
    """
    if frequency == MeasurementFrequency.DAILY:
        return period_date.strftime("%d %b %Y")

    if frequency == MeasurementFrequency.WEEKLY:
        first_of_month = period_date.replace(day=1)
        week_num = (period_date - first_of_month).days // 7 + 1
        return f"Week {week_num}, {period_date.strftime('%b %Y')}"

    if frequency == MeasurementFrequency.MONTHLY:
        return period_date.strftime("%B %Y")

    if frequency == MeasurementFrequency.QUARTERLY:
        quarter = (period_date.month - 1) // 3 + 1
        return f"Q{quarter} {period_date.year}"

    if frequency == MeasurementFrequency.YEARLY:
        return str(period_date.year)

    # ON_DEMAND — fall back to date display
    return period_date.strftime("%d %b %Y")


def get_period_start_dates(
    start: date,
    end: date,
    frequency: MeasurementFrequency,
) -> list[date]:
    """
    Return all expected period start dates within [start, end] for the given frequency.

    Dates are normalised to calendar boundaries:
        - MONTHLY    → 1st of each month from start's month to end's month
        - QUARTERLY  → Jan 1 / Apr 1 / Jul 1 / Oct 1 within the range
        - YEARLY     → Jan 1 of each year within the range
        - WEEKLY     → start date + multiples of 7 days
        - DAILY      → every date from start to end inclusive
        - ON_DEMAND  → just [start] (no fixed schedule)
    """
    if frequency == MeasurementFrequency.ON_DEMAND:
        return [start]

    if frequency == MeasurementFrequency.DAILY:
        dates: list[date] = []
        cur = start
        while cur <= end:
            dates.append(cur)
            cur += timedelta(days=1)
        return dates

    if frequency == MeasurementFrequency.WEEKLY:
        dates = []
        cur = start
        while cur <= end:
            dates.append(cur)
            cur += timedelta(weeks=1)
        return dates

    if frequency == MeasurementFrequency.MONTHLY:
        # Normalise to 1st of start's month
        cur = start.replace(day=1)
        dates = []
        while cur <= end:
            if cur >= start:
                dates.append(cur)
            # Advance by 1 month
            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1, day=1)
            else:
                cur = cur.replace(month=cur.month + 1, day=1)
        return dates

    if frequency == MeasurementFrequency.QUARTERLY:
        # Snap to quarter start: Jan, Apr, Jul, Oct
        quarter_start_month = ((start.month - 1) // 3) * 3 + 1
        cur = start.replace(month=quarter_start_month, day=1)
        dates = []
        while cur <= end:
            if cur >= start:
                dates.append(cur)
            new_month = cur.month + 3
            new_year = cur.year
            if new_month > 12:
                new_month -= 12
                new_year += 1
            cur = cur.replace(year=new_year, month=new_month, day=1)
        return dates

    if frequency == MeasurementFrequency.YEARLY:
        cur = start.replace(month=1, day=1)
        dates = []
        while cur <= end:
            if cur >= start:
                dates.append(cur)
            cur = cur.replace(year=cur.year + 1, month=1, day=1)
        return dates

    return [start]
