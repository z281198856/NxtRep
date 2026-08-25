from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.schemas.admin import (
    AdminUserCreateRequest,
    AdminUserCreateResponse,
)


def test_admin_user_create_request_normalizes_fields() -> None:
    request = AdminUserCreateRequest(
        username="  zengsiqi  ",
        display_name="  Zeng  ",
    )

    assert request.username == "zengsiqi"
    assert request.display_name == "Zeng"
    assert request.is_admin is False


def test_blank_username_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AdminUserCreateRequest(
            username="   ",
            display_name="Zeng",
        )


def test_admin_user_create_response_serializes() -> None:
    user_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(minutes=30)

    response = AdminUserCreateResponse(
        id=user_id,
        username="zengsiqi",
        display_name="Zeng",
        is_admin=False,
        password_setup_required=True,
        setup_token="s" * 64,
        setup_token_expires_at=expires_at,
    )

    data = response.model_dump(mode="json")

    assert data["id"] == str(user_id)
    assert data["username"] == "zengsiqi"
    assert data["setup_token"] == "s" * 64
    assert data["setup_token_expires_at"].endswith("Z")
