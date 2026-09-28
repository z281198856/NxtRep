import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from nxtrep_backend.agents.intent_router import (
    AgentIntentRouter,
    AgentIntentRoutingError,
)
from nxtrep_backend.schemas.agent import AgentIntentPlan, AgentIntentTask
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_media import ResolvedAgentImage


def make_image(purpose: ImagePurpose) -> ResolvedAgentImage:
    return ResolvedAgentImage(
        asset_id=uuid4(),
        purpose=purpose,
        content_type="image/jpeg",
        data=b"sensitive-image-bytes",
    )


def make_task(
    task_type: str,
    asset_ids: list,
) -> AgentIntentTask:
    return AgentIntentTask(
        task_type=task_type,
        asset_ids=asset_ids,
        confidence="high",
        routing_reason="用户明确提出了该任务。",
    )


def make_dependencies() -> tuple[MagicMock, MagicMock]:
    model = MagicMock(spec=BaseChatModel)
    structured_model = MagicMock()
    structured_model.ainvoke = AsyncMock()
    model.with_structured_output.return_value = structured_model
    return model, structured_model


def test_router_uses_agent_intent_plan_structured_output() -> None:
    model, _ = make_dependencies()

    AgentIntentRouter(model)

    model.with_structured_output.assert_called_once_with(
        AgentIntentPlan,
        method="function_calling",
        include_raw=True,
    )


@pytest.mark.asyncio
async def test_router_returns_mixed_body_and_nutrition_plan() -> None:
    model, structured_model = make_dependencies()
    body_image = make_image(ImagePurpose.BODY_PROGRESS)
    meal_image = make_image(ImagePurpose.NUTRITION_ENTRY)
    expected = AgentIntentPlan(
        tasks=[
            make_task("body_assessment", [body_image.asset_id]),
            make_task("nutrition_analysis", [meal_image.asset_id]),
        ]
    )
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": expected,
        "parsing_error": None,
    }
    router = AgentIntentRouter(model)

    result = await router.route(
        message="结合我的身材照和午餐给出减脂建议",
        images=[body_image, meal_image],
    )

    assert result == expected
    messages = structured_model.ainvoke.await_args.args[0]
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert "一次请求可以包含多个任务" in messages[0].content
    payload = json.loads(messages[1].content)
    assert payload["message"] == "结合我的身材照和午餐给出减脂建议"
    assert payload["images"] == [
        {
            "asset_id": str(body_image.asset_id),
            "purpose": "body_progress",
        },
        {
            "asset_id": str(meal_image.asset_id),
            "purpose": "nutrition_entry",
        },
    ]
    assert "sensitive-image-bytes" not in messages[1].content


@pytest.mark.asyncio
async def test_router_allows_one_image_in_multiple_tasks() -> None:
    model, structured_model = make_dependencies()
    image = make_image(ImagePurpose.BODY_PROGRESS)
    expected = AgentIntentPlan(
        tasks=[
            make_task("body_assessment", [image.asset_id]),
            make_task("body_progress_comparison", [image.asset_id]),
        ]
    )
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": expected,
        "parsing_error": None,
    }
    router = AgentIntentRouter(model)

    result = await router.route(
        message="评估体态并和历史进度比较",
        images=[image],
    )

    assert result == expected


@pytest.mark.asyncio
async def test_router_repairs_unassigned_image_for_single_general_question() -> None:
    model, structured_model = make_dependencies()
    image = make_image(ImagePurpose.CHAT_ATTACHMENT)
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": AgentIntentPlan(
            tasks=[make_task("general_question", [])],
            unassigned_asset_ids=[image.asset_id],
        ),
        "parsing_error": None,
    }
    router = AgentIntentRouter(model)

    result = await router.route(
        message="Describe the image",
        images=[image],
    )

    assert result.tasks[0].asset_ids == [image.asset_id]
    assert result.unassigned_asset_ids == []


@pytest.mark.asyncio
@pytest.mark.parametrize("assignment", ["omitted", "invented"])
async def test_router_rejects_image_assignment_mismatch(
    assignment: str,
) -> None:
    model, structured_model = make_dependencies()
    image = make_image(ImagePurpose.CHAT_ATTACHMENT)
    assigned_ids = [] if assignment == "omitted" else [uuid4()]
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": AgentIntentPlan(tasks=[make_task("general_question", assigned_ids)]),
        "parsing_error": None,
    }
    router = AgentIntentRouter(model)

    with pytest.raises(AgentIntentRoutingError, match="provided images"):
        await router.route(
            message="分析这张图片",
            images=[image],
        )


@pytest.mark.asyncio
async def test_router_maps_structured_output_failure() -> None:
    model, structured_model = make_dependencies()
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": None,
        "parsing_error": ValueError("invalid plan"),
    }
    router = AgentIntentRouter(model)

    with pytest.raises(AgentIntentRoutingError, match="structured output"):
        await router.route(
            message="帮我分析我的近期训练表现",
            images=[],
        )


@pytest.mark.asyncio
async def test_router_uses_fallback_after_invalid_primary_output() -> None:
    primary, primary_structured = make_dependencies()
    fallback, fallback_structured = make_dependencies()
    expected = AgentIntentPlan(tasks=[make_task("general_question", [])])
    primary_structured.ainvoke.return_value = {
        "raw": None,
        "parsed": None,
        "parsing_error": ValueError("invalid"),
    }
    fallback_structured.ainvoke.return_value = {
        "raw": None,
        "parsed": expected,
        "parsing_error": None,
    }

    result = await AgentIntentRouter(primary, fallback).route(
        message="你好，可以介绍一下你自己吗？",
        images=[],
    )

    assert result == expected
    primary_structured.ainvoke.assert_awaited_once()
    fallback_structured.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_router_locally_routes_clear_knowledge_question_without_model() -> None:
    model, structured_model = make_dependencies()

    result = await AgentIntentRouter(model).route(
        message="力量训练后为什么通常需要摄入蛋白质？",
        images=[],
    )

    assert [task.task_type for task in result.tasks] == ["knowledge_retrieval"]
    assert result.tasks[0].confidence == "high"
    structured_model.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_router_prioritizes_explicit_plan_creation_over_why_explanation() -> None:
    model, structured_model = make_dependencies()

    result = await AgentIntentRouter(model).route(
        message=(
            "请根据我的身高、目标和每周可练天数，生成一份三天哑铃力量训练计划草稿，"
            "说明为什么适合我；先不要启用。"
        ),
        images=[],
    )

    assert [task.task_type for task in result.tasks] == ["training_plan_draft"]
    assert result.tasks[0].confidence == "high"
    structured_model.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_router_keeps_how_to_create_a_plan_as_read_only_knowledge() -> None:
    model, structured_model = make_dependencies()

    result = await AgentIntentRouter(model).route(
        message="请解释如何制定一份力量训练计划？",
        images=[],
    )

    assert [task.task_type for task in result.tasks] == ["knowledge_retrieval"]
    structured_model.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_router_keeps_multiple_explicit_tasks_for_model_routing() -> None:
    model, structured_model = make_dependencies()
    expected = AgentIntentPlan(tasks=[make_task("training_plan_draft", [])])
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": expected,
        "parsing_error": None,
    }

    await AgentIntentRouter(model).route(
        message="请生成一份力量训练计划，同时帮我记录今天饮食。",
        images=[],
    )

    structured_model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["你好！", "hello", "Hi", "你能做什么？"])
async def test_router_locally_routes_simple_conversation_without_model(
    message: str,
) -> None:
    model, structured_model = make_dependencies()

    result = await AgentIntentRouter(model).route(
        message=message,
        images=[],
    )

    assert [task.task_type for task in result.tasks] == ["general_question"]
    assert result.tasks[0].required_context == []
    assert result.tasks[0].confidence == "high"
    structured_model.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["今天怎么练？", "How should I train today?"])
async def test_router_locally_routes_today_training_query_without_model(message: str) -> None:
    model, structured_model = make_dependencies()

    result = await AgentIntentRouter(model).route(
        message=message,
        images=[],
    )

    assert [task.task_type for task in result.tasks] == ["structured_data_query"]
    assert result.tasks[0].required_context == ["training_plan", "calendar", "workout"]
    assert result.tasks[0].confidence == "high"
    structured_model.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_router_does_not_locally_route_today_training_mutation() -> None:
    model, structured_model = make_dependencies()
    expected = AgentIntentPlan(tasks=[make_task("training_plan_draft", [])])
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": expected,
        "parsing_error": None,
    }

    result = await AgentIntentRouter(model).route(
        message="帮我调整今天的训练",
        images=[],
    )

    assert result == expected
    structured_model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_router_uses_model_for_ambiguous_plan_discussion() -> None:
    model, structured_model = make_dependencies()
    expected = AgentIntentPlan(tasks=[make_task("training_plan_draft", [])])
    structured_model.ainvoke.return_value = {
        "raw": None,
        "parsed": expected,
        "parsing_error": None,
    }

    result = await AgentIntentRouter(model).route(
        message="我可能想制定一套力量训练计划，先聊聊",
        images=[],
    )

    assert result == expected
    structured_model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_router_rejects_blank_message_before_model_call() -> None:
    model, structured_model = make_dependencies()
    router = AgentIntentRouter(model)

    with pytest.raises(ValueError, match="message"):
        await router.route(message="   ", images=[])

    structured_model.ainvoke.assert_not_awaited()
