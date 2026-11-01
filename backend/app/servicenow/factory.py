from functools import lru_cache

from app.core.config import Settings, get_settings

from .base import ServiceNowClient
from .errors import ServiceNowValidationError
from .instance import load_instance_config
from .live import LiveServiceNowClient
from .mock import MockServiceNowClient


def create_client(settings: Settings | None = None) -> ServiceNowClient:
    s = settings or get_settings()
    mode = s.servicenow_mode.lower()

    if mode == "mock":
        config = load_instance_config(s.sn_config_path or None, allow_example=True)
        return MockServiceNowClient(config)

    if mode == "live":
        if not (s.sn_instance and s.sn_user and s.sn_password):
            raise ServiceNowValidationError("live mode needs SN_INSTANCE, SN_USER, SN_PASSWORD")
        config = load_instance_config(s.sn_config_path or None)
        if config.has_placeholders:
            raise ServiceNowValidationError(
                "servicenow.json still contains placeholder sys_ids; use your real ones"
            )
        return LiveServiceNowClient(
            s.sn_instance,
            s.sn_user,
            s.sn_password,
            instance_config=config,
            kb_sys_id=s.sn_kb_sys_id,
            timeout=s.sn_timeout,
            max_retries=s.sn_max_retries,
        )

    raise ValueError(f"SERVICENOW_MODE must be 'mock' or 'live', got {s.servicenow_mode!r}")


@lru_cache
def get_client() -> ServiceNowClient:
    """Shared client for the app (use as a FastAPI dependency)."""
    return create_client()
