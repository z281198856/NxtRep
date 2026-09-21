from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AllowedImageContentType = Literal[
    "image/jpeg",
    "image/png",
    "image/webp",
]
MAX_IMAGE_UPLOAD_BYTES = 50 * 1024 * 1024


# 1. 图片用途
class ImagePurpose(StrEnum):
    CHAT_ATTACHMENT = "chat_attachment"
    NUTRITION_ENTRY = "nutrition_entry"
    BODY_PROGRESS = "body_progress"
    TRAINING_PLAN = "training_plan"


# 2. 图片生命周期状态
class ImageStatus(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    UPLOADED = "uploaded"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"


# 3. 前端申请上传地址时提交的数据
class ImageUploadIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: ImagePurpose
    content_type: AllowedImageContentType
    content_length: int = Field(gt=0, le=MAX_IMAGE_UPLOAD_BYTES)


class ImageUploadCapabilitiesResponse(BaseModel):
    """Runtime limits a mobile client needs before preparing a camera image."""

    model_config = ConfigDict(extra="forbid")

    accepted_content_types: list[AllowedImageContentType]
    preferred_content_type: AllowedImageContentType
    convert_before_upload: list[Literal["image/heic", "image/heif"]]
    max_bytes: int = Field(gt=0)
    max_pixels: int = Field(gt=0)
    max_dimension: int = Field(gt=0)
    direct_upload_method: Literal["PUT"]
    upload_url_expires_in: int = Field(gt=0)


# 4. 后端返回给前端的 OSS 上传信息
class ImageUploadIntentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    method: Literal["PUT"]
    upload_url: str
    headers: dict[str, str]
    expires_at: datetime
    status: ImageStatus


class ImageDownloadIntentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["GET"]
    download_url: str
    headers: dict[str, str]
    expires_at: datetime


# 5. 前端上传 OSS 完成后提交的数据
class ImageUploadCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_content_type: AllowedImageContentType
    expected_content_length: int = Field(gt=0, le=MAX_IMAGE_UPLOAD_BYTES)


# 6. 返回给前端的图片资产信息
class ImageAssetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    purpose: ImagePurpose
    content_type: AllowedImageContentType
    content_length: int = Field(gt=0)
    status: ImageStatus
    created_at: datetime
    completed_at: datetime | None = None
    failure_reason: str | None = None
