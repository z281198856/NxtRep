from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.intent_router import AgentIntentRouter
from nxtrep_backend.schemas.agent import (
    AgentChatRequest,
    AgentIntentPlan,
    AgentIntentTask,
)
from nxtrep_backend.schemas.agent_task import AgentTask, AgentTaskState, AgentTaskUpdate
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


async def plan_task(task, *, message="记录午饭", context=None):
    resolver, router, assembler = make_dependencies()
    router.route.return_value = AgentIntentPlan(tasks=[task])
    return await AgentRequestPlanner(
        resolver=resolver, intent_router=router, context_assembler=assembler
    ).plan(
        user_id=uuid4(),
        request=AgentChatRequest(message=message),
        conversation_context=context or AgentConversationContext(),
    )


def meal_task(parameters, *, fields=(), transition="new"):
    return AgentIntentTask(
        task_type="nutrition_record_draft",
        confidence="high",
        routing_reason="文字记餐份量回归",
        missing_fields=list(fields),
        task_update=AgentTaskUpdate(
            transition=transition, parameters=parameters, missing_fields=list(fields)
        ),
    )


@pytest.mark.asyncio
async def test_named_lunch_with_qualitative_portion_can_prepare_an_estimate():
    items = [
        {"food_name": "去皮葱烧鸡腿肉"},
        {"food_name": "葱烧豆腐"},
        {"food_name": "米饭", "amount_g": "正常一盒"},
    ]
    planned = await plan_task(
        meal_task({"items": items}, fields=["items[].amount_g"]),
        message="今天午饭是去皮葱烧鸡腿肉和葱烧豆腐，米饭正常一盒",
    )
    task = planned.intent_plan.tasks[0]
    assert task.missing_fields == []
    assert task.task_update.parameters["items"] == items
    state = planned.conversation_context.task_state["active_task"]
    assert state["status"] == "ready"
    assert state["missing_fields"] == []


@pytest.mark.asyncio
async def test_old_collecting_meal_can_continue_without_weighing_food():
    active = AgentTask(
        task_type="nutrition_record_draft",
        parameters={"items": [{"food_name": "米饭", "amount_g": "一盒"}]},
        missing_fields=["items[].amount_g"],
    )
    context = AgentConversationContext(
        task_state=AgentTaskState(active_task=active).model_dump(mode="json")
    )
    planned = await plan_task(
        meal_task({"meal_type": "lunch"}, transition="continue"),
        message="这是午饭，按普通份量估算就好",
        context=context,
    )
    task = planned.intent_plan.tasks[0]
    assert task.task_id == active.task_id
    assert task.missing_fields == []
    assert task.task_update.parameters["items"][0]["food_name"] == "米饭"


@pytest.mark.asyncio
async def test_meal_without_identified_food_still_requires_food_name():
    planned = await plan_task(meal_task({"meal_type": "lunch"}, fields=["food_name", "amount_g"]))
    assert "food_name" in planned.intent_plan.tasks[0].missing_fields
    assert planned.conversation_context.task_state["active_task"]["status"] == "collecting"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entity,status", [("confirmation_id", "awaiting_confirmation"), ("entry_id", "completed")]
)
async def test_existing_meal_correction_cannot_default_a_missing_new_quantity(entity, status):
    active = AgentTask(
        task_type="nutrition_record_draft",
        status=status,
        entities={entity: str(uuid4())},
        parameters={"food_name": "米饭"},
    )
    planned = await plan_task(
        meal_task({"food_name": "米饭"}, fields=["amount_g"], transition="correct"),
        message="米饭份量不对，修改刚才那份",
        context=AgentConversationContext(
            task_state=AgentTaskState(active_task=active).model_dump(mode="json")
        ),
    )
    assert "amount_g" in planned.intent_plan.tasks[0].missing_fields
    assert planned.intent_plan.tasks[0].task_update.entities[entity] == active.entities[entity]


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [-1, "NaN", True])
@pytest.mark.parametrize("nested", [False, True])
async def test_explicit_invalid_meal_quantity_is_not_permission_to_estimate(amount, nested):
    parameters = (
        {"items": [{"food_name": "米饭", "amount_g": amount}]}
        if nested
        else {"food_name": "米饭", "amount_g": amount}
    )
    planned = await plan_task(meal_task(parameters))
    task = planned.intent_plan.tasks[0]
    expected = "items[0].amount_g" if nested else "amount_g"
    assert expected in task.missing_fields
    assert planned.conversation_context.task_state["active_task"]["status"] == "collecting"


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
async def test_invalid_quantity_survives_other_slot_update_until_valid_quantity_arrives(nested):
    parameters = (
        {"items": [{"food_name": "米饭", "amount_g": -1}]}
        if nested
        else {"food_name": "米饭", "amount_g": -1}
    )
    first = await plan_task(meal_task(parameters))
    second = await plan_task(
        meal_task({"meal_type": "lunch"}, transition="continue"),
        message="餐次是午饭",
        context=first.conversation_context,
    )
    expected = "items[0].amount_g" if nested else "amount_g"
    assert expected in second.intent_plan.tasks[0].missing_fields
    corrected = {"items": [{"food_name": "米饭", "amount_g": 200}]} if nested else {"amount_g": 200}
    third = await plan_task(
        meal_task(corrected, transition="continue"),
        message="现在把份量更正为普通一份",
        context=second.conversation_context,
    )
    assert third.intent_plan.tasks[0].missing_fields == []
    assert third.conversation_context.task_state["active_task"]["status"] == "ready"


@pytest.mark.asyncio
async def test_complete_multi_food_parameters_do_not_request_a_single_global_amount():
    resolver, router, assembler = make_dependencies()
    router.route.return_value = AgentIntentPlan(
        tasks=[
            AgentIntentTask(
                task_type="nutrition_record_draft",
                confidence="high",
                routing_reason="multi food",
                missing_fields=["amount_g"],
                task_update=AgentTaskUpdate(
                    transition="new",
                    parameters={
                        "items": [
                            {"food_name": "米饭", "amount_g": 200},
                            {"food_name": "鸡胸肉", "amount_g": 150},
                        ],
                        "meal_type": "lunch",
                    },
                    missing_fields=["amount_g"],
                ),
            )
        ]
    )
    planned = await AgentRequestPlanner(
        resolver=resolver, intent_router=router, context_assembler=assembler
    ).plan(
        user_id=uuid4(),
        request=AgentChatRequest(message="午饭记录米饭200g、鸡胸肉150g"),
        conversation_context=AgentConversationContext(),
    )
    assert planned.intent_plan.tasks[0].missing_fields == []
    assert len(planned.intent_plan.tasks[0].task_update.parameters["items"]) == 2
    assert planned.conversation_context.task_state["active_task"]["missing_fields"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "task_type, expected",
    [
            ("nutrition_analysis", "nutrition_analysis"),
        ("nutrition_target_draft", "nutrition_target_draft"),
        ("training_plan_draft", "training_plan_draft"),
    ],
)
async def test_planner_preserves_model_task_without_local_image_coercion(
    task_type: str,
    expected: str,
) -> None:
    resolver, router, assembler = make_dependencies()
    router.route.return_value = make_plan(task_type)
    planner = AgentRequestPlanner(
        resolver=resolver, intent_router=router, context_assembler=assembler
    )
    result = await planner.plan(
        user_id=uuid4(),
        request=AgentChatRequest(message="分析一下汉堡营养成分"),
        conversation_context=AgentConversationContext(),
    )
    assert result.intent_plan.tasks[0].task_type == expected
    assert result.intent_plan.tasks[0].missing_fields == []
    resolver.resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_food_photo_keeps_image_analysis_route() -> None:
    resolver, router, assembler = make_dependencies()
    asset_id = uuid4()
    resolver.resolve.return_value = [
        ResolvedAgentImage(
            asset_id=asset_id,
            purpose=ImagePurpose.NUTRITION_ENTRY,
            content_type="image/jpeg",
            data=b"sanitized-food-image",
        )
    ]
    router.route.return_value = make_plan("nutrition_analysis")
    planner = AgentRequestPlanner(
        resolver=resolver, intent_router=router, context_assembler=assembler
    )
    result = await planner.plan(
        user_id=uuid4(),
        request=AgentChatRequest(message="这顿饭多少热量", image_asset_ids=[asset_id]),
        conversation_context=AgentConversationContext(),
    )
    assert result.intent_plan.tasks[0].task_type == "nutrition_analysis"


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


@pytest.mark.asyncio
@pytest.mark.parametrize("hint", [None, "", "一盒", "正常一盒", "一大碗", "半碗"])
async def test_top_level_unspecified_or_qualitative_portion_is_estimable_for_new_meal(hint):
    planned = await plan_task(
        meal_task({"food_name": "米饭", "amount_g": hint}, fields=["amount_g"])
    )
    active = planned.conversation_context.task_state["active_task"]
    assert active["missing_fields"] == []
    assert active["invalid_fields"] == []
    assert active["status"] == "ready"


@pytest.mark.asyncio
@pytest.mark.parametrize("hint", [None, "一盒"])
async def test_qualitative_correction_does_not_reuse_saved_meal_old_grams(hint):
    from uuid import uuid4

    from nxtrep_backend.schemas.agent_task import AgentTask, AgentTaskState

    state = AgentTaskState(
        active_task=AgentTask(
            task_type="nutrition_record_draft",
            entities={"entry_id": str(uuid4())},
            parameters={"food_name": "米饭", "amount_g": 150},
        )
    )
    task = meal_task(
        {"food_name": "米饭", "amount_g": hint}, fields=["amount_g"], transition="continue"
    )
    planned = await plan_task(
        task, context=AgentConversationContext(task_state=state.model_dump(mode="json"))
    )
    active = planned.conversation_context.task_state["active_task"]
    assert "amount_g" in active["missing_fields"]
    assert "amount_g" in active["invalid_fields"]
    assert "amount_g" not in active["parameters"]


@pytest.mark.asyncio
async def test_new_meal_invalid_amount_can_be_corrected_with_an_explicit_portion_description():
    first = await plan_task(meal_task({"food_name": "米饭", "amount_g": -150}))
    second = await plan_task(
        meal_task({"portion": "一盒"}, transition="continue"), context=first.conversation_context
    )
    active = second.conversation_context.task_state["active_task"]
    assert active["missing_fields"] == active["invalid_fields"] == []
    assert active["parameters"]["_amount_g_input"] == "一盒"
    assert active["status"] == "ready"


@pytest.mark.asyncio
async def test_valid_meal_grams_clear_old_invalid_input_hint():
    first = await plan_task(meal_task({"food_name": "米饭", "amount_g": -150}))
    second = await plan_task(
        meal_task({"amount_g": 200}, transition="continue"), context=first.conversation_context
    )
    active = second.conversation_context.task_state["active_task"]
    assert active["missing_fields"] == active["invalid_fields"] == []
    assert "_amount_g_input" not in active["parameters"]
