from enum import Enum


class ScoreStatus(str, Enum):
    COMPUTED = "computed"                   # auto-calculated, not yet reviewed
    MANAGER_REVIEWED = "manager_reviewed"  # manager has seen/acknowledged it
    ADJUSTED = "adjusted"                  # manager applied a qualitative adjustment
    CALIBRATED = "calibrated"              # went through a calibration session
    FINAL = "final"                        # locked; no further changes allowed
    APPEALED = "appealed"                  # employee disputes the score (stub)


class RatingLabel(str, Enum):
    EXCEPTIONAL = "exceptional"                       # ≥ exceptional_min (default 120%)
    EXCEEDS_EXPECTATIONS = "exceeds_expectations"    # ≥ exceeds_min      (default 100%)
    MEETS_EXPECTATIONS = "meets_expectations"        # ≥ meets_min        (default 80%)
    PARTIALLY_MEETS = "partially_meets"              # ≥ partially_meets_min (default 60%)
    DOES_NOT_MEET = "does_not_meet"                  # ≥ 0%
    NOT_RATED = "not_rated"                          # no actuals submitted at all


class CalibrationStatus(str, Enum):
    OPEN = "open"              # session created, not yet started
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"    # all adjustments done; scores marked CALIBRATED
    LOCKED = "locked"          # after scores are FINAL, session is sealed
