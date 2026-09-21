import pytest
from pydantic import SecretStr, ValidationError

from nxtrep_backend.core.config import Settings
from nxtrep_backend.core.security import hash_password, verify_password


def test_hash_password_does_not_store_plaintext() -> None:
    password = "example_password_123"

    first_hash = hash_password(password)
    second_hash = hash_password(password)

    assert first_hash != password
    assert password not in first_hash
    assert first_hash != second_hash


def test_verify_password_accepts_correct_password() -> None:
    password = "example_password_123"
    password_hash = hash_password(password)

    assert verify_password(password, password_hash) is True


def test_verify_password_rejects_wrong_password() -> None:
    password_hash = hash_password("correct_password")

    assert verify_password("wrong_password", password_hash) is False
    assert verify_password("wrong_password", "invalid-hash") is False


def test_production_configuration_rejects_insecure_defaults() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production")


def test_production_configuration_accepts_explicit_secure_values() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        debug=False,
        jwt_secret=SecretStr("production-secret-" * 3),
        database_url="postgresql+asyncpg://app:strong-password@db:5432/nxtrep",
        cors_origins=["https://app.example.com"],
    )
    assert settings.environment == "production"
