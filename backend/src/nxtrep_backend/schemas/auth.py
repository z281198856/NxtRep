from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UsernameRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)

    @field_validator("username", mode="before")
    @classmethod
    def strip_username(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()

        return value


class LoginRequest(UsernameRequest):
    password: str = Field(min_length=1, max_length=128)
    device_name: str | None = Field(default=None, max_length=120)

    @field_validator("device_name", mode="before")
    @classmethod
    def normalize_device_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None

        return value


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)


class LogoutRequest(RefreshTokenRequest):
    pass


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
    device_name: str | None = Field(default=None, max_length=120)

    @field_validator("device_name", mode="before")
    @classmethod
    def normalize_device_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class PasswordSetupRequest(UsernameRequest):
    setup_token: str = Field(min_length=32, max_length=512)
    new_password: str = Field(min_length=8, max_length=128)


class AuthUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    password_setup_required: bool


class TokenPairResponse(BaseModel):
    access_token: str = Field(min_length=1)
    refresh_token: str = Field(min_length=32)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(gt=0)
    refresh_expires_in: int = Field(gt=0)
    user: AuthUserResponse


class RefreshSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    device_name: str | None
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None


class RefreshSessionListResponse(BaseModel):
    sessions: list[RefreshSessionResponse]


class CurrentAccountResponse(BaseModel):
    id: UUID
    username: str
    status: Literal["active", "disabled"]
    is_admin: bool
    password_setup_required: bool
    profile_initialized: bool
