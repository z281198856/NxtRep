import re
from functools import lru_cache
from typing import Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageConfigurationError(ValueError):
    """Raised when a configured storage provider is incomplete or unsafe."""


class OssConfiguration(BaseModel):
    """Validated, immutable OSS settings passed to the future storage provider."""

    model_config = ConfigDict(frozen=True)

    region: str
    endpoint: AnyHttpUrl
    use_cname: bool
    bucket: str
    access_key_id: SecretStr
    access_key_secret: SecretStr
    object_prefix: str
    upload_url_expire_seconds: int
    download_url_expire_seconds: int
    image_max_bytes: int


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
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=200)
    database_pool_timeout_seconds: int = Field(default=30, ge=1, le=300)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    llm_provider: Literal["deepseek", "glm"] = "deepseek"
    deepseek_api_key: SecretStr | None = None
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_thinking_enabled: bool = False
    glm_api_key: SecretStr | None = None
    glm_model: str = "glm-5.1"
    glm_vision_model: str = "glm-4.6v-flash"
    glm_vision_fallback_model: str | None = "glm-4v-flash"
    embedding_provider: Literal["glm"] = "glm"
    glm_embedding_model: str = "embedding-3"
    embedding_model_version: str = Field(
        default="v1",
        min_length=1,
        max_length=80,
    )
    embedding_dimensions: int = Field(default=1024, ge=256, le=2048)
    embedding_batch_size: int = Field(default=64, ge=1, le=64)
    embedding_timeout_seconds: int = Field(default=45, ge=1, le=300)
    embedding_max_retries: int = Field(default=2, ge=0, le=10)
    rag_enabled: bool = False
    rag_candidate_k: int = Field(default=20, ge=5, le=100)
    rag_top_k: int = Field(default=5, ge=1, le=10)
    rag_min_vector_score: float = Field(default=0.5, ge=0, le=1)
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    llm_proxy_url: AnyHttpUrl | None = None
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    llm_timeout_seconds: int = Field(default=45, ge=1, le=300)
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    agent_intent_router_timeout_seconds: int = Field(default=12, ge=1, le=300)
    agent_intent_router_max_retries: int = Field(default=0, ge=0, le=10)
    vision_temperature: float = Field(default=0.1, ge=0, le=2)
    vision_timeout_seconds: int = Field(default=60, ge=1, le=300)
    vision_max_retries: int = Field(default=1, ge=0, le=3)
    agent_sse_heartbeat_seconds: float = Field(default=15.0, ge=5.0, le=60.0)
    agent_sse_disconnect_poll_seconds: float = Field(default=1.0, ge=0.1, le=5.0)
    storage_provider: Literal["aliyun_oss"] | None = None
    oss_region: str | None = None
    oss_endpoint: AnyHttpUrl | None = None
    oss_use_cname: bool = False
    oss_bucket: str | None = None
    oss_access_key_id: SecretStr | None = None
    oss_access_key_secret: SecretStr | None = None
    oss_object_prefix: str = "images"
    oss_upload_url_expire_seconds: int = Field(default=600, ge=60, le=3600)
    oss_download_url_expire_seconds: int = Field(default=300, ge=60, le=3600)
    image_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    image_max_pixels: int = Field(
        default=25_000_000,
        ge=1_000_000,
        le=100_000_000,
    )
    image_max_dimension: int = Field(
        default=8192,
        ge=512,
        le=20_000,
    )
    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator(
        "deepseek_api_key",
        "glm_api_key",
        "oss_access_key_id",
        "oss_access_key_secret",
        mode="before",
    )
    @classmethod
    def empty_secret_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("embedding_model_version")
    @classmethod
    def normalize_embedding_model_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("embedding model version must not be blank")
        return normalized

    @field_validator(
        "llm_proxy_url",
        "oss_region",
        "oss_endpoint",
        "oss_bucket",
        mode="before",
    )
    @classmethod
    def empty_optional_value_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("oss_endpoint")
    @classmethod
    def require_https_oss_endpoint(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is not None and value.scheme != "https":
            raise ValueError("OSS endpoint must use HTTPS")
        return value

    @field_validator("oss_bucket")
    @classmethod
    def validate_oss_bucket_name(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", value) is None:
            raise ValueError(
                "OSS bucket must be 3-63 characters using lowercase letters, numbers and hyphens"
            )
        return value

    @field_validator("oss_object_prefix")
    @classmethod
    def normalize_oss_object_prefix(cls, value: str) -> str:
        normalized = value.strip().strip("/")
        if not normalized or ".." in normalized.split("/"):
            raise ValueError("OSS object prefix must be a safe, non-empty path prefix")
        return normalized

    @model_validator(mode="after")
    def validate_rag_candidate_limits(self) -> "Settings":
        if self.rag_top_k > self.rag_candidate_k:
            raise ValueError("rag_top_k must not exceed rag_candidate_k")
        return self

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.environment.casefold() != "production":
            return self
        if self.debug:
            raise ValueError("Debug mode must be disabled in production")
        if self.jwt_secret is None or len(self.jwt_secret.get_secret_value()) < 32:
            raise ValueError("Production JWT secret must contain at least 32 characters")
        if "nxtrep:nxtrep@" in self.database_url.casefold():
            raise ValueError("Default database credentials are forbidden in production")
        unsafe_origins = {
            origin
            for origin in self.cors_origins
            if origin == "*" or "localhost" in origin or "127.0.0.1" in origin
        }
        if unsafe_origins:
            raise ValueError("Production CORS origins must be explicit non-local origins")
        return self

    def require_oss_configuration(self) -> OssConfiguration:
        """Return validated OSS settings only when an OSS-backed feature is used."""
        if self.storage_provider != "aliyun_oss":
            raise StorageConfigurationError("NXTREP_STORAGE_PROVIDER must be set to aliyun_oss")

        required = {
            "NXTREP_OSS_REGION": self.oss_region,
            "NXTREP_OSS_ENDPOINT": self.oss_endpoint,
            "NXTREP_OSS_BUCKET": self.oss_bucket,
            "NXTREP_OSS_ACCESS_KEY_ID": self.oss_access_key_id,
            "NXTREP_OSS_ACCESS_KEY_SECRET": self.oss_access_key_secret,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise StorageConfigurationError(
                f"Missing required OSS configuration: {', '.join(missing)}"
            )

        return OssConfiguration(
            region=self.oss_region,
            endpoint=self.oss_endpoint,
            use_cname=self.oss_use_cname,
            bucket=self.oss_bucket,
            access_key_id=self.oss_access_key_id,
            access_key_secret=self.oss_access_key_secret,
            object_prefix=self.oss_object_prefix,
            upload_url_expire_seconds=self.oss_upload_url_expire_seconds,
            download_url_expire_seconds=self.oss_download_url_expire_seconds,
            image_max_bytes=self.image_max_bytes,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
