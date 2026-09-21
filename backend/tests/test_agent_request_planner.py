from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.intent_router import AgentIntentRouter
from nxtrep_backend.schemas.agent import (
    AgentChatRequest,
    AgentIntentPlan,
    AgentIntentTask,
)
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_context import AgentContextAssembler
from nxtrep_backend.services.agent_media import (
    AgentImageAssetResolver,
    ResolvedAgentImage,
)
from nxtrep_backend.services.agent_planning import AgentRequestPlanner
from nxtrep_backend.services.conversation import AgentConversationContext


def make_plan(task_type: str) -> AgentIntentPlan:
    return AgentIntentPlan(
        tasks=[
            AgentIntentTask(
                task_type=task_type,
                confidence="high",
                routing_reason="测试请求规划。",
            )
        ]
    )


def make_dependencies() -> tuple[MagicMock, MagicMock, MagicMock]:
    resolver = MagicMock(spec=AgentImageAssetResolver)
    resolver.resolve = AsyncMock()
    intent_router = MagicMock(spec=AgentIntentRouter)
    intent_router.route = AsyncMock()
    context_assembler = MagicMock(spec=AgentContextAssembler)
    context_assembler.load_memories = AsyncMock(return_value=())
    return resolver, intent_router, context_assembler


@pytest.mark.asyncio
async def test_text_request_skips_image_resolution() -> None:
    resolver, intent_router, context_assembler = make_dependencies()
    expected = make_plan("general_question")
    intent_router.route.return_value = expected
    planner = AgentRequestPlanner(
        resolver=resolver,
        intent_router=intent_router,
        context_assembler=context_assembler,
    )
    conversation_context = AgentConversationContext()
    user_id = uuid4()
    request = AgentChatRequest(message="深蹲时怎么呼吸？")

    result = await planner.plan(
        user_id=user_id,
        request=request,
        conversation_context=conversation_context,
    )

    assert result.images == ()
    assert result.intent_plan == expected
    assert result.memories == ()
    resolver.resolve.assert_not_awaited()
    intent_router.route.assert_awaited_once_with(
        message="深蹲时怎么呼吸？",
        images=[],
        conversation_context=conversation_context,
        context_hints=request.context_hints,
    )
    context_assembler.load_memories.assert_awaited_once_with(
        user_id=user_id,
        intent_plan=expected,
    )


@pytest.mark.asyncio
async def test_image_request_resolves_once_and_reuses_same_images() -> None:
    resolver, intent_router, context_assembler = make_dependencies()
    user_id = uuid4()
    asset_id = uuid4()
    image = ResolvedAgentImage(
        asset_id=asset_id,
        purpose=ImagePurpose.BODY_PROGRESS,
        content_type="image/jpeg",
        data=b"sanitized-body-image",
    )
    resolved_images = [image]
    expected = AgentIntentPlan(
        tasks=[
            AgentIntentTask(
                task_type="body_assessment",
                asset_ids=[asset_id],
                confidence="high",
                routing_reason="用户请求分析身体照片。",
            )
        ]
    )
    resolver.resolve.return_value = resolved_images
    intent_router.route.return_value = expected
    planner = AgentRequestPlanner(
        resolver=resolver,
        intent_router=intent_router,
        context_assembler=context_assembler,
    )
    request = AgentChatRequest(
        message="分析我的体态",
        image_asset_ids=[asset_id],
    )
    conversation_context = AgentConversationContext()

    result = await planner.plan(
        user_id=user_id,
        request=request,
        conversation_context=conversation_context,
    )

    resolver.resolve.assert_awaited_once_with(
        user_id=user_id,
        asset_ids=[asset_id],
    )
    intent_router.route.assert_awaited_once_with(
        message=request.message,
        images=resolved_images,
        conversation_context=conversation_context,
        context_hints=request.context_hints,
    )
    assert result.images == (image,)
    assert result.intent_plan == expected
