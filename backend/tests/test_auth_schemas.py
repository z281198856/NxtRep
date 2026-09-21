from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.schemas.auth import (
    AuthUserResponse,
    LoginRequest,
    PasswordSetupRequest,
    RefreshTokenRequest,
    TokenPairResponse,
)


def test_login_request_normalizes_username_and_device() -> None:
    request = LoginRequest(
        username="  zengsiqi  ",
        password=" password-with-spaces ",
        device_name="  iPhone  ",
    )

    assert request.username == "zengsiqi"
    assert request.password == " password-with-spaces "
    assert request.device_name == "iPhone"


def test_blank_username_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(
            username="   ",
            password="password",
        )


def test_short_new_password_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PasswordSetupRequest(
            username="zengsiqi",
            setup_token="a" * 64,
            new_password="short",
        )


def test_short_refresh_token_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RefreshTokenRequest(refresh_token="short")


def test_token_pair_response() -> None:
    user_id = uuid4()

    response = TokenPairResponse(
        access_token="access-token",
        refresh_token="r" * 64,
        expires_in=900,
        refresh_expires_in=2_592_000,
        user=AuthUserResponse(
            id=user_id,
            username="zengsiqi",
            password_setup_required=False,
        ),
    )

    assert response.token_type == "bearer"
    assert response.expires_in == 900
    assert response.refresh_expires_in == 2_592_000
    assert response.user.id == user_id
