"""
Adapter Registry — central registry for all data source adapters.
Fully extensible: add new adapters without touching core code.
"""

from app.integrations.adapters.base import BaseAdapter


class AdapterRegistry:
    """
    Central registry for all data adapters.
    Adapters self-register at module load time.
    """

    _adapters: dict[str, type[BaseAdapter]] = {}

    @classmethod
    def register(cls, name: str, adapter_class: type[BaseAdapter]) -> None:
        """Register a new adapter. Call at module load time."""
        if name in cls._adapters:
            raise ValueError(f"Adapter '{name}' already registered")
        cls._adapters[name] = adapter_class

    @classmethod
    def get(cls, adapter_name: str) -> BaseAdapter:
        """Return an instance of the named adapter."""
        if adapter_name not in cls._adapters:
            raise ValueError(
                f"Unknown adapter: '{adapter_name}'. "
                f"Available: {list(cls._adapters.keys())}"
            )
        return cls._adapters[adapter_name]()

    @classmethod
    def list_available(cls) -> list[dict]:
        """Returns metadata for all registered adapters (for frontend config UI)."""
        result = []
        for name, adapter_class in cls._adapters.items():
            instance = adapter_class()
            result.append(
                {
                    "name": name,
                    "schema": instance.get_config_schema(),
                }
            )
        return result

    @classmethod
    def is_registered(cls, name: str) -> bool:
        return name in cls._adapters


_REGISTERED = False


def register_builtin_adapters() -> None:
    """Register all built-in adapters. Called once at app startup."""
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True

    from app.integrations.adapters.csv_upload import CsvUploadAdapter
    from app.integrations.adapters.database import DatabaseAdapter
    from app.integrations.adapters.influxdb import InfluxDbAdapter
    from app.integrations.adapters.kpi_actual import KPIActualAdapter
    from app.integrations.adapters.rest_api import RestApiAdapter
    from app.integrations.adapters.webhook import WebhookReceiveAdapter

    AdapterRegistry.register("rest_api", RestApiAdapter)
    AdapterRegistry.register("database", DatabaseAdapter)
    AdapterRegistry.register("influxdb", InfluxDbAdapter)
    AdapterRegistry.register("webhook_receive", WebhookReceiveAdapter)
    AdapterRegistry.register("kpi_actual", KPIActualAdapter)
    AdapterRegistry.register("csv_upload", CsvUploadAdapter)
