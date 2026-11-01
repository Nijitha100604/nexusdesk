import re
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from .constants import GROUP_NAMES
from .errors import ServiceNowValidationError
from .validation import SYS_ID_RE

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = BACKEND_DIR / "config" / "servicenow.json"
EXAMPLE_CONFIG_PATH = BACKEND_DIR / "config" / "servicenow.example.json"
_PLACEHOLDER_RE = re.compile(r"^(.)\1{31}$")  # e.g. 1111...1


class InstanceConfig(BaseModel):
    groups: dict[str, str]
    callers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "InstanceConfig":
        missing = [n for n in GROUP_NAMES if n not in self.groups]
        if missing:
            raise ValueError(f"missing groups in config: {missing}")
        for name, sys_id in {**self.groups, **self.callers}.items():
            if not SYS_ID_RE.match(sys_id):
                raise ValueError(f"{name}: not a 32-char lowercase hex sys_id")
        return self

    @property
    def has_placeholders(self) -> bool:
        values = [*self.groups.values(), *self.callers.values()]
        return any(_PLACEHOLDER_RE.match(v) for v in values)

    def group_id(self, name: str) -> str:
        try:
            return self.groups[name]
        except KeyError:
            raise ServiceNowValidationError(
                f"unknown group {name!r}; known: {list(self.groups)}"
            ) from None


def load_instance_config(
    path: Path | str | None = None, *, allow_example: bool = False
) -> InstanceConfig:
    if path:
        target = Path(path)
    elif DEFAULT_CONFIG_PATH.exists():
        target = DEFAULT_CONFIG_PATH
    elif allow_example:
        target = EXAMPLE_CONFIG_PATH
    else:
        raise ServiceNowValidationError(
            "backend/config/servicenow.json not found; copy servicenow.example.json "
            "and fill in your real sys_ids"
        )
    return InstanceConfig.model_validate_json(target.read_text(encoding="utf-8"))
