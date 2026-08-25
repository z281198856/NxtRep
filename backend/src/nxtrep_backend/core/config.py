from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    jwt_secret: SecretStr | None = None
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    password_setup_token_expire_minutes: int = 30
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="NXTREP_",
        extra="ignore",
    )

    app_name: str = "NxtRep API"
    environment: str = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://nxtrep:nxtrep@localhost:5432/nxtrep"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5-mini"
    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def empty_openai_api_key_is_unset(cls, value: object) -> object:
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
