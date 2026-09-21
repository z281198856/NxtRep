from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import alibabacloud_oss_v2 as oss
import pytest
from pydantic import SecretStr

from nxtrep_backend.core.config import OssConfiguration
from nxtrep_backend.providers.storage import (
    AliyunOssImageStorageProvider,
    ImageObjectNotFoundError,
    ImageValidationError,
)


def _configuration() -> OssConfiguration:
    return OssConfiguration(
        region="cn-hongkong",
        endpoint="https://oss-cn-hongkong.aliyuncs.com",
        use_cname=False,
        bucket="nxtrep-images-dev-test",
        access_key_id=SecretStr("test-access-key-id"),
        access_key_secret=SecretStr("test-access-key-secret"),
        object_prefix="images",
        upload_url_expire_seconds=600,
        download_url_expire_seconds=300,
        image_max_bytes=10 * 1024 * 1024,
    )


class _FakeHeadClient:
    def __init__(self, result: object | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.request: object | None = None

    def presign(self, request: object, **kwargs: object) -> object:
        raise AssertionError("presign is not expected in this test")

    def head_object(self, request: object, **kwargs: object) -> object:
        self.request = request
        if self.error is not None:
            raise self.error
        return self.result


class _FakeStreamBody:
    def __init__(self, data: bytes):
        self._data = data
        self.closed = False

    def __enter__(self) -> "_FakeStreamBody":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def read(self) -> bytes:
        return self._data

    def close(self) -> None:
        self.closed = True


class _FakeObjectClient:
    def __init__(
        self,
        *,
        get_result: object | None = None,
        put_result: object | None = None,
    ) -> None:
        self.get_result = get_result
        self.put_result = put_result
        self.get_request: object | None = None
        self.put_request: object | None = None

    def presign(self, request: object, **kwargs: object) -> object:
        raise AssertionError("presign is not expected in this test")

    def head_object(self, request: object, **kwargs: object) -> object:
        raise AssertionError("head_object is not expected in this test")

    def get_object(self, request: object, **kwargs: object) -> object:
        self.get_request = request
        return self.get_result

    def put_object(self, request: object, **kwargs: object) -> object:
        self.put_request = request
        return self.put_result


def test_real_sdk_generates_v4_put_and_get_presigned_urls_without_network() -> None:
    provider = AliyunOssImageStorageProvider(_configuration())
    object_key = provider.create_object_key(uuid4(), uuid4(), "image/jpeg")

    upload = provider.presign_upload(object_key, "image/jpeg", 1024)
    download = provider.presign_download(object_key)

    assert upload.method == "PUT"
    assert upload.object_key == object_key
    assert "x-oss-signature-version=OSS4-HMAC-SHA256" in upload.url
    assert "test-access-key-secret" not in upload.url
    assert upload.headers["Content-Type"] == "image/jpeg"
    assert upload.headers["x-oss-forbid-overwrite"] == "true"
    assert download.method == "GET"
    assert "x-oss-signature-version=OSS4-HMAC-SHA256" in download.url


def test_object_key_uses_private_ids_instead_of_original_filename() -> None:
    provider = AliyunOssImageStorageProvider(_configuration())
    owner_id = uuid4()
    asset_id = uuid4()

    assert provider.create_object_key(owner_id, asset_id, "image/png") == (
        f"images/{owner_id}/{asset_id}.png"
    )


@pytest.mark.parametrize("content_type", ["text/plain", "image/gif", "video/mp4"])
def test_upload_rejects_non_supported_image_types(content_type: str) -> None:
    provider = AliyunOssImageStorageProvider(_configuration())

    with pytest.raises(ImageValidationError, match="Only JPEG, PNG and WebP"):
        provider.presign_upload("images/user/asset.bin", content_type, 100)


def test_upload_rejects_oversized_image() -> None:
    configuration = _configuration().model_copy(update={"image_max_bytes": 100})
    provider = AliyunOssImageStorageProvider(configuration)

    with pytest.raises(ImageValidationError, match="Image size must be"):
        provider.presign_upload("images/user/asset.jpg", "image/jpeg", 101)


def test_storage_rejects_object_key_outside_private_prefix() -> None:
    provider = AliyunOssImageStorageProvider(_configuration())

    with pytest.raises(ImageValidationError, match="outside the configured OSS prefix"):
        provider.presign_download("public/asset.jpg")


@pytest.mark.asyncio
async def test_verify_image_checks_head_metadata_against_upload_intent() -> None:
    result = SimpleNamespace(
        content_length=2048,
        content_type="image/jpeg",
        etag="etag-value",
        last_modified=datetime(2026, 8, 28, tzinfo=UTC),
    )
    client = _FakeHeadClient(result=result)
    provider = AliyunOssImageStorageProvider(_configuration(), client=client)

    metadata = await provider.verify_image(
        "images/user/asset.jpg",
        expected_content_type="image/jpeg",
        expected_content_length=2048,
    )

    assert metadata.content_length == 2048
    assert metadata.content_type == "image/jpeg"
    assert metadata.etag == "etag-value"
    assert isinstance(client.request, oss.HeadObjectRequest)


@pytest.mark.asyncio
async def test_verify_image_rejects_metadata_mismatch() -> None:
    result = SimpleNamespace(
        content_length=1024,
        content_type="image/png",
        etag=None,
        last_modified=None,
    )
    provider = AliyunOssImageStorageProvider(
        _configuration(), client=_FakeHeadClient(result=result)
    )

    with pytest.raises(ImageValidationError, match="content type mismatch"):
        await provider.verify_image(
            "images/user/asset.png",
            expected_content_type="image/jpeg",
            expected_content_length=1024,
        )


@pytest.mark.asyncio
async def test_verify_image_maps_oss_not_found_error() -> None:
    service_error = oss.exceptions.ServiceError(
        status_code=404,
        code="NoSuchKey",
        request_id="test-request-id",
        message="The specified key does not exist.",
        ec="0026-00000001",
        timestamp="2026-08-28T00:00:00Z",
        request_target="test-bucket.oss-cn-hongkong.aliyuncs.com/images/user/missing.jpg",
    )
    error = oss.exceptions.OperationError(name="HeadObject", error=service_error)
    provider = AliyunOssImageStorageProvider(_configuration(), client=_FakeHeadClient(error=error))

    with pytest.raises(ImageObjectNotFoundError, match="does not exist"):
        await provider.verify_image("images/user/missing.jpg")


@pytest.mark.asyncio
async def test_download_image_reads_and_closes_private_oss_stream() -> None:
    data = b"sanitization input"
    body = _FakeStreamBody(data)
    client = _FakeObjectClient(
        get_result=SimpleNamespace(
            body=body,
            content_length=len(data),
            content_type="image/jpeg",
        )
    )
    provider = AliyunOssImageStorageProvider(_configuration(), client=client)

    result = await provider.download_image("images/user/asset.jpg")

    assert result == data
    assert body.closed is True
    assert isinstance(client.get_request, oss.GetObjectRequest)


@pytest.mark.asyncio
async def test_download_image_closes_stream_before_rejecting_oversized_object() -> None:
    body = _FakeStreamBody(b"not read")
    configuration = _configuration().model_copy(update={"image_max_bytes": 8})
    client = _FakeObjectClient(
        get_result=SimpleNamespace(
            body=body,
            content_length=9,
            content_type="image/jpeg",
        )
    )
    provider = AliyunOssImageStorageProvider(configuration, client=client)

    with pytest.raises(ImageValidationError, match="download size"):
        await provider.download_image("images/user/asset.jpg")

    assert body.closed is True


@pytest.mark.asyncio
async def test_replace_image_uploads_sanitized_bytes_and_returns_new_metadata() -> None:
    data = b"sanitized image bytes"
    client = _FakeObjectClient(
        put_result=SimpleNamespace(etag="sanitized-etag"),
    )
    provider = AliyunOssImageStorageProvider(_configuration(), client=client)

    metadata = await provider.replace_image(
        "images/user/asset.jpg",
        data,
        content_type="image/jpeg",
    )

    assert metadata.object_key == "images/user/asset.jpg"
    assert metadata.content_length == len(data)
    assert metadata.content_type == "image/jpeg"
    assert metadata.etag == "sanitized-etag"
    assert isinstance(client.put_request, oss.PutObjectRequest)
    assert client.put_request.body == data
    assert client.put_request.content_length == len(data)
    assert client.put_request.content_type == "image/jpeg"
    assert client.put_request.forbid_overwrite is None
