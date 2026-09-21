from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    unit_system: Literal["metric", "imperial"]
    timezone: str
    privacy_mode: Literal["private", "summary"]
    share_anonymous_analytics: bool
    version: int


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_system: Literal["metric", "imperial"] | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    privacy_mode: Literal["private", "summary"] | None = None
    share_anonymous_analytics: bool | None = None
    expected_version: int = Field(ge=1)

    @field_validator("timezone")
    @classmethod
    def require_valid_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return normalized

    @model_validator(mode="after")
    def require_change(self) -> Self:
        fields = {
            "unit_system",
            "timezone",
            "privacy_mode",
            "share_anonymous_analytics",
        }
        if not self.model_fields_set.intersection(fields):
            raise ValueError("At least one settings field must be provided")
        return self
