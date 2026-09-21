from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.schemas.media import (
    ImageAssetResponse,
    ImagePurpose,
    ImageStatus,
    ImageUploadCompleteRequest,
    ImageUploadIntentRequest,
    ImageUploadIntentResponse,
)


def test_valid_image_upload_intent_is_accepted() -> None:
    request = ImageUploadIntentRequest(
        purpose="nutrition_entry",
        content_type="image/jpeg",
        content_length=2048,
    )

    assert request.purpose == ImagePurpose.NUTRITION_ENTRY
    assert request.content_type == "image/jpeg"
    assert request.content_length == 2048


@pytest.mark.parametrize("content_type", ["text/plain", "image/gif", "video/mp4"])
def test_upload_intent_rejects_unsupported_media_types(content_type: str) -> None:
    with pytest.raises(ValidationError):
        ImageUploadIntentRequest(
            purpose="chat_attachment",
            content_type=content_type,
            content_length=2048,
        )


@pytest.mark.parametrize("content_length", [0, -1])
def test_upload_intent_rejects_non_positive_content_length(content_length: int) -> None:
    with pytest.raises(ValidationError):
        ImageUploadIntentRequest(
            purpose="chat_attachment",
            content_type="image/png",
            content_length=content_length,
        )


def test_upload_intent_rejects_unknown_purpose() -> None:
    with pytest.raises(ValidationError):
        ImageUploadIntentRequest(
            purpose="profile_avatar",
            content_type="image/webp",
            content_length=1024,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", str(uuid4())),
        ("object_key", "images/another-user/private.jpg"),
        ("status", "ready"),
    ],
)
def test_upload_intent_forbids_server_owned_fields(field: str, value: str) -> None:
    payload = {
        "purpose": "body_progress",
        "content_type": "image/jpeg",
        "content_length": 1024,
        field: value,
    }

    with pytest.raises(ValidationError):
        ImageUploadIntentRequest.model_validate(payload)


def test_upload_intent_response_serializes_client_upload_contract() -> None:
    asset_id = uuid4()
    expires_at = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)
    response = ImageUploadIntentResponse(
        asset_id=asset_id,
        method="PUT",
        upload_url="https://example.oss-cn-hongkong.aliyuncs.com/image.jpg?signature=test",
        headers={
            "Content-Type": "image/jpeg",
            "x-oss-forbid-overwrite": "true",
        },
        expires_at=expires_at,
        status="pending_upload",
    )

    payload = response.model_dump(mode="json")

    assert payload == {
        "asset_id": str(asset_id),
        "method": "PUT",
        "upload_url": ("https://example.oss-cn-hongkong.aliyuncs.com/image.jpg?signature=test"),
        "headers": {
            "Content-Type": "image/jpeg",
            "x-oss-forbid-overwrite": "true",
        },
        "expires_at": "2026-08-28T10:00:00Z",
        "status": "pending_upload",
    }


def test_upload_complete_request_accepts_expected_metadata_only() -> None:
    request = ImageUploadCompleteRequest(
        expected_content_type="image/png",
        expected_content_length=4096,
    )

    assert request.expected_content_type == "image/png"
    assert request.expected_content_length == 4096

    with pytest.raises(ValidationError):
        ImageUploadCompleteRequest.model_validate(
            {
                "expected_content_type": "image/png",
                "expected_content_length": 4096,
                "object_key": "images/another-user/private.png",
            }
        )


def test_ready_image_asset_response_serializes_without_storage_credentials() -> None:
    asset_id = uuid4()
    created_at = datetime(2026, 8, 28, 9, 55, tzinfo=UTC)
    completed_at = datetime(2026, 8, 28, 9, 56, tzinfo=UTC)
    response = ImageAssetResponse(
        id=asset_id,
        purpose="nutrition_entry",
        content_type="image/jpeg",
        content_length=2048,
        status="ready",
        created_at=created_at,
        completed_at=completed_at,
        failure_reason=None,
    )

    payload = response.model_dump(mode="json")

    assert payload["id"] == str(asset_id)
    assert payload["purpose"] == "nutrition_entry"
    assert payload["status"] == "ready"
    assert payload["completed_at"] == "2026-08-28T09:56:00Z"
    assert "object_key" not in payload
    assert "access_key_id" not in payload
    assert "access_key_secret" not in payload


def test_media_enums_define_the_complete_initial_state_space() -> None:
    assert {item.value for item in ImagePurpose} == {
        "chat_attachment",
        "nutrition_entry",
        "body_progress",
        "training_plan",
    }
    assert {item.value for item in ImageStatus} == {
        "pending_upload",
        "uploaded",
        "ready",
        "failed",
        "deleted",
    }
