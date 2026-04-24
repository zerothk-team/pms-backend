from enum import Enum


class MeasurementUnit(str, Enum):
    PERCENTAGE = "percentage"
    CURRENCY = "currency"
    COUNT = "count"
    SCORE = "score"
    RATIO = "ratio"
    DURATION_HOURS = "duration_hours"
    CUSTOM = "custom"


class MeasurementFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    ON_DEMAND = "on_demand"


class DataSourceType(str, Enum):
    MANUAL = "manual"
    FORMULA = "formula"
    INTEGRATION = "integration"


class ScoringDirection(str, Enum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class KPIStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class DepartmentCategory(str, Enum):
    SALES = "sales"
    MARKETING = "marketing"
    FINANCE = "finance"
    HR = "hr"
    OPERATIONS = "operations"
    ENGINEERING = "engineering"
    CUSTOMER_SUCCESS = "customer_success"
    PRODUCT = "product"
    LEGAL = "legal"
    GENERAL = "general"
