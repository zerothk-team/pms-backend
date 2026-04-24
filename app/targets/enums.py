from enum import Enum


class TargetLevel(str, Enum):
    ORGANISATION = "organisation"
    DEPARTMENT = "department"
    TEAM = "team"
    INDIVIDUAL = "individual"


class TargetStatus(str, Enum):
    DRAFT = "draft"
    PENDING_ACKNOWLEDGEMENT = "pending_acknowledgement"  # waiting for employee
    ACKNOWLEDGED = "acknowledged"                         # employee confirmed
    APPROVED = "approved"                                 # manager/hr approved
    LOCKED = "locked"                                     # period started, immutable
