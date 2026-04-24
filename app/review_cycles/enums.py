from enum import Enum


class CycleStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"      # targets can be set; actuals can be entered
    CLOSED = "closed"      # period ended; actuals locked; scoring runs
    ARCHIVED = "archived"


class CycleType(str, Enum):
    ANNUAL = "annual"
    SEMI_ANNUAL = "semi_annual"
    QUARTERLY = "quarterly"
    CUSTOM = "custom"
