import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from nxtrep_backend.agents.intent_router import (
    AgentIntentRouter,
    AgentIntentRoutingError,
    is_confirmation_status_query,
    meal_nutrient_follow_up_task,
)
from nxtrep_backend.schemas.agent import AgentIntentPlan, AgentIntentTask
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_media import ResolvedAgentImage
from nxtrep_backend.services.conversation import (
    AgentConversationContext,
    ConversationMessageContext,
)


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


def supply_plan(structured, task_type, required_context=()):
    structured.ainvoke.return_value = {"parsed": AgentIntentPlan(tasks=[AgentIntentTask(
        task_type=task_type, confidence="high", routing_reason="模型语义规划",
        required_context=list(required_context),
    )]), "raw": None, "parsing_error": None}


def test_router_uses_agent_intent_plan_structured_output() -> None:
    model, _ = make_dependencies()

    AgentIntentRouter(model)

    model.with_structured_output.assert_called_once_with(
        AgentIntentPlan,
        method="function_calling",
        include_raw=True,
    )


@pytest.mark.asyncio
async def test_router_repairs_one_malformed_plan_before_returning_validated_intent():
    model, structured = make_dependencies()
    expected = AgentIntentPlan(tasks=[make_task("general_question", [])])
    structured.ainvoke.side_effect = [
        {"parsed": None, "parsing_error": ValueError("invalid enum")},
        {"parsed": expected, "parsing_error": None},
    ]
    result = await AgentIntentRouter(model).route(message="解释一下训练容量", images=[])
    assert result == expected
    assert structured.ainvoke.await_count == 2
    repair_messages = structured.ainvoke.await_args_list[1].args[0]
    assert "不补造用户意图" in repair_messages[-2].content


@pytest.mark.asyncio
async def test_router_format_repair_is_bounded():
    model, structured = make_dependencies()
    structured.ainvoke.return_value = {"parsed": None}
    with pytest.raises(AgentIntentRoutingError):
        await AgentIntentRouter(model).route(message="解释一下训练容量", images=[])
    assert structured.ainvoke.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "只用两句话解释一下，这份草稿还没保存对吗？",
        "这个草稿现在生效了吗",
        "刚才的提案是否已经执行？",
    ],
)
async def test_concrete_draft_status_uses_read_tools_without_public_knowledge(message):
    model, structured_model = make_dependencies()
    supply_plan(structured_model, "structured_data_query", ["confirmation"])
    plan = await AgentIntentRouter(model).route(message=message, images=[])
    assert plan.tasks[0].task_type == "structured_data_query"
    assert plan.tasks[0].required_context == ["confirmation"]
    structured_model.ainvoke.assert_awaited_once()


@pytest.mark.parametrize(
    "message",
    [
        "草稿是什么？",
        "取消这份草稿",
        "这份草稿改成100克，保存了吗？",
        "请批准这张卡，马上执行",
        "这份提案确认机制为什么这样设计？",
        "这份草稿保存了吗，另外查一下今天的训练和饮食",
    ],
)
def test_status_shortcut_does_not_drop_mutations_or_product_questions(message):
    assert not is_confirmation_status_query(message)


def meal_context():
    return AgentConversationContext(
        recent_messages=(
            ConversationMessageContext(role="user", content="午饭是泡脚鸡胗饭"),
            ConversationMessageContext(
                role="assistant",
                content="已创建午餐草稿，碳水约68克，待确认。",
            ),
            ConversationMessageContext(role="user", content="碳水应该不超过六十克"),
            ConversationMessageContext(role="assistant", content="没有完成长期记忆修改，请重试。"),
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message,expected",
    [
        ("碳水应该不超过六十克", "structured_data_query"),
        ("热量应该只有500千卡", "structured_data_query"),
        ("这餐蛋白质至少30g吧", "structured_data_query"),
        ("把米饭减少，让整餐碳水控制在60克以内，先改草稿", "nutrition_record_draft"),
    ],
)
async def test_meal_nutrient_followup_never_becomes_long_term_memory(message, expected):
    model, structured = make_dependencies()
    supply_plan(structured, expected, ["confirmation"])
    result = await AgentIntentRouter(model).route(
        message=message,
        images=[],
        conversation_context=meal_context(),
    )
    assert [task.task_type for task in result.tasks] == [expected]
    assert result.tasks[0].required_context == ["confirmation"]
    structured.ainvoke.assert_awaited_once()


@pytest.mark.parametrize(
    "message",
    [
        "记住以后每餐碳水不超过60克",
        "每天碳水目标改成60克",
        "我的长期偏好是每餐碳水60克以内",
        "取消草稿，碳水不超过60克",
        "碳水控制60克以内，另外查训练记录",
        "碳水是什么",
        "不要减少米饭，碳水应该不超过60克",
        "不要改鸡胗，只减少米饭，碳水控制60克以内",
    ],
)
def test_meal_followup_does_not_override_explicit_memory_or_mixed_tasks(message):
    assert meal_nutrient_follow_up_task(message, meal_context()) is None


def test_nutrient_statement_without_meal_context_requires_semantic_routing():
    assert meal_nutrient_follow_up_task("碳水应该不超过六十克", None) is None


@pytest.mark.asyncio
async def test_nutrient_feedback_reviews_a_proposed_write_before_any_execution():
    model, structured = make_dependencies()
    wrong = AgentIntentPlan(tasks=[make_task("nutrition_record_draft", [])])
    corrected = AgentIntentPlan(tasks=[make_task("structured_data_query", [])])
    structured.ainvoke.side_effect = [
        {"parsed": wrong, "raw": None, "parsing_error": None},
        {"parsed": corrected, "raw": None, "parsing_error": None},
    ]
    result = await AgentIntentRouter(model).route(
        message="碳水应该不超过六十克", images=[], conversation_context=meal_context(),
    )
    assert result == corrected
    assert structured.ainvoke.await_count == 2
    feedback = json.loads(structured.ainvoke.await_args_list[1].args[0][1].content)
    assert feedback["validation_conflicts"][0]["code"] == "MEAL_FEEDBACK_IS_READ_ONLY"


@pytest.mark.asyncio
async def test_nutrient_feedback_repeated_write_plan_is_rejected():
    model, structured = make_dependencies()
    supply_plan(structured, "nutrition_record_draft")
    with pytest.raises(AgentIntentRoutingError, match="目标仍有冲突"):
        await AgentIntentRouter(model).route(
            message="碳水应该不超过六十克", images=[], conversation_context=meal_context(),
        )
    assert structured.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_nutrient_correction_passes_saved_meal_state_to_model():
    from dataclasses import replace

    context = replace(
        meal_context(),
        meal_confirmations=(
            {
                "status": "succeeded",
                "operation_type": "nutrition_entry_create",
                "entry_id": str(uuid4()),
            },
        ),
    )
    model, structured = make_dependencies()
    supply_plan(structured, "nutrition_entry_update_draft")
    plan = await AgentIntentRouter(model).route(
        message="把米饭减少，让整餐碳水控制在60克以内", images=[], conversation_context=context
    )
    assert [t.task_type for t in plan.tasks] == ["nutrition_entry_update_draft"]
    structured.ainvoke.assert_awaited_once()
    assert meal_nutrient_follow_up_task("碳水应该不超过六十克", AgentConversationContext()) is None


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
    assert primary_structured.ainvoke.await_count == 2
    fallback_structured.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_router_semantically_routes_clear_knowledge_question() -> None:
    model, structured_model = make_dependencies()
    supply_plan(structured_model, "knowledge_retrieval")

    result = await AgentIntentRouter(model).route(
        message="力量训练后为什么通常需要摄入蛋白质？",
        images=[],
    )

    assert [task.task_type for task in result.tasks] == ["knowledge_retrieval"]
    assert result.tasks[0].confidence == "high"
    structured_model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_router_prioritizes_explicit_plan_creation_over_why_explanation() -> None:
    model, structured_model = make_dependencies()
    supply_plan(structured_model, "training_plan_draft")

    result = await AgentIntentRouter(model).route(
        message=(
            "请根据我的身高、目标和每周可练天数，生成一份三天哑铃力量训练计划草稿，"
            "说明为什么适合我；先不要启用。"
        ),
        images=[],
    )

    assert [task.task_type for task in result.tasks] == ["training_plan_draft"]
    assert result.tasks[0].confidence == "high"
    structured_model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_router_keeps_how_to_create_a_plan_as_read_only_knowledge() -> None:
    model, structured_model = make_dependencies()
    supply_plan(structured_model, "knowledge_retrieval")

    result = await AgentIntentRouter(model).route(
        message="请解释如何制定一份力量训练计划？",
        images=[],
    )

    assert [task.task_type for task in result.tasks] == ["knowledge_retrieval"]
    structured_model.ainvoke.assert_awaited_once()


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
async def test_router_interprets_simple_conversation_with_model(
    message: str,
) -> None:
    model, structured_model = make_dependencies()
    supply_plan(structured_model, "general_question")

    result = await AgentIntentRouter(model).route(
        message=message,
        images=[],
    )

    assert [task.task_type for task in result.tasks] == ["general_question"]
    assert result.tasks[0].required_context == []
    assert result.tasks[0].confidence == "high"
    structured_model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["今天怎么练？", "How should I train today?"])
async def test_router_semantically_routes_today_training_query(message: str) -> None:
    model, structured_model = make_dependencies()
    supply_plan(structured_model, "structured_data_query", ["training_plan", "calendar", "workout"])

    result = await AgentIntentRouter(model).route(
        message=message,
        images=[],
    )

    assert [task.task_type for task in result.tasks] == ["structured_data_query"]
    assert result.tasks[0].required_context == ["training_plan", "calendar", "workout"]
    assert result.tasks[0].confidence == "high"
    structured_model.ainvoke.assert_awaited_once()


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "我今天已经吃了多少热量和碳水蛋白脂肪？",
        "我这周训练了多少次？",
        "今天练什么，顺便告诉我今天吃了多少热量？",
        "请把明天的训练改到周五，并告诉我为什么这样安排。",
        "我每天训练需要多少蛋白质？",
    ],
)
async def test_personal_and_mixed_questions_reach_semantic_router(message):
    model, structured = make_dependencies()
    expected = AgentIntentPlan(tasks=[make_task("structured_data_query", [])])
    structured.ainvoke.return_value = {"parsed": expected, "parsing_error": None}
    result = await AgentIntentRouter(model).route(message=message, images=[])
    assert result == expected
    structured.ainvoke.assert_awaited_once()
