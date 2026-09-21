from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID

import alibabacloud_oss_v2 as oss

from nxtrep_backend.core.config import OssConfiguration, Settings

_IMAGE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


class StorageProviderError(RuntimeError):
    """Base error for storage provider failures."""


class ImageValidationError(StorageProviderError):
    """Raised when image metadata or an object key violates upload rules."""


class ImageObjectNotFoundError(StorageProviderError):
    """Raised when an expected OSS object does not exist."""


@dataclass(frozen=True)
class PresignedImageRequest:
    object_key: str
    method: Literal["PUT", "GET"]
    url: str
    expires_at: datetime
    headers: Mapping[str, str]


@dataclass(frozen=True)
class ImageObjectMetadata:
    object_key: str
    content_length: int
    content_type: str
    etag: str | None
    last_modified: datetime | None


class ImageStorageProvider(Protocol):
    def create_object_key(self, owner_id: UUID, asset_id: UUID, content_type: str) -> str: ...

    def presign_upload(
        self, object_key: str, content_type: str, content_length: int
    ) -> PresignedImageRequest: ...

    def presign_download(self, object_key: str) -> PresignedImageRequest: ...

    async def verify_image(
        self,
        object_key: str,
        *,
        expected_content_type: str | None = None,
        expected_content_length: int | None = None,
    ) -> ImageObjectMetadata: ...

    async def download_image(
        self,
        object_key: str,
    ) -> bytes: ...

    async def replace_image(
        self,
        object_key: str,
        data: bytes,
        *,
        content_type: str,
    ) -> ImageObjectMetadata: ...


class _OssClient(Protocol):
    def presign(self, request: Any, **kwargs: Any) -> Any: ...

    def head_object(self, request: Any, **kwargs: Any) -> Any: ...

    def get_object(self, request: Any, **kwargs: Any) -> Any: ...

    def put_object(self, request: Any, **kwargs: Any) -> Any: ...


def _find_service_error(error: BaseException) -> oss.exceptions.ServiceError | None:
    current: BaseException | None = error
    for _ in range(6):
        if current is None:
            return None
        if isinstance(current, oss.exceptions.ServiceError):
            return current
        unwrap = getattr(current, "unwrap", None)
        unwrapped = unwrap() if callable(unwrap) else None
        current = unwrapped if isinstance(unwrapped, BaseException) else current.__cause__
    return None


class AliyunOssImageStorageProvider:
    """Private-image storage backed by Alibaba Cloud OSS SDK V2."""

    def __init__(self, configuration: OssConfiguration, client: _OssClient | None = None):
        self._configuration = configuration
        self._client = client or self._build_client(configuration)

    @staticmethod
    def _build_client(configuration: OssConfiguration) -> oss.Client:
        credentials = oss.credentials.StaticCredentialsProvider(
            access_key_id=configuration.access_key_id.get_secret_value(),
            access_key_secret=configuration.access_key_secret.get_secret_value(),
        )
        sdk_configuration = oss.config.Config(
            region=configuration.region,
            endpoint=str(configuration.endpoint).rstrip("/"),
            signature_version="v4",
            credentials_provider=credentials,
            retry_max_attempts=3,
            connect_timeout=10,
            readwrite_timeout=30,
            use_cname=configuration.use_cname,
        )
        return oss.Client(sdk_configuration)

    def create_object_key(self, owner_id: UUID, asset_id: UUID, content_type: str) -> str:
        extension = self._extension_for(content_type)
        return f"{self._configuration.object_prefix}/{owner_id}/{asset_id}.{extension}"

    def presign_upload(
        self, object_key: str, content_type: str, content_length: int
    ) -> PresignedImageRequest:
        normalized_key = self._validate_object_key(object_key)
        normalized_type = self._validate_image_input(content_type, content_length)
        request = oss.PutObjectRequest(
            bucket=self._configuration.bucket,
            key=normalized_key,
            content_type=normalized_type,
            content_length=content_length,
            forbid_overwrite=True,
        )
        return self._presign(
            request,
            object_key=normalized_key,
            method="PUT",
            expires_seconds=self._configuration.upload_url_expire_seconds,
        )

    def presign_download(self, object_key: str) -> PresignedImageRequest:
        normalized_key = self._validate_object_key(object_key)
        request = oss.GetObjectRequest(
            bucket=self._configuration.bucket,
            key=normalized_key,
        )
        return self._presign(
            request,
            object_key=normalized_key,
            method="GET",
            expires_seconds=self._configuration.download_url_expire_seconds,
        )

    async def verify_image(
        self,
        object_key: str,
        *,
        expected_content_type: str | None = None,
        expected_content_length: int | None = None,
    ) -> ImageObjectMetadata:
        normalized_key = self._validate_object_key(object_key)
        request = oss.HeadObjectRequest(
            bucket=self._configuration.bucket,
            key=normalized_key,
        )
        try:
            result = await asyncio.to_thread(self._client.head_object, request)
        except oss.exceptions.BaseError as exc:
            service_error = _find_service_error(exc)
            if service_error is not None and (
                service_error.status_code == 404 or service_error.code in {"NoSuchKey", "NotFound"}
            ):
                raise ImageObjectNotFoundError(
                    f"OSS image object does not exist: {normalized_key}"
                ) from exc
            if service_error is not None:
                raise StorageProviderError(
                    "OSS HeadObject failed with status "
                    f"{service_error.status_code} ({service_error.code or 'unknown'})"
                ) from exc
            raise StorageProviderError("OSS HeadObject request failed") from exc

        content_length = result.content_length
        content_type = self._normalize_content_type(result.content_type)
        if content_length is None or content_length <= 0:
            raise ImageValidationError("OSS image has an invalid or missing content length")
        self._validate_image_input(content_type, content_length)

        if expected_content_type is not None:
            expected_type = self._normalize_content_type(expected_content_type)
            if content_type != expected_type:
                raise ImageValidationError(
                    f"OSS image content type mismatch: expected {expected_type}, got {content_type}"
                )
        if expected_content_length is not None and content_length != expected_content_length:
            raise ImageValidationError("OSS image content length does not match the upload intent")

        return ImageObjectMetadata(
            object_key=normalized_key,
            content_length=content_length,
            content_type=content_type,
            etag=result.etag,
            last_modified=result.last_modified,
        )

    def _presign(
        self,
        request: Any,
        *,
        object_key: str,
        method: Literal["PUT", "GET"],
        expires_seconds: int,
    ) -> PresignedImageRequest:
        try:
            result = self._client.presign(request, expires=timedelta(seconds=expires_seconds))
        except oss.exceptions.BaseError as exc:
            raise StorageProviderError(f"OSS {method} URL signing failed") from exc

        if (
            result.method != method
            or not result.url
            or not result.url.startswith("https://")
            or result.expiration is None
        ):
            raise StorageProviderError(f"OSS returned an invalid {method} presigned request")

        headers = {str(name): str(value) for name, value in (result.signed_headers or {}).items()}
        return PresignedImageRequest(
            object_key=object_key,
            method=method,
            url=result.url,
            expires_at=result.expiration,
            headers=headers,
        )

    def _validate_object_key(self, object_key: str) -> str:
        normalized = object_key.strip().strip("/")
        segments = normalized.split("/")
        expected_prefix = f"{self._configuration.object_prefix}/"
        if not normalized.startswith(expected_prefix) or any(
            segment in {"", ".", ".."} for segment in segments
        ):
            raise ImageValidationError("Image object key is outside the configured OSS prefix")
        return normalized

    def _validate_image_input(self, content_type: str, content_length: int) -> str:
        normalized_type = self._normalize_content_type(content_type)
        self._extension_for(normalized_type)
        if content_length <= 0 or content_length > self._configuration.image_max_bytes:
            raise ImageValidationError(
                f"Image size must be between 1 and {self._configuration.image_max_bytes} bytes"
            )
        return normalized_type

    async def download_image(
        self,
        object_key: str,
    ) -> bytes:
        normalized_key = self._validate_object_key(object_key)

        request = oss.GetObjectRequest(
            bucket=self._configuration.bucket,
            key=normalized_key,
        )

        try:
            result = await asyncio.to_thread(
                self._client.get_object,
                request,
            )
        except oss.exceptions.BaseError as exc:
            service_error = _find_service_error(exc)

            if service_error is not None and (
                service_error.status_code == 404 or service_error.code in {"NoSuchKey", "NotFound"}
            ):
                raise ImageObjectNotFoundError(
                    f"OSS image object does not exist: {normalized_key}"
                ) from exc

            raise StorageProviderError("OSS GetObject request failed") from exc

        body = result.body

        if body is None:
            raise StorageProviderError("OSS GetObject response has no body")

        content_length = result.content_length

        if (
            content_length is None
            or content_length <= 0
            or content_length > self._configuration.image_max_bytes
        ):
            await asyncio.to_thread(body.close)
            raise ImageValidationError("OSS image download size is outside the allowed range")

        try:
            data = await asyncio.to_thread(
                self._read_stream_body,
                body,
            )
        except Exception as exc:
            raise StorageProviderError("OSS image body could not be read") from exc

        if len(data) != content_length:
            raise ImageValidationError("OSS image body length does not match object metadata")

        return data

    async def replace_image(
        self,
        object_key: str,
        data: bytes,
        *,
        content_type: str,
    ) -> ImageObjectMetadata:
        normalized_key = self._validate_object_key(object_key)
        normalized_type = self._validate_image_input(
            content_type,
            len(data),
        )

        request = oss.PutObjectRequest(
            bucket=self._configuration.bucket,
            key=normalized_key,
            body=data,
            content_type=normalized_type,
            content_length=len(data),
            metadata={
                "nxtrep-sanitized": "true",
            },
        )

        try:
            result = await asyncio.to_thread(
                self._client.put_object,
                request,
            )
        except oss.exceptions.BaseError as exc:
            raise StorageProviderError("OSS sanitized image upload failed") from exc

        return ImageObjectMetadata(
            object_key=normalized_key,
            content_length=len(data),
            content_type=normalized_type,
            etag=result.etag,
            last_modified=None,
        )

    @staticmethod
    def _normalize_content_type(content_type: str | None) -> str:
        return (content_type or "").split(";", maxsplit=1)[0].strip().lower()

    @staticmethod
    def _extension_for(content_type: str) -> str:
        try:
            return _IMAGE_EXTENSIONS[content_type]
        except KeyError as exc:
            raise ImageValidationError("Only JPEG, PNG and WebP images are accepted") from exc

    @staticmethod
    def _read_stream_body(body: Any) -> bytes:
        with body:
            return body.read()


def build_image_storage_provider(settings: Settings) -> AliyunOssImageStorageProvider:
    return AliyunOssImageStorageProvider(settings.require_oss_configuration())
