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
    user: AuthUserResponse
