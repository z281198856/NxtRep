from uuid import uuid4

import pytest
from pydantic import ValidationError

from nxtrep_backend.schemas.agent import AgentChatRequest


def test_agent_chat_request_accepts_ready_image_asset_references() -> None:
    first_asset_id = uuid4()
    second_asset_id = uuid4()

    request = AgentChatRequest(
        message="比较这两张身体照片，告诉我训练变化",
        image_asset_ids=[first_asset_id, second_asset_id],
    )

    assert request.image_asset_ids == [first_asset_id, second_asset_id]


def test_agent_chat_request_defaults_to_text_only() -> None:
    request = AgentChatRequest(message="帮我设计今天的训练")

    assert request.image_asset_ids == []


def test_agent_chat_request_limits_attachment_count() -> None:
    with pytest.raises(ValidationError):
        AgentChatRequest(
            message="分析这些图片",
            image_asset_ids=[uuid4() for _ in range(5)],
        )


def test_agent_chat_request_rejects_duplicate_asset_ids() -> None:
    asset_id = uuid4()

    with pytest.raises(ValidationError, match="must be unique"):
        AgentChatRequest(
            message="分析图片",
            image_asset_ids=[asset_id, asset_id],
        )


def test_agent_chat_request_forbids_client_owned_image_metadata() -> None:
    with pytest.raises(ValidationError):
        AgentChatRequest.model_validate(
            {
                "message": "分析图片",
                "image_asset_ids": [str(uuid4())],
                "image_urls": ["https://untrusted.example/private.jpg"],
            }
        )
