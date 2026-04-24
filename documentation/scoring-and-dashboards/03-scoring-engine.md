# 03 — Scoring Engine Algorithm

← [Back to Index](index.md)

---

## Overview

The scoring engine converts KPI actuals into numeric performance scores using a five-step pipeline. All calculations are done using Python's `Decimal` type for precision — no floating-point arithmetic.

The pipeline runs in `app/scoring/calculator.py` (pure functions) and is orchestrated by `ScoringEngine` in `app/scoring/service.py`.

---

## Step 1 — Achievement Percentage

**Function**: `compute_achievement_percentage(actual, target, direction, minimum_value)`

This measures "how well did the employee hit their target?"

### Higher-is-Better KPIs
```
achievement_pct = (actual_value / target_value) × 100
```

| Example | Calculation | Result |
|---------|-------------|--------|
| Revenue target 100 K, actual 115 K | (115 / 100) × 100 | 115 % |
| Calls target 50, actual 40 | (40 / 50) × 100 | 80 % |
| Calls target 50, actual 60 | (60 / 50) × 100 | 120 % |

### Lower-is-Better KPIs
```
achievement_pct = (target_value / actual_value) × 100
```

| Example | Calculation | Result |
|---------|-------------|--------|
| Defect rate target 5 %, actual 4 % | (5 / 4) × 100 | 125 % |
| Defect rate target 5 %, actual 6 % | (5 / 6) × 100 | 83.3 % |
| Error target 5, actual 0 | actual=0 for LIB → cap at 200 % | 200 % |

### Special Cases

| Condition | Result | Rationale |
|-----------|--------|-----------|
| `target_value = 0` (HIB) | 0 % | Division by zero — no valid reference |
| `actual_value = 0` (LIB) | Capped at 200 % | Zero errors/defects = perfect result |
| `actual < minimum_value` | 0 % | Hard floor — misses minimum → no credit |
| Result > 200 % | Capped at 200 % | Prevents extreme stretch bonuses |

---

## Step 2 — Weighted Score

**Function**: `compute_weighted_score(achievement_pct, weight)`

Each KPI has a weight within a review cycle (e.g. Revenue 60 %, Calls 40 %). The weighted score normalises the contribution so KPIs sum to a comparable scale.

```
weighted_score = achievement_pct × (weight / 100)
```

| Achievement | Weight | Weighted score |
|-------------|--------|----------------|
| 115 % | 60 | 69.0 |
| 80 % | 40 | 32.0 |

> A KPI with weight=45 and achievement=100 % contributes 45 points,
> not 100 points, to the composite.

---

## Step 3 — Composite Score

**Function**: `compute_composite_score(scores)`

The composite score is the weighted average of all KPI weighted scores.

```
composite = (Σ weighted_scores / Σ weights) × 100
```

**Full example** (two KPIs):

| KPI | Achievement | Weight | Weighted score |
|-----|-------------|--------|----------------|
| Revenue | 115 % | 60 | 69.0 |
| Calls | 80 % | 40 | 32.0 |

```
composite = (69.0 + 32.0) / (60 + 40) × 100 = 101.0 / 100 × 100 = 101.0
```

### Missing Actuals Penalty

**Critical business rule**: if an employee has not submitted an actual for a KPI, that KPI is included in the composite calculation with `weighted_score = 0`.

This reflects real-world performance management: **missing data is treated as 0% achievement**. An employee cannot receive a high composite score just by skipping a KPI.

| KPI | Achievement | Weight | Weighted score |
|-----|-------------|--------|----------------|
| Revenue | 115 % | 60 | 69.0 |
| Calls | *No actual* | 40 | 0.0 (penalty) |

```
composite = (69.0 + 0.0) / (60 + 40) × 100 = 69.0
```

---

## Step 4 — Rating Label

**Function**: `determine_rating(score, config)`

The composite and each KPI score are mapped to a `RatingLabel` using the thresholds from `ScoreConfig`:

```python
if score >= config.exceptional_min:      → EXCEPTIONAL
if score >= config.exceeds_min:          → EXCEEDS_EXPECTATIONS
if score >= config.meets_min:            → MEETS_EXPECTATIONS
if score >= config.partially_meets_min:  → PARTIALLY_MEETS
else:                                    → DOES_NOT_MEET
```

**Special case**: If `kpis_with_actuals == 0`, the rating is set to `NOT_RATED` without going through the threshold logic.

### Default thresholds (when no `ScoreConfig` record exists)

| Rating | Threshold |
|--------|-----------|
| EXCEPTIONAL | ≥ 120 % |
| EXCEEDS_EXPECTATIONS | ≥ 100 % |
| MEETS_EXPECTATIONS | ≥ 80 % |
| PARTIALLY_MEETS | ≥ 60 % |
| DOES_NOT_MEET | < 60 % |

---

## Step 5 — Store Results

The engine upserts (create or update) rows in `performance_scores` and `composite_scores`:

1. For each user in the cycle, find all their `LOCKED` targets.
2. For each target, find the most recent `APPROVED` actual.
3. Compute `achievement_pct` and `weighted_score`; store in `performance_scores`.
4. Aggregate all weighted scores for the user into a `composite_score`.
5. Assign rating labels using `determine_rating`.

**Idempotency**: re-running does not create duplicate rows — it updates them in place. Existing adjustments are preserved: if a score has status `ADJUSTED`, `CALIBRATED`, or `FINAL`, the `final_score` is not overwritten during recomputation.

---

## Manager Adjustments

### KPI-Level Adjustment (`PATCH /scoring/kpi-score/{score_id}/adjust`)

A manager can apply a ± point adjustment to a single KPI score:

1. Validate the adjustment is within `max_adjustment_points` from `ScoreConfig`.
2. Set `performance_score.final_score = weighted_score + adjustment`.
3. Create a `ScoreAdjustment` audit record.
4. **Automatically recompute the composite score** using the new `final_score`.

**Propagation rule**: After a KPI-level adjustment, the composite is recomputed from `final_score` (not from the original `achievement_pct`). This ensures KPI-level adjustments flow through correctly.

### Composite-Level Adjustment (`PATCH /scoring/composite/{composite_id}/adjust`)

An HR admin can directly adjust the composite score:

1. Validate within `max_adjustment_points`.
2. Set `composite.final_weighted_average = new_score`.
3. Set `composite.rating = determine_rating(new_score, config)`.
4. Create a `ScoreAdjustment` audit record.

---

## Validation Rule: Adjustment Cap

**Function**: `validate_adjustment(original, adjusted, max_adjustment)`

```
abs(adjusted - original) ≤ max_adjustment_points
```

| Original | Proposed | Cap | Valid? |
|----------|----------|-----|--------|
| 85.0 | 90.0 | 10.0 | Yes (diff = 5.0) |
| 85.0 | 95.1 | 10.0 | No (diff = 10.1 > 10.0) |
| 85.0 | 75.0 | 10.0 | Yes (diff = 10.0 ≤ 10.0) |

---

## Calibration Adjustments

Calibration adjustments bypass the `max_adjustment_points` cap. The facilitator has full authority. Changes are recorded with `adjustment_type = "calibration"` and update `composite.status` to `CALIBRATED`.

---

## Finalisation

`POST /scoring/finalise/{cycle_id}` locks all scores for a cycle:

1. Checks if `ScoreConfig.requires_calibration = true` — if so, at least one `CalibrationSession` with `status = completed` must exist.
2. Sets `status = FINAL` on all `CompositeScore` and `PerformanceScore` rows.
3. Locked scores cannot be adjusted or recomputed.

---

## Score Distribution Statistics

**Function**: `compute_score_distribution(scores)`

Used by the org dashboard and calibration sessions to provide a statistical overview.

Returns:
- `mean` — arithmetic mean
- `median` — 50th percentile
- `std_dev` — population standard deviation
- `percentiles` — `{p25, p50, p75, p90}`
- `rating_counts` — count per `RatingLabel`
- `rating_percentages` — % per `RatingLabel`
