import base64
from uuid import uuid4

import pytest

from nxtrep_backend.agents.vision import build_glm_vision_content
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_media import ResolvedAgentImage


def make_image(
    *,
    data: bytes,
    content_type: str,
    purpose: ImagePurpose,
) -> ResolvedAgentImage:
    return ResolvedAgentImage(
        asset_id=uuid4(),
        purpose=purpose,
        content_type=content_type,
        data=data,
    )


def test_builder_creates_glm_data_uri_content_in_image_order() -> None:
    jpeg = make_image(
        data=b"jpeg-bytes",
        content_type="image/jpeg",
        purpose=ImagePurpose.BODY_PROGRESS,
    )
    png = make_image(
        data=b"png-bytes",
        content_type="image/png",
        purpose=ImagePurpose.NUTRITION_ENTRY,
    )

    content = build_glm_vision_content(
        question="比较身体变化并估算这顿饭的营养",
        images=[jpeg, png],
    )

    assert content[0]["type"] == "text"
    assert "比较身体变化并估算这顿饭的营养" in content[0]["text"]
    assert "body_progress" in content[0]["text"]
    assert "nutrition_entry" in content[0]["text"]
    assert content[1] == {
        "type": "image_url",
        "image_url": {
            "url": ("data:image/jpeg;base64," + base64.b64encode(b"jpeg-bytes").decode("ascii"))
        },
    }
    assert content[2] == {
        "type": "image_url",
        "image_url": {
            "url": ("data:image/png;base64," + base64.b64encode(b"png-bytes").decode("ascii"))
        },
    }


def test_builder_does_not_expose_asset_ids_or_oss_object_keys() -> None:
    image = make_image(
        data=b"private-image",
        content_type="image/webp",
        purpose=ImagePurpose.CHAT_ATTACHMENT,
    )

    content = build_glm_vision_content(
        question="描述图片",
        images=[image],
    )
    serialized = str(content)

    assert str(image.asset_id) not in serialized
    assert "oss" not in serialized.lower()
    assert "object_key" not in serialized


def test_builder_rejects_empty_image_collection() -> None:
    with pytest.raises(ValueError, match="At least one image"):
        build_glm_vision_content(question="分析图片", images=[])


def test_builder_rejects_blank_question() -> None:
    image = make_image(
        data=b"private-image",
        content_type="image/jpeg",
        purpose=ImagePurpose.BODY_PROGRESS,
    )

    with pytest.raises(ValueError, match="question"):
        build_glm_vision_content(question="   ", images=[image])
