from enum import Enum


class VariableSourceType(str, Enum):
    MANUAL = "manual"                    # user types value on actuals entry screen
    REST_API = "rest_api"                # HTTP GET/POST to external endpoint
    DATABASE = "database"               # direct SQL query to external DB
    INFLUXDB = "influxdb"               # InfluxDB/time-series via Flux query
    WEBHOOK_RECEIVE = "webhook_receive"  # external system POSTs to PMS
    KPI_ACTUAL = "kpi_actual"            # pull latest actual from another KPI
    CSV_UPLOAD = "csv_upload"           # periodic CSV upload (batch)
    FORMULA = "formula"                 # derived from other variables within the same KPI


class VariableDataType(str, Enum):
    NUMBER = "number"                   # floating point
    INTEGER = "integer"                 # whole numbers only
    PERCENTAGE = "percentage"           # 0–100 (or 0–∞ for over-achievement)
    CURRENCY = "currency"               # tied to org currency, stored as Numeric
    BOOLEAN = "boolean"                 # 1/0, used in conditional formulas
    DURATION_HOURS = "duration_hours"


class SyncStatus(str, Enum):
    NEVER_SYNCED = "never_synced"
    SYNCING = "syncing"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"  # some periods succeeded, some failed
