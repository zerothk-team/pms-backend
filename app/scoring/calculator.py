"""
scoring/calculator.py — Pure scoring calculation functions.

Design principles:
  - No database calls — all inputs passed as arguments
  - All functions are pure (same input always → same output)
  - Decimal arithmetic throughout — never float for money/percentages
  - Config-aware since Enhancement 1: resolve_scoring_config() handles 3-level precedence

Key functions:
  compute_achievement_percentage(actual, target, direction, minimum, cap) → Decimal
  compute_weighted_score(achievement_pct, weight) → Decimal
  compute_composite_score(scores) → Decimal
  resolve_scoring_config(target, cycle_config) → dict   ← Enhancement 1
  determine_rating_with_config(achievement_pct, config) → (RatingLabel, source_str)

Usage from ScoringEngine:
  config = resolve_scoring_config(target, cycle_config)
  pct = compute_achievement_percentage(actual, target.target_value, kpi.scoring_direction)
  rating, source = determine_rating_with_config(pct, config)
"""

import statistics
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from app.kpis.enums import ScoringDirection
from app.scoring.enums import RatingLabel

if TYPE_CHECKING:
    from app.scoring.models import ScoreConfig
    from app.scoring.kpi_scoring_model import KPIScoringConfig
    from app.targets.models import KPITarget

# Maximum allowed achievement percentage to prevent runaway stretch bonuses.
_ACHIEVEMENT_CAP = Decimal("200.0000")
_ZERO = Decimal("0.0000")


# ---------------------------------------------------------------------------
# Per-KPI config resolution & config-aware rating
# ---------------------------------------------------------------------------


def resolve_scoring_config(
    target: "KPITarget",
    cycle_config: "ScoreConfig",
) -> dict:
    """
    Resolve the effective scoring thresholds for a KPITarget.

    Precedence (highest to lowest):
      1. target.scoring_config      (target-level override)
      2. target.kpi.scoring_config  (KPI-level default)
      3. cycle_config               (cycle-wide fallback)

    Returns a dict with keys:
      exceptional_min, exceeds_min, meets_min, partially_meets_min,
      does_not_meet_min, achievement_cap, source
    """
    # Try target-level override first
    if target.scoring_config_id and target.scoring_config:
        cfg = target.scoring_config
        return {
            "exceptional_min":    float(cfg.exceptional_min),
            "exceeds_min":        float(cfg.exceeds_min),
            "meets_min":          float(cfg.meets_min),
            "partially_meets_min": float(cfg.partially_meets_min),
            "does_not_meet_min":  float(cfg.does_not_meet_min),
            "achievement_cap":    float(cfg.achievement_cap),
            "source":             f"target_override:{cfg.name}",
        }

    # Try KPI-level default
    if target.kpi and target.kpi.scoring_config_id and target.kpi.scoring_config:
        cfg = target.kpi.scoring_config
        return {
            "exceptional_min":    float(cfg.exceptional_min),
            "exceeds_min":        float(cfg.exceeds_min),
            "meets_min":          float(cfg.meets_min),
            "partially_meets_min": float(cfg.partially_meets_min),
            "does_not_meet_min":  float(cfg.does_not_meet_min),
            "achievement_cap":    float(cfg.achievement_cap),
            "source":             f"kpi_default:{cfg.name}",
        }

    # Fall back to cycle-level config
    return {
        "exceptional_min":    float(cycle_config.exceptional_min),
        "exceeds_min":        float(cycle_config.exceeds_min),
        "meets_min":          float(cycle_config.meets_min),
        "partially_meets_min": float(cycle_config.partially_meets_min),
        "does_not_meet_min":  0.0,
        "achievement_cap":    200.0,
        "source":             "cycle_default",
    }


def determine_rating_with_config(
    achievement_pct: Decimal | None,
    scoring_config: dict,
) -> tuple[RatingLabel, str]:
    """
    Map an achievement percentage to a RatingLabel using a resolved config dict.

    Args:
        achievement_pct: Raw achievement percentage (before cap), or None.
        scoring_config:  Result of resolve_scoring_config().

    Returns:
        (RatingLabel, source_description)
    """
    if achievement_pct is None:
        return RatingLabel.NOT_RATED, scoring_config.get("source", "")

    capped = min(float(achievement_pct), scoring_config["achievement_cap"])

    if capped >= scoring_config["exceptional_min"]:
        return RatingLabel.EXCEPTIONAL, scoring_config["source"]
    if capped >= scoring_config["exceeds_min"]:
        return RatingLabel.EXCEEDS_EXPECTATIONS, scoring_config["source"]
    if capped >= scoring_config["meets_min"]:
        return RatingLabel.MEETS_EXPECTATIONS, scoring_config["source"]
    if capped >= scoring_config["partially_meets_min"]:
        return RatingLabel.PARTIALLY_MEETS, scoring_config["source"]
    return RatingLabel.DOES_NOT_MEET, scoring_config["source"]


def compute_achievement_percentage(
    actual_value: Decimal,
    target_value: Decimal,
    scoring_direction: ScoringDirection,
    minimum_value: Decimal | None = None,
) -> Decimal:
    """
    Calculate how well an employee achieved their target as a percentage.

    Business rules:
    - Higher-is-better:  (actual / target) × 100
      e.g. Revenue target 100 K, actual 115 K → 115 %
    - Lower-is-better:   (target / actual) × 100
      e.g. Defect rate target 5 %, actual 4 % → 125 % (better than target)
    - If `minimum_value` is set and the actual falls below it, the score is 0 %.
      This represents a hard floor — missing the minimum yields no credit.
    - Division by zero returns 0 % (no target set or actual is zero for LIB).
    - Result is capped at 200 % to prevent extreme stretch-target inflation.

    Args:
        actual_value:     The value entered as the actual for this period.
        target_value:     The target value from KPITarget.target_value.
        scoring_direction: Whether higher or lower actuals are better.
        minimum_value:    Optional floor; actual below this → 0 %.

    Returns:
        Achievement percentage, 0.0000–200.0000 inclusive.
    """
    # Hard floor check
    if minimum_value is not None and actual_value < minimum_value:
        return _ZERO

    try:
        if scoring_direction == ScoringDirection.HIGHER_IS_BETTER:
            if target_value == _ZERO:
                return _ZERO
            result = (actual_value / target_value) * Decimal("100")
        else:  # LOWER_IS_BETTER
            if actual_value == _ZERO:
                # Actual of 0 for a lower-is-better KPI is perfect (or zero-divided)
                return _ACHIEVEMENT_CAP if target_value > _ZERO else _ZERO
            result = (target_value / actual_value) * Decimal("100")
    except (ZeroDivisionError, Exception):
        return _ZERO

    # Cap at 200 %
    result = min(result, _ACHIEVEMENT_CAP)
    return result.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def compute_weighted_score(achievement_pct: Decimal, weight: Decimal) -> Decimal:
    """
    Apply the KPI's weight to its achievement percentage.

    weighted_score = achievement_pct × (weight / 100)

    A KPI with weight=50 contributing 120 % achievement adds 60 points
    toward the composite (not 120), keeping the composite on a 0-100+ scale
    relative to the total weight.

    Args:
        achievement_pct: Value from compute_achievement_percentage (0–200).
        weight:          KPITarget.weight, typically 0–100 (sum across user's KPIs = 100).

    Returns:
        Weighted contribution score.
    """
    if weight == _ZERO:
        return _ZERO
    result = achievement_pct * (weight / Decimal("100"))
    return result.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def compute_composite_score(scores: list[dict]) -> Decimal:
    """
    Compute the composite (overall) score as a weighted average.

    Each element in `scores` must have:
        "weighted_score": Decimal — the weighted contribution
        "weight":         Decimal — the KPI's assigned weight

    Formula: sum(weighted_scores) / sum(weights) × 100

    KPIs with no actuals submitted should be included with weighted_score=0
    so the employee is penalised for missing data.  This reflects real-world
    performance management: missing data is treated as 0 % achievement.

    Returns 0 if no scores are provided or total weight is 0.

    Args:
        scores: [{"weighted_score": Decimal, "weight": Decimal}, ...]

    Returns:
        Composite score (0–200+ scale, consistent with individual KPI scores).
    """
    if not scores:
        return _ZERO

    total_weight = sum(s["weight"] for s in scores)
    if total_weight == _ZERO:
        return _ZERO

    total_weighted = sum(s["weighted_score"] for s in scores)
    result = (total_weighted / total_weight) * Decimal("100")
    return result.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def determine_rating(score: Decimal, config: "ScoreConfig") -> RatingLabel:
    """
    Map a numeric composite/KPI score to a RatingLabel using ScoreConfig thresholds.

    Thresholds are evaluated from highest to lowest (exceptional first).
    Default config: EXCEPTIONAL ≥ 120, EXCEEDS ≥ 100, MEETS ≥ 80,
                    PARTIALLY_MEETS ≥ 60, DOES_NOT_MEET ≥ 0.

    NOT_RATED is returned only when no actuals exist (score == -1 sentinel),
    not from this function — callers should guard with that check instead.

    Args:
        score:  The final numeric score (0–200).
        config: ScoreConfig row with threshold fields.

    Returns:
        One of the RatingLabel enum values (never NOT_RATED from this function).
    """
    if score >= config.exceptional_min:
        return RatingLabel.EXCEPTIONAL
    if score >= config.exceeds_min:
        return RatingLabel.EXCEEDS_EXPECTATIONS
    if score >= config.meets_min:
        return RatingLabel.MEETS_EXPECTATIONS
    if score >= config.partially_meets_min:
        return RatingLabel.PARTIALLY_MEETS
    return RatingLabel.DOES_NOT_MEET


def validate_adjustment(
    original: Decimal,
    adjusted: Decimal,
    max_adjustment: Decimal,
) -> bool:
    """
    Return True if the proposed adjustment is within the allowed cap.

    Prevents managers from drastically inflating or deflating scores.
    The cap is symmetric — it applies equally to bumps and cuts.

    Args:
        original:       The computed or current score.
        adjusted:       The proposed new score.
        max_adjustment: The cap from ScoreConfig.max_adjustment_points.

    Returns:
        True if abs(adjusted - original) ≤ max_adjustment, else False.
    """
    return abs(adjusted - original) <= max_adjustment


def compute_score_distribution(scores: list[Decimal]) -> dict:
    """
    Compute statistical distribution metrics for a set of composite scores.

    Used by HR admins and executives to understand the spread of performance
    across the organisation or a department.

    Args:
        scores: List of composite (final_weighted_average) Decimal values.

    Returns:
        dict with keys:
            mean               — arithmetic mean
            median             — 50th percentile
            std_dev            — population standard deviation (0 if <2 scores)
            percentiles        — {"p25", "p50", "p75", "p90"}
            rating_counts      — {RatingLabel.value: int}
            rating_percentages — {RatingLabel.value: Decimal}
        All numeric values are Decimal rounded to 4 dp.
    """
    if not scores:
        return {
            "mean": _ZERO,
            "median": _ZERO,
            "std_dev": _ZERO,
            "percentiles": {"p25": _ZERO, "p50": _ZERO, "p75": _ZERO, "p90": _ZERO},
            "rating_counts": {r.value: 0 for r in RatingLabel},
            "rating_percentages": {r.value: _ZERO for r in RatingLabel},
        }

    float_scores = [float(s) for s in scores]
    n = len(float_scores)

    mean_val = Decimal(str(statistics.mean(float_scores))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    median_val = Decimal(str(statistics.median(float_scores))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    std_dev_val = (
        Decimal(str(statistics.pstdev(float_scores))).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        if n > 1
        else _ZERO
    )

    def _percentile(data: list[float], pct: float) -> Decimal:
        sorted_data = sorted(data)
        idx = (pct / 100) * (len(sorted_data) - 1)
        lower = int(idx)
        upper = min(lower + 1, len(sorted_data) - 1)
        val = sorted_data[lower] + (idx - lower) * (sorted_data[upper] - sorted_data[lower])
        return Decimal(str(val)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    percentiles = {
        "p25": _percentile(float_scores, 25),
        "p50": _percentile(float_scores, 50),
        "p75": _percentile(float_scores, 75),
        "p90": _percentile(float_scores, 90),
    }

    # Rating counts require a config — use default thresholds here for distribution
    # Callers with an actual ScoreConfig should pre-map ratings themselves
    default_thresholds = [
        (Decimal("120"), RatingLabel.EXCEPTIONAL),
        (Decimal("100"), RatingLabel.EXCEEDS_EXPECTATIONS),
        (Decimal("80"), RatingLabel.MEETS_EXPECTATIONS),
        (Decimal("60"), RatingLabel.PARTIALLY_MEETS),
        (Decimal("0"), RatingLabel.DOES_NOT_MEET),
    ]

    rating_counts: dict[str, int] = {r.value: 0 for r in RatingLabel}
    for s in scores:
        if s < _ZERO:
            # Sentinel for NOT_RATED
            rating_counts[RatingLabel.NOT_RATED.value] += 1
            continue
        for threshold, label in default_thresholds:
            if s >= threshold:
                rating_counts[label.value] += 1
                break

    total = sum(rating_counts.values()) or 1
    rating_percentages = {
        k: Decimal(str(v / total * 100)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        for k, v in rating_counts.items()
    }

    return {
        "mean": mean_val,
        "median": median_val,
        "std_dev": std_dev_val,
        "percentiles": percentiles,
        "rating_counts": rating_counts,
        "rating_percentages": rating_percentages,
    }
