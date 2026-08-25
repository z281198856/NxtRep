from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from pydantic import SecretStr

from nxtrep_backend.core.config import Settings
from nxtrep_backend.core.tokens import (
    JWT_ALGORITHM,
    AuthConfigurationError,
    InvalidAccessTokenError,
    create_access_token,
    create_opaque_token,
    decode_access_token,
    hash_opaque_token,
)

TEST_SECRET = "unit-test-secret-" * 4


def make_settings(secret: str | None = TEST_SECRET) -> Settings:
    return Settings(
        _env_file=None,
        jwt_secret=SecretStr(secret) if secret is not None else None,
        access_token_expire_minutes=15,
    )


def test_access_token_round_trip() -> None:
    settings = make_settings()
    user_id = uuid4()

    token = create_access_token(user_id, settings)

    assert isinstance(token, str)
    assert decode_access_token(token, settings) == user_id


def test_tampered_access_token_is_rejected() -> None:
    settings = make_settings()
    token = create_access_token(uuid4(), settings)

    header, payload, _signature = token.split(".")
    tampered_token = f"{header}.{payload}.invalid"

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(tampered_token, settings)


def test_access_token_signed_with_another_secret_is_rejected() -> None:
    first_settings = make_settings("first-test-secret-" * 4)
    second_settings = make_settings("second-test-secret-" * 4)

    token = create_access_token(uuid4(), first_settings)

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, second_settings)


def test_wrong_token_type_is_rejected() -> None:
    settings = make_settings()
    assert settings.jwt_secret is not None

    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(minutes=15),
            "jti": str(uuid4()),
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, settings)


def test_missing_jwt_secret_is_rejected() -> None:
    settings = make_settings(None)

    with pytest.raises(AuthConfigurationError):
        create_access_token(uuid4(), settings)


def test_opaque_tokens_are_random() -> None:
    first_token = create_opaque_token()
    second_token = create_opaque_token()

    assert first_token != second_token
    assert len(first_token) >= 64
    assert len(second_token) >= 64


def test_opaque_token_hash_is_deterministic() -> None:
    token = create_opaque_token()

    first_hash = hash_opaque_token(token)
    second_hash = hash_opaque_token(token)

    assert first_hash == second_hash
    assert first_hash != token
    assert token not in first_hash
    assert len(first_hash) == 64


def test_different_tokens_have_different_hashes() -> None:
    first_token = create_opaque_token()
    second_token = create_opaque_token()

    assert hash_opaque_token(first_token) != hash_opaque_token(second_token)


def test_empty_opaque_token_is_rejected() -> None:
    with pytest.raises(ValueError):
        hash_opaque_token("")
