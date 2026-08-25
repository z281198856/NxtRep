from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from nxtrep_backend.schemas.auth import UsernameRequest


class AdminUserCreateRequest(UsernameRequest):
    display_name: str | None = Field(default=None, max_length=80)
    is_admin: bool = False

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None

        return value


class AdminUserCreateResponse(BaseModel):
    id: UUID
    username: str
    display_name: str | None
    is_admin: bool
    password_setup_required: bool
    setup_token: str = Field(min_length=32)
    setup_token_expires_at: datetime
