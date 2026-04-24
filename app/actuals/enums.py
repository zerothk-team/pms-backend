from enum import Enum


class ActualEntrySource(str, Enum):
    MANUAL = "manual"                       # human entered via API
    AUTO_FORMULA = "auto_formula"           # computed by formula engine
    AUTO_INTEGRATION = "auto_integration"   # synced from external system


class ActualEntryStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"   # awaiting manager sign-off
    APPROVED = "approved"                   # accepted
    REJECTED = "rejected"                   # returned for correction
    SUPERSEDED = "superseded"               # replaced by a newer entry for same period
