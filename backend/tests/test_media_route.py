from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.api.deps import get_current_user
from nxtrep_backend.api.routes import media as media_route
from nxtrep_backend.db.models import ImageAsset, User
from nxtrep_backend.db.session import get_db_session
from nxtrep_backend.main import app
from nxtrep_backend.providers.image_processing import ImageContentValidationError
from nxtrep_backend.providers.storage import (
    ImageObjectNotFoundError,
    ImageValidationError,
    PresignedImageRequest,
    StorageProviderError,
)
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.media import (
    ImageAssetNotFoundError,
    ImageAssetStateError,
    ImageUploadIntentMismatchError,
    ImageUploadIntentResult,
)

NOW = datetime(2026, 8, 29, 6, 0, tzinfo=UTC)


@pytest.fixture
def client() -> Iterator[TestClient]:
    async def override_db_session() -> AsyncIterator[AsyncSession]:
        yield MagicMock(spec=AsyncSession)

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides[get_db_session] = override_db_session
    storage = MagicMock()
    processor = MagicMock()
    app.dependency_overrides[media_route.get_image_storage_provider] = lambda: storage
    app.dependency_overrides[media_route.get_image_content_processor] = lambda: processor

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db_session, None)
    app.dependency_overrides.pop(media_route.get_image_storage_provider, None)
    app.dependency_overrides.pop(media_route.get_image_content_processor, None)


def make_user() -> User:
    return User(
        id=uuid4(),
        username="media-user",
        password_setup_required=False,
    )


def make_asset(*, user: User, status: str) -> ImageAsset:
    asset_id = uuid4()
    return ImageAsset(
        id=asset_id,
        user_id=user.id,
        purpose="nutrition_entry",
        object_key=f"images/{user.id}/{asset_id}.jpg",
        content_type="image/jpeg",
        content_length=2048,
        status=status,
        upload_expires_at=NOW + timedelta(minutes=10),
        created_at=NOW,
        completed_at=NOW if status != "pending_upload" else None,
    )


def build_upload_service_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> MagicMock:
    upload_service = MagicMock()
    upload_service.create_upload_intent = AsyncMock()
    upload_service.complete_upload = AsyncMock()
    monkeypatch.setattr(
        media_route,
        "ImageAssetService",
        MagicMock(return_value=upload_service),
    )
    return upload_service


def build_processing_service_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> MagicMock:
    processing_service = MagicMock()
    processing_service.process_uploaded_image = AsyncMock()
    monkeypatch.setattr(
        media_route,
        "ImageAssetProcessingService",
        MagicMock(return_value=processing_service),
    )
    return processing_service


def test_image_capabilities_describe_mobile_upload_contract(client: TestClient) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user

    response = client.get("/api/v1/media/images/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "accepted_content_types": ["image/jpeg", "image/png", "image/webp"],
        "preferred_content_type": "image/jpeg",
        "convert_before_upload": ["image/heic", "image/heif"],
        "max_bytes": 10 * 1024 * 1024,
        "max_pixels": 25_000_000,
        "max_dimension": 8192,
        "direct_upload_method": "PUT",
        "upload_url_expires_in": 600,
    }


def test_create_upload_intent_returns_oss_direct_upload_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    asset = make_asset(user=user, status="pending_upload")
    upload = PresignedImageRequest(
        object_key=asset.object_key,
        method="PUT",
        url="https://bucket.oss-cn-hongkong.aliyuncs.com/signed-upload",
        expires_at=asset.upload_expires_at,
        headers={"Content-Type": "image/jpeg"},
    )
    app.dependency_overrides[get_current_user] = lambda: user
    upload_service = build_upload_service_mock(monkeypatch)
    upload_service.create_upload_intent.return_value = ImageUploadIntentResult(
        asset=asset,
        upload=upload,
    )

    response = client.post(
        "/api/v1/media/images/upload-intents",
        json={
            "purpose": "nutrition_entry",
            "content_type": "image/jpeg",
            "content_length": 2048,
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "asset_id": str(asset.id),
        "method": "PUT",
        "upload_url": upload.url,
        "headers": {"Content-Type": "image/jpeg"},
        "expires_at": "2026-08-29T06:10:00Z",
        "status": "pending_upload",
    }
    upload_service.create_upload_intent.assert_awaited_once_with(
        user_id=user.id,
        purpose=ImagePurpose.NUTRITION_ENTRY,
        content_type="image/jpeg",
        content_length=2048,
    )


@pytest.mark.parametrize(
    ("error", "status_code", "error_code"),
    [
        (ImageValidationError(), 422, "IMAGE_UPLOAD_INVALID"),
        (StorageProviderError(), 503, "IMAGE_STORAGE_UNAVAILABLE"),
    ],
)
def test_create_upload_intent_maps_storage_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: RuntimeError,
    status_code: int,
    error_code: str,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    upload_service = build_upload_service_mock(monkeypatch)
    upload_service.create_upload_intent.side_effect = error

    response = client.post(
        "/api/v1/media/images/upload-intents",
        json={
            "purpose": "nutrition_entry",
            "content_type": "image/jpeg",
            "content_length": 2048,
        },
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code


def test_complete_upload_verifies_then_processes_image(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    uploaded_asset = make_asset(user=user, status="uploaded")
    ready_asset = make_asset(user=user, status="ready")
    ready_asset.id = uploaded_asset.id
    ready_asset.object_key = uploaded_asset.object_key
    ready_asset.content_length = 1800
    app.dependency_overrides[get_current_user] = lambda: user
    upload_service = build_upload_service_mock(monkeypatch)
    processing_service = build_processing_service_mock(monkeypatch)
    upload_service.complete_upload.return_value = uploaded_asset
    processing_service.process_uploaded_image.return_value = ready_asset

    response = client.post(
        f"/api/v1/media/images/{uploaded_asset.id}/complete",
        json={
            "expected_content_type": "image/jpeg",
            "expected_content_length": 2048,
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(uploaded_asset.id)
    assert response.json()["status"] == "ready"
    assert response.json()["content_length"] == 1800
    upload_service.complete_upload.assert_awaited_once_with(
        user_id=user.id,
        asset_id=uploaded_asset.id,
        expected_content_type="image/jpeg",
        expected_content_length=2048,
    )
    processing_service.process_uploaded_image.assert_awaited_once_with(
        user_id=user.id,
        asset_id=uploaded_asset.id,
    )


@pytest.mark.parametrize(
    ("error", "status_code", "error_code"),
    [
        (ImageAssetNotFoundError(), 404, "IMAGE_ASSET_NOT_FOUND"),
        (ImageUploadIntentMismatchError(), 409, "IMAGE_UPLOAD_MISMATCH"),
        (ImageAssetStateError(), 409, "IMAGE_ASSET_STATE_INVALID"),
        (ImageObjectNotFoundError(), 409, "IMAGE_UPLOAD_NOT_FOUND"),
        (ImageContentValidationError(), 422, "IMAGE_CONTENT_INVALID"),
        (StorageProviderError(), 503, "IMAGE_STORAGE_UNAVAILABLE"),
    ],
)
def test_complete_upload_maps_media_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: RuntimeError,
    status_code: int,
    error_code: str,
) -> None:
    user = make_user()
    asset_id = uuid4()
    app.dependency_overrides[get_current_user] = lambda: user
    upload_service = build_upload_service_mock(monkeypatch)
    processing_service = build_processing_service_mock(monkeypatch)

    if isinstance(error, ImageContentValidationError):
        upload_service.complete_upload.return_value = make_asset(
            user=user,
            status="uploaded",
        )
        processing_service.process_uploaded_image.side_effect = error
    else:
        upload_service.complete_upload.side_effect = error

    response = client.post(
        f"/api/v1/media/images/{asset_id}/complete",
        json={
            "expected_content_type": "image/jpeg",
            "expected_content_length": 2048,
        },
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code


def test_create_download_intent_returns_private_oss_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    asset = make_asset(user=user, status="ready")
    download = PresignedImageRequest(
        object_key=asset.object_key,
        method="GET",
        url="https://bucket.oss-cn-hongkong.aliyuncs.com/signed-download",
        expires_at=NOW + timedelta(minutes=5),
        headers={"x-oss-test": "signed"},
    )
    app.dependency_overrides[get_current_user] = lambda: user
    service = build_upload_service_mock(monkeypatch)
    service.create_download_intent = AsyncMock(return_value=download)

    response = client.get(
        f"/api/v1/media/images/{asset.id}/download-intent"
    )

    assert response.status_code == 200
    assert response.json() == {
        "method": "GET",
        "download_url": download.url,
        "headers": {"x-oss-test": "signed"},
        "expires_at": "2026-08-29T06:05:00Z",
    }
    service.create_download_intent.assert_awaited_once_with(
        user_id=user.id,
        asset_id=asset.id,
    )


@pytest.mark.parametrize(
    ("error", "status_code", "error_code"),
    [
        (ImageAssetNotFoundError(), 404, "IMAGE_ASSET_NOT_FOUND"),
        (ImageAssetStateError(), 409, "IMAGE_ASSET_STATE_INVALID"),
        (StorageProviderError(), 503, "IMAGE_STORAGE_UNAVAILABLE"),
    ],
)
def test_create_download_intent_maps_media_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: RuntimeError,
    status_code: int,
    error_code: str,
) -> None:
    user = make_user()
    asset_id = uuid4()
    app.dependency_overrides[get_current_user] = lambda: user
    service = build_upload_service_mock(monkeypatch)
    service.create_download_intent = AsyncMock(side_effect=error)

    response = client.get(
        f"/api/v1/media/images/{asset_id}/download-intent"
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code


def test_media_upload_endpoints_require_authentication(client: TestClient) -> None:
    capabilities_response = client.get("/api/v1/media/images/capabilities")
    intent_response = client.post(
        "/api/v1/media/images/upload-intents",
        json={
            "purpose": "chat_attachment",
            "content_type": "image/jpeg",
            "content_length": 2048,
        },
    )
    complete_response = client.post(
        f"/api/v1/media/images/{uuid4()}/complete",
        json={
            "expected_content_type": "image/jpeg",
            "expected_content_length": 2048,
        },
    )
    download_response = client.get(
        f"/api/v1/media/images/{uuid4()}/download-intent"
    )

    assert capabilities_response.status_code == 401
    assert intent_response.status_code == 401
    assert complete_response.status_code == 401
    assert download_response.status_code == 401


def test_upload_intent_rejects_invalid_input_before_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()
    app.dependency_overrides[get_current_user] = lambda: user
    upload_service = build_upload_service_mock(monkeypatch)

    response = client.post(
        "/api/v1/media/images/upload-intents",
        json={
            "purpose": "nutrition_entry",
            "content_type": "image/gif",
            "content_length": 0,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    upload_service.create_upload_intent.assert_not_awaited()


def test_media_upload_endpoints_are_registered_in_openapi(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()

    assert "post" in schema["paths"]["/api/v1/media/images/upload-intents"]
    assert "post" in schema["paths"]["/api/v1/media/images/{asset_id}/complete"]
    assert "get" in schema["paths"]["/api/v1/media/images/capabilities"]
