import json
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph

from nxtrep_backend.agents.vision import GlmVisionAnalyzer
from nxtrep_backend.schemas.agent import AgentCitation, AgentIntentTask
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.services.agent_context import ActiveMemoryContext
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.general import (
    GeneralQuestionBranchHandler,
    GeneralQuestionResponseError,
)
from nxtrep_backend.services.agent_media import ResolvedAgentImage
from nxtrep_backend.services.conversation import (
    AgentConversationContext,
    ConversationMessageContext,
)


def make_react_agent(result: dict) -> MagicMock:
    agent = MagicMock(spec=CompiledStateGraph)
    agent.ainvoke = AsyncMock(return_value=result)
    return agent


def make_handler(react_agent: MagicMock):
    return GeneralQuestionBranchHandler(lambda task: react_agent)


def make_input(
    *,
    task_type: str = "general_question",
    missing_fields=None,
    required_context=None,
) -> AgentBranchInput:
    return AgentBranchInput(
        user_id=uuid4(),
        message="深蹲时应该怎样呼吸？",
        task=AgentIntentTask(
            task_type=task_type,
            asset_ids=[],
            required_context=(["profile"] if required_context is None else required_context),
            missing_fields=missing_fields or [],
            confidence="high",
            routing_reason="The user asked a general fitness question",
        ),
        images=(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [True, False])
async def test_actual_preflight_search_allows_useful_estimate_without_repeated_search(available):
    agent = make_react_agent(
        {
            "messages": [
                AIMessage(content="按一份米饭和一个鸡腿估算，约600至800千卡；油和酱汁会影响结果。")
            ]
        }
    )
    preflight = {
        "status": "available" if available else "unavailable",
        "sources": [{"url": "https://example.org/food", "title": "食物资料"}] if available else [],
        "message": "搜索服务不可用" if not available else "已找到来源",
    }
    request = replace(
        make_input(required_context=[]),
        message="一份鸡腿饭大概多少热量？",
        knowledge_context={"web_search_required": True, "preflight_web_result": preflight},
    )
    result = await make_handler(agent).execute(request)
    assert result.status == "completed"
    assert result.result["web_search_results"] == [preflight]
    assert agent.ainvoke.await_count == 1
    if available:
        assert any(item.source_id == "https://example.org/food" for item in result.citations)
    else:
        assert "联网没有取得可用来源" in result.result["answer"]
        assert not result.citations


@pytest.mark.asyncio
async def test_explicit_web_verification_keeps_actual_preflight_failure_visible():
    agent = make_react_agent({"messages": [AIMessage(content="估算可参考600至800千卡。")]})
    request = replace(
        make_input(required_context=[]),
        message="联网核实这份鸡腿饭的热量。",
        knowledge_context={
            "web_search_required": True,
            "preflight_web_result": {
                "status": "unavailable",
                "sources": [],
                "error_code": "WEB_SEARCH_UNAVAILABLE",
                "message": "联网服务暂不可用",
            },
        },
    )
    result = await make_handler(agent).execute(request)
    assert result.status == "failed"
    assert result.error.code == "WEB_SEARCH_UNAVAILABLE"
    assert result.error.message == "联网服务暂不可用"
    assert not result.citations


@pytest.mark.asyncio
@pytest.mark.parametrize("read_record", [False, True])
async def test_structured_query_requires_fresh_read_evidence(read_record):
    messages = []
    if read_record:
        messages.append(
            ToolMessage(
                name="read_daily_nutrition_summary",
                tool_call_id="read",
                content=json.dumps(
                    {
                        "status": "available",
                        "consumed": {
                            "kcal": "500",
                            "protein_g": "25",
                            "carbs_g": "60",
                            "fat_g": "15",
                        },
                    }
                ),
            )
        )
    messages.append(AIMessage(content="今天记录了 500 千卡。"))
    agent = make_react_agent({"messages": messages})
    result = await make_handler(agent).execute(
        make_input(
            task_type="structured_data_query",
            required_context=["nutrition"],
        )
    )
    assert result.status == ("completed" if read_record else "failed")
    if not read_record:
        assert result.error.code == "DATA_QUERY_NOT_EXECUTED"


@pytest.mark.asyncio
async def test_mixed_query_does_not_claim_missing_domain_was_read():
    agent = make_react_agent(
        {
            "messages": [
                ToolMessage(
                    name="read_recent_workouts",
                    tool_call_id="read",
                    content=json.dumps(
                        {
                            "status": "available",
                            "summary": {"workout_count": 2},
                            "workouts": [],
                        }
                    ),
                ),
                AIMessage(content="训练两次，吃了 1000 千卡。"),
            ]
        }
    )
    result = await make_handler(agent).execute(
        make_input(
            task_type="structured_data_query",
            required_context=["workout", "nutrition"],
        )
    )
    assert result.status == "failed"
    assert result.error.code == "DATA_QUERY_NOT_EXECUTED"


@pytest.mark.asyncio
async def test_memory_text_without_write_result_is_not_success():
    agent = make_react_agent({"messages": [AIMessage(content="已经记住了。请放心。")]})
    result = await make_handler(agent).execute(make_input(task_type="memory_write"))
    assert result.status == "failed"
    assert result.error.code == "MEMORY_OPERATION_NOT_EXECUTED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "task_type",
    [
        "workout_set_update_draft",
        "workout_set_void_draft",
        "nutrition_entry_update_draft",
        "nutrition_entry_delete_draft",
    ],
)
async def test_workout_change_text_without_card_never_claims_success(task_type):
    agent = make_react_agent({"messages": [AIMessage(content="训练记录已修改。请放心。")]})
    result = await make_handler(agent).execute(make_input(task_type=task_type))
    assert result.status == "failed"
    assert result.error.code == (
        "SAVED_MEAL_DRAFT_NOT_CREATED"
        if task_type.startswith("nutrition_entry_")
        else "WORKOUT_SET_DRAFT_NOT_CREATED"
    )
    assert result.unpersisted_suggestion is None
    assert agent.ainvoke.await_count == 2
    assert not result.confirmation_cards


@pytest.mark.asyncio
@pytest.mark.parametrize("with_card", [False, True])
async def test_workout_change_ambiguous_selection_keeps_pending_card_and_does_not_write(with_card):
    messages = [
        ToolMessage(
            name="read_workout_set_for_change",
            tool_call_id="read",
            content=json.dumps(
                {"status": "needs_review", "message": "有两个匹配的训练组，请选择。"}
            ),
        )
    ]
    if with_card:
        messages.append(
            ToolMessage(
                name="propose_workout_set_update",
                tool_call_id="edit",
                content=json.dumps(
                    {
                        "status": "confirmation_required",
                        "confirmation": {
                            "confirmation_id": str(uuid4()),
                            "operation_type": "workout_set_update",
                            "status": "pending",
                            "impact": "更正待确认",
                            "version": 1,
                            "expires_at": datetime(2026, 10, 8, tzinfo=UTC).isoformat(),
                        },
                    }
                ),
            )
        )
    messages.append(AIMessage(content="请选择具体记录。"))
    result = await make_handler(make_react_agent({"messages": messages})).execute(
        make_input(task_type="workout_set_update_draft")
    )
    assert result.status == "needs_input"
    assert result.result["saved"] is False
    assert result.result["answer"] == "有两个匹配的训练组，请选择。"
    assert result.missing_fields == ["workout_set_selection"]
    assert bool(result.confirmation_cards) == with_card
    assert result.requires_confirmation == with_card


@pytest.mark.asyncio
@pytest.mark.parametrize("creates_card", [True, False])
async def test_food_catalog_text_only_estimate_retries_once_without_fake_success(creates_card):
    card_id = uuid4()
    messages = [AIMessage(content="燕麦饼每100克约300千卡。")]
    if creates_card:
        messages = [
            ToolMessage(
                name="propose_custom_food",
                tool_call_id="food",
                content=json.dumps(
                    {
                        "status": "confirmation_required",
                        "confirmation": {
                            "confirmation_id": str(card_id),
                            "operation_type": "food_create",
                            "status": "pending",
                            "impact": "加入食品库",
                            "version": 1,
                            "expires_at": datetime(2026, 10, 7, tzinfo=UTC).isoformat(),
                        },
                    }
                ),
            ),
            AIMessage(content="食品草稿已创建，请确认。"),
        ]
    agent = make_react_agent({})
    agent.ainvoke.side_effect = [
        {"messages": [AIMessage(content="可以按常见配方估算燕麦饼。")]},
        {"messages": messages},
    ]
    result = await make_handler(agent).execute(make_input(task_type="food_catalog_draft"))
    assert agent.ainvoke.await_count == 2
    assert result.status == ("completed" if creates_card else "failed")
    if creates_card:
        assert result.confirmation_cards[0].confirmation_id == card_id
    else:
        assert result.error.code == "FOOD_CATALOG_DRAFT_NOT_CREATED"


@pytest.mark.asyncio
@pytest.mark.parametrize("with_card", [False, True])
async def test_food_review_is_clear_and_keeps_any_completed_pending_cards(with_card):
    messages = [
        ToolMessage(
            name="read_custom_food",
            tool_call_id="read",
            content=json.dumps({"status": "needs_review", "message": "有两个同名食品，请选择品牌"}),
        )
    ]
    if with_card:
        messages.append(
            ToolMessage(
                name="propose_custom_food_update",
                tool_call_id="edit",
                content=json.dumps(
                    {
                        "status": "confirmation_required",
                        "confirmation": {
                            "confirmation_id": str(uuid4()),
                            "operation_type": "food_update",
                            "status": "pending",
                            "impact": "修改待确认",
                            "version": 1,
                            "expires_at": datetime(2026, 10, 7, tzinfo=UTC).isoformat(),
                        },
                    }
                ),
            )
        )
    messages.append(AIMessage(content="要删除的食品有两个品牌，请选择。"))
    branch_input = make_input(task_type="food_catalog_draft")
    branch_input.task.food_catalog_actions = ["update", "delete"]
    agent = make_react_agent({"messages": messages})
    result = await make_handler(agent).execute(branch_input)
    assert result.status == "needs_input"
    assert bool(result.confirmation_cards) == with_card
    assert result.missing_fields == ["custom_food_selection"]
    assert agent.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_data_query_retries_only_missing_read_then_returns_verified_data():
    workouts = ToolMessage(
        name="read_recent_workouts",
        tool_call_id="workouts",
        content=json.dumps(
            {
                "status": "available",
                "summary": {"workout_count": 1},
                "workouts": [],
            }
        ),
    )
    nutrition = ToolMessage(
        name="read_daily_nutrition_summary",
        tool_call_id="nutrition",
        content=json.dumps(
            {
                "status": "available",
                "date": "2026-10-05",
                "consumed": {"kcal": "500", "protein_g": "25", "carbs_g": "60", "fat_g": "15"},
            }
        ),
    )
    agent = make_react_agent({})
    agent.ainvoke.side_effect = [
        {"messages": [workouts, AIMessage(content="还有营养记录未读取。")]},
        {"messages": [workouts, nutrition, AIMessage(content="训练 1 次，已记录 500 千卡。")]},
    ]
    result = await make_handler(agent).execute(
        make_input(
            task_type="structured_data_query",
            required_context=["workout", "nutrition"],
        )
    )
    assert result.status == "completed"
    assert len(result.result["queried_records"]) == 2
    assert agent.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_retry_timeout_cannot_return_stale_success_text():
    agent = make_react_agent({})
    agent.ainvoke.side_effect = [
        {"messages": [AIMessage(content="这是尚未保存的候选计划。")]},
        TimeoutError("private provider detail"),
    ]
    with pytest.raises(GeneralQuestionResponseError) as error:
        await make_handler(agent).execute(make_input(task_type="training_plan_draft"))
    assert isinstance(error.value.__cause__, TimeoutError)


@pytest.mark.asyncio
async def test_incomplete_read_is_distinct_from_an_unexecuted_query():
    agent = make_react_agent(
        {
            "messages": [
                ToolMessage(
                    name="read_daily_nutrition_summary",
                    tool_call_id="incomplete",
                    content=json.dumps({"status": "available", "consumed": {}}),
                ),
                AIMessage(content="今天吃了 500 千卡。"),
            ]
        }
    )
    result = await make_handler(agent).execute(
        make_input(
            task_type="structured_data_query",
            required_context=["nutrition"],
        )
    )
    assert result.status == "failed"
    assert result.error.code == "DATA_QUERY_INCOMPLETE"
    assert "不完整" in result.error.message


@pytest.mark.asyncio
async def test_plain_general_question_defers_to_native_streaming_synthesis() -> None:
    react_agent = make_react_agent({})
    handler = make_handler(react_agent)
    memory = ActiveMemoryContext(
        id=uuid4(),
        category="communication_preference",
        content="请使用中文回答",
        version=1,
    )
    branch_input = make_input(required_context=[])
    branch_input = AgentBranchInput(
        user_id=branch_input.user_id,
        message="你好",
        task=branch_input.task,
        images=(),
        memories=(memory,),
    )

    result = await handler.execute(branch_input)

    assert result.status == "completed"
    assert result.result == {
        "response_mode": "direct_general_question",
        "active_long_term_memories": [memory.as_dict()],
    }
    react_agent.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_returns_trimmed_react_answer() -> None:
    react_agent = make_react_agent(
        {"messages": [AIMessage(content=("  下蹲时吸气并保持躯干稳定，起身通过发力点后呼气。  "))]}
    )
    handler = make_handler(react_agent)
    branch_input = make_input()

    result = await handler.execute(branch_input)

    react_agent.ainvoke.assert_awaited_once()
    sent = react_agent.ainvoke.await_args
    assert sent.kwargs["config"] == {"recursion_limit": 32}
    context = json.loads(sent.args[0]["messages"][-1]["content"])
    assert context["current_user_message"] == branch_input.message
    assert context["current_action_plan"]["task_type"] == branch_input.task.task_type
    assert result.status == "completed"
    assert result.result == {"answer": "下蹲时吸气并保持躯干稳定，起身通过发力点后呼气。"}
    assert result.requires_confirmation is False


@pytest.mark.asyncio
async def test_handler_includes_vision_observation_for_image_question() -> None:
    react_agent = make_react_agent({"messages": [AIMessage(content="这张图展示了一个深蹲动作。")]})
    analyzer = MagicMock(spec=GlmVisionAnalyzer)
    analyzer.analyze = AsyncMock(return_value="观察到用户处于深蹲底部位置。")
    handler = GeneralQuestionBranchHandler(
        lambda task: react_agent,
        vision_analyzer=analyzer,
    )
    asset_id = uuid4()
    image = ResolvedAgentImage(
        asset_id=asset_id,
        purpose=ImagePurpose.BODY_PROGRESS,
        content_type="image/jpeg",
        data=b"sanitized-image",
    )
    base_input = make_input(required_context=[])
    branch_input = AgentBranchInput(
        user_id=base_input.user_id,
        message="帮我看看这个动作",
        task=AgentIntentTask(
            task_type="general_question",
            asset_ids=[asset_id],
            required_context=[],
            missing_fields=[],
            confidence="high",
            routing_reason="The user asked about an attached image",
        ),
        images=(image,),
    )

    result = await handler.execute(branch_input)

    assert result.status == "completed"
    analyzer.analyze.assert_awaited_once_with(
        question="帮我看看这个动作",
        images=(image,),
    )
    react_agent.ainvoke.assert_awaited_once()
    content = react_agent.ainvoke.await_args.args[0]["messages"][-1]["content"]
    assert "帮我看看这个动作" in content
    assert "观察到用户处于深蹲底部位置。" in content
    assert "c2FuaXRpemVkLWltYWdl" not in content


@pytest.mark.asyncio
async def test_optional_training_goal_does_not_block_breathing_answer() -> None:
    react_agent = make_react_agent({"messages": [
        AIMessage(content="下蹲时吸气，起身时呼气。围绕动作控制呼吸。"),
    ]})
    handler = make_handler(react_agent)
    branch_input = make_input(
        missing_fields=["training_goal", "training_goal"],
    )

    result = await handler.execute(branch_input)

    assert result.status == "completed"
    assert "呼吸" in result.result["answer"]
    react_agent.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_uses_general_knowledge_when_rag_is_disabled() -> None:
    react_agent = make_react_agent({})
    handler = GeneralQuestionBranchHandler(
        lambda task: react_agent,
        knowledge_retrieval_enabled=False,
    )

    result = await handler.execute(make_input(task_type="knowledge_retrieval"))

    assert result.status == "completed"
    assert result.result == {"response_mode": "general_knowledge", "evidence_status": "unavailable"}
    assert result.error is None
    react_agent.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_propagates_confirmation_requirement() -> None:
    confirmation_id = uuid4()
    react_agent = make_react_agent(
        {
            "messages": [
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "confirmation_required",
                            "draft": {"id": str(uuid4()), "version": 1},
                            "confirmation": {
                                "confirmation_id": str(confirmation_id),
                                "operation_type": "training_plan_activate",
                                "status": "pending",
                                "before": None,
                                "after": {"plan_draft_id": str(uuid4())},
                                "impact": "activate training plan",
                                "expires_at": datetime(2026, 9, 9, tzinfo=UTC).isoformat(),
                                "version": 1,
                            },
                        }
                    ),
                    tool_call_id="call-1",
                ),
                AIMessage(content="提案已创建，请在确认卡片中批准。"),
            ]
        }
    )
    handler = make_handler(react_agent)

    result = await handler.execute(make_input(task_type="training_plan_draft"))

    assert result.requires_confirmation is True
    assert len(result.operation_results) == 1
    assert result.confirmation_cards[0].confirmation_id == confirmation_id


@pytest.mark.asyncio
async def test_training_plan_retries_text_only_answer_and_returns_confirmation() -> None:
    confirmation_id = uuid4()
    agent = make_react_agent({})
    agent.ainvoke.side_effect = [
        {"messages": [AIMessage(content="这是文字计划。")]},
        {
            "messages": [
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "confirmation_required",
                            "confirmation": {
                                "confirmation_id": str(confirmation_id),
                                "operation_type": "training_plan_activate",
                                "status": "pending",
                                "impact": "激活训练计划",
                                "expires_at": datetime(2026, 9, 9, tzinfo=UTC).isoformat(),
                                "version": 1,
                            },
                        }
                    ),
                    name="propose_training_plan",
                    tool_call_id="plan-call",
                ),
                AIMessage(content="草稿已创建，请确认。"),
            ]
        },
    ]

    result = await make_handler(agent).execute(make_input(task_type="training_plan_draft"))

    assert agent.ainvoke.await_count == 2
    assert result.status == "completed"
    assert result.confirmation_cards[0].confirmation_id == confirmation_id
    assert result.requires_confirmation is True
    retry_messages = agent.ainvoke.await_args_list[1].args[0]["messages"]
    assert retry_messages[0]["role"] == "system"
    assert "propose_training_plan" in retry_messages[0]["content"]


@pytest.mark.asyncio
async def test_training_plan_without_tool_returns_specific_failure_after_one_retry() -> None:
    agent = make_react_agent({"messages": [AIMessage(content="这里只有文字计划。")]})

    result = await make_handler(agent).execute(make_input(task_type="training_plan_draft"))

    assert agent.ainvoke.await_count == 2
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "TRAINING_PLAN_DRAFT_NOT_CREATED"


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["", "可先采用适度热量缺口，后续按体重趋势调整。"])
async def test_nutrition_draft_failure_preserves_advice_after_bounded_retry(answer: str) -> None:
    agent = make_react_agent({"messages": [AIMessage(content=answer)]})
    result = await make_handler(agent).execute(make_input(task_type="nutrition_target_draft"))
    assert agent.ainvoke.await_count == 2
    assert result.status == "failed"
    assert result.error.code == "NUTRITION_TARGET_DRAFT_NOT_CREATED"
    assert result.unpersisted_suggestion == (answer or None)
    assert result.result is None
    assert result.confirmation_cards == []


@pytest.mark.asyncio
async def test_nutrition_draft_does_not_repeat_successful_side_effect() -> None:
    agent = make_react_agent(
        {
            "messages": [
                ToolMessage(
                    content=json.dumps({"status": "confirmation_required", "confirmation": {}}),
                    name="propose_nutrition_target",
                    tool_call_id="nutrition-call",
                ),
                AIMessage(content="请确认。"),
            ]
        }
    )
    result = await make_handler(agent).execute(make_input(task_type="nutrition_target_draft"))
    agent.ainvoke.assert_awaited_once()
    assert result.error.code == "NUTRITION_TARGET_DRAFT_NOT_CREATED"


@pytest.mark.asyncio
async def test_training_plan_retries_empty_model_answer_without_tool() -> None:
    agent = make_react_agent({})
    agent.ainvoke.side_effect = [
        {"messages": [AIMessage(content="")]},
        {"messages": [AIMessage(content="仍未创建草稿")]},
    ]

    result = await make_handler(agent).execute(make_input(task_type="training_plan_draft"))

    assert agent.ainvoke.await_count == 2
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "TRAINING_PLAN_DRAFT_NOT_CREATED"


@pytest.mark.asyncio
async def test_training_plan_retries_failed_tool_with_validation_feedback() -> None:
    agent = make_react_agent(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "plan-call",
                            "name": "propose_training_plan",
                            "args": {},
                        }
                    ],
                ),
                ToolMessage(
                    content=json.dumps({"status": "needs_review", "draft": {}}),
                    name="propose_training_plan",
                    tool_call_id="plan-call",
                ),
                AIMessage(content="草稿未通过校验。"),
            ]
        }
    )

    result = await make_handler(agent).execute(make_input(task_type="training_plan_draft"))

    assert agent.ainvoke.await_count == 2
    retry_messages = agent.ainvoke.await_args_list[1].args[0]["messages"]
    assert any(
        isinstance(item, ToolMessage) and "needs_review" in item.content for item in retry_messages
    )
    assert result.status == "failed"
    assert result.unpersisted_suggestion == "草稿未通过校验。"
    assert result.result is None
    assert result.error is not None
    assert result.error.code == "TRAINING_PLAN_DRAFT_INVALID"


@pytest.mark.asyncio
async def test_training_plan_does_not_retry_after_different_proposal_tool() -> None:
    agent = make_react_agent(
        {
            "messages": [
                ToolMessage(
                    content=json.dumps({"status": "confirmation_required", "confirmation": {}}),
                    name="propose_schedule_change",
                    tool_call_id="schedule-call",
                ),
                AIMessage(content="已创建其他提案。"),
            ]
        }
    )

    result = await make_handler(agent).execute(make_input(task_type="training_plan_draft"))

    agent.ainvoke.assert_awaited_once()
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "TRAINING_PLAN_DRAFT_INVALID"


@pytest.mark.asyncio
async def test_completed_proposal_is_not_reported_failed_when_final_answer_is_empty() -> None:
    confirmation_id = uuid4()
    agent = make_react_agent(
        {
            "messages": [
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "confirmation_required",
                            "confirmation": {
                                "confirmation_id": str(confirmation_id),
                                "operation_type": "training_plan_activate",
                                "status": "pending",
                                "impact": "激活训练计划",
                                "expires_at": datetime(2026, 9, 9, tzinfo=UTC).isoformat(),
                                "version": 1,
                            },
                        }
                    ),
                    name="propose_training_plan",
                    tool_call_id="plan-call",
                ),
                AIMessage(content=""),
            ]
        }
    )

    result = await make_handler(agent).execute(make_input(task_type="training_plan_draft"))

    agent.ainvoke.assert_awaited_once()
    assert result.status == "completed"
    assert result.confirmation_cards[0].confirmation_id == confirmation_id
    assert result.result == {"answer": "提案已创建，请在确认卡片中审核。"}


@pytest.mark.asyncio
async def test_handler_propagates_knowledge_citations() -> None:
    react_agent = make_react_agent(
        {
            "messages": [
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "available",
                            "evidence": [
                                {
                                    "content": "下蹲阶段吸气并保持躯干稳定。",
                                    "citation": {
                                        "source_key": "squat-guide",
                                        "source_title": "深蹲动作指南",
                                        "source_uri": "https://example.com/squat",
                                        "source_version": 3,
                                        "section_path": "动作要领 > 呼吸",
                                        "page_numbers": [4],
                                    },
                                },
                                {
                                    "content": "起身通过发力点后呼气。",
                                    "citation": {
                                        "source_key": "squat-guide",
                                        "source_title": "深蹲动作指南",
                                        "source_uri": "https://example.com/squat",
                                        "source_version": 3,
                                        "section_path": "动作要领 > 呼吸",
                                        "page_numbers": [5],
                                    },
                                },
                            ],
                        }
                    ),
                    tool_call_id="call-knowledge",
                ),
                AIMessage(content="下蹲时吸气，起身通过发力点后呼气。"),
            ]
        }
    )
    handler = make_handler(react_agent)

    result = await handler.execute(make_input(task_type="knowledge_retrieval"))

    assert result.citations == [
        AgentCitation(
            source_type="knowledge",
            source_id="squat-guide@3",
            label="深蹲动作指南 / 动作要领 > 呼吸 / 第4-5页",
        )
    ]


@pytest.mark.asyncio
async def test_handler_injects_recent_history_summary_and_relevant_memories() -> None:
    react_agent = make_react_agent({"messages": [AIMessage(content="安排好了")]})
    handler = make_handler(react_agent)
    branch_input = make_input(task_type="training_plan_draft")
    branch_input = AgentBranchInput(
        user_id=branch_input.user_id,
        message="那帮我安排一下",
        task=branch_input.task,
        images=(),
        conversation_context=AgentConversationContext(
            summary="用户计划增肌",
            recent_messages=(
                ConversationMessageContext(role="user", content="我每周练三天"),
                ConversationMessageContext(role="assistant", content="了解"),
            ),
        ),
        memories=(
            ActiveMemoryContext(
                id=uuid4(),
                category="equipment",
                content="只有哑铃",
                version=1,
            ),
        ),
    )

    await handler.execute(branch_input)

    messages = react_agent.ainvoke.await_args_list[0].args[0]["messages"]
    assert "用户计划增肌" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "我每周练三天"}
    assert messages[2] == {"role": "assistant", "content": "了解"}
    assert "只有哑铃" in messages[-1]["content"]
    assert "那帮我安排一下" in messages[-1]["content"]


@pytest.mark.asyncio
async def test_handler_rejects_wrong_task_type() -> None:
    react_agent = make_react_agent({})
    handler = make_handler(react_agent)

    with pytest.raises(ValueError, match="text task"):
        await handler.execute(make_input(task_type="nutrition_analysis"))

    react_agent.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "react_result, error_message",
    [
        ({}, "no messages"),
        ({"messages": []}, "no messages"),
        ({"messages": [AIMessage(content="   ")]}, "no answer"),
        (
            {
                "messages": [
                    AIMessage(
                        content=[
                            {
                                "type": "text",
                                "text": "unexpected block",
                            }
                        ]
                    )
                ]
            },
            "no answer",
        ),
    ],
)
async def test_handler_rejects_invalid_react_result(
    react_result: dict,
    error_message: str,
) -> None:
    handler = make_handler(make_react_agent(react_result))

    with pytest.raises(
        GeneralQuestionResponseError,
        match=error_message,
    ):
        await handler.execute(make_input())


@pytest.mark.asyncio
@pytest.mark.parametrize("first_answer", ["", "没有准确品牌匹配，需要再查询。"])
async def test_brand_meal_search_only_result_retries_and_creates_confirmation(first_answer):
    search = ToolMessage(
        name="search_food_candidates",
        tool_call_id="food-search",
        content=json.dumps({"status": "available", "total": 0, "foods": []}),
    )
    confirmation_id = uuid4()
    proposal = ToolMessage(
        name="propose_nutrition_entry",
        tool_call_id="meal-proposal",
        content=json.dumps(
            {
                "status": "confirmation_required",
                "confirmation": {
                    "confirmation_id": str(confirmation_id),
                    "operation_type": "nutrition_entry_create",
                    "status": "pending",
                    "impact": "确认后记录午餐",
                    "version": 1,
                    "expires_at": datetime(2026, 10, 6, tzinfo=UTC).isoformat(),
                },
            }
        ),
    )
    agent = make_react_agent({})
    search_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "food-search",
                "name": "search_food_candidates",
                "args": {"query": "鸡腿饭"},
            }
        ],
    )
    proposal_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "meal-proposal",
                "name": "propose_nutrition_entry",
                "args": {},
            }
        ],
    )
    agent.ainvoke.side_effect = [
        {"messages": [search_call, search, AIMessage(content=first_answer)]},
        {
            "messages": [
                search_call,
                search,
                proposal_call,
                proposal,
                AIMessage(content="估算草稿已创建，请确认。"),
            ]
        },
    ]
    result = await make_handler(agent).execute(make_input(task_type="nutrition_record_draft"))
    assert result.status == "completed"
    assert result.confirmation_cards[0].confirmation_id == confirmation_id
    assert agent.ainvoke.await_count == 2
    retry = agent.ainvoke.await_args_list[1].args[0]["messages"]
    assert search in retry
    assert "propose_nutrition_entry" in retry[-1]["content"]


@pytest.mark.asyncio
async def test_meal_retry_is_bounded_and_preserves_unsaved_advice():
    agent = make_react_agent({"messages": [AIMessage(content="两个汉堡可先估算份量。")]})
    result = await make_handler(agent).execute(make_input(task_type="nutrition_record_draft"))
    assert agent.ainvoke.await_count == 2
    assert result.status == "failed"
    assert result.unpersisted_suggestion == "两个汉堡可先估算份量。"
    assert not result.confirmation_cards
    assert "请说明食物" not in result.error.message


@pytest.mark.asyncio
async def test_meal_does_not_repeat_created_confirmation_with_invalid_card_payload():
    agent = make_react_agent(
        {
            "messages": [
                ToolMessage(
                    name="propose_nutrition_entry",
                    tool_call_id="meal",
                    content=json.dumps({"status": "confirmation_required", "confirmation": {}}),
                ),
                AIMessage(content="请确认"),
            ]
        }
    )
    result = await make_handler(agent).execute(make_input(task_type="nutrition_record_draft"))
    agent.ainvoke.assert_awaited_once()
    assert result.status == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("task_type", ["general_question", "knowledge_retrieval"])
async def test_explicit_web_request_cannot_be_answered_without_actual_search(task_type):
    agent = make_react_agent({"messages": [AIMessage(content="我已经查过网页。")]})
    branch = make_input(task_type=task_type, required_context=[])
    branch = branch.__class__(
        user_id=branch.user_id, task=branch.task, images=(), message="联网查训练恢复知识"
    )
    result = await make_handler(agent).execute(branch)
    assert result.status == "failed"
    assert result.error.code == "WEB_SEARCH_NOT_EXECUTED"


@pytest.mark.asyncio
async def test_actual_web_search_has_citations_and_error_keeps_distinct_reason():
    branch = make_input(task_type="knowledge_retrieval", required_context=[])
    branch = branch.__class__(
        user_id=branch.user_id, task=branch.task, images=(), message="联网查恢复知识"
    )
    for payload, status in [
        (
            {
                "status": "available",
                "searched_at": "2026-10-05",
                "sources": [
                    {"title": "研究", "url": "https://example.com/paper", "excerpt": "依据"}
                ],
            },
            "completed",
        ),
        (
            {
                "status": "unavailable",
                "error_code": "WEB_SEARCH_TIMEOUT",
                "message": "联网搜索超时",
                "sources": [],
            },
            "failed",
        ),
    ]:
        agent = make_react_agent(
            {
                "messages": [
                    ToolMessage(name="search_web", tool_call_id="web", content=json.dumps(payload)),
                    AIMessage(content="基于已有资料回答。"),
                ]
            }
        )
        result = await make_handler(agent).execute(branch)
        assert result.status == status
        if status == "completed":
            assert result.citations[0].source_type == "web"
            assert result.citations[0].source_id == "https://example.com/paper"
        else:
            assert result.error.code == "WEB_SEARCH_TIMEOUT"


@pytest.mark.asyncio
@pytest.mark.parametrize("called", [True, False])
async def test_automatic_web_fallback_requires_actual_call_without_trigger_words(called):
    messages = []
    if called:
        messages.append(
            ToolMessage(
                name="search_web",
                tool_call_id="web",
                content=json.dumps(
                    {
                        "status": "available",
                        "searched_at": "2026-10-05",
                        "sources": [{"title": "研究", "url": "https://example.com/research"}],
                    }
                ),
            )
        )
    messages.append(AIMessage(content="回答及来源"))
    agent = make_react_agent({"messages": messages})
    handler = make_handler(agent)
    branch = replace(
        make_input(required_context=[]),
        knowledge_context={
            "web_search_required": True,
            "evidence_status": "no_evidence",
        },
    )
    result = await handler.execute(branch)
    agent.ainvoke.assert_awaited_once()
    assert result.status == ("completed" if called else "failed")
    if called:
        assert result.citations[0].source_type == "web"
    else:
        assert result.error.code == "WEB_SEARCH_NOT_EXECUTED"


@pytest.mark.asyncio
async def test_general_question_preflight_runs_once_and_greeting_skips_it():
    agent = make_react_agent({"messages": [AIMessage(content="通用回答")]})
    handler = make_handler(agent)
    handler._knowledge_preflight = AsyncMock(
        return_value=await handler.execute(make_input(required_context=[]))
    )
    await handler.execute(make_input(required_context=[]))
    handler._knowledge_preflight.assert_awaited_once()
    branch = replace(make_input(required_context=[]), message="你好")
    await handler.execute(branch)
    handler._knowledge_preflight.assert_awaited_once()
    branch = replace(
        branch,
        message="按给出的数值计算总量",
        knowledge_context={
            "web_search_required": False,
        },
    )
    await handler.execute(branch)
    handler._knowledge_preflight.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "task_type,actions", [("nutrition_record_draft", []), ("food_catalog_draft", ["create"])]
)
async def test_known_food_without_grams_reaches_estimation_and_returns_real_card(
    monkeypatch, task_type, actions
):
    from nxtrep_backend.schemas.agent_task import AgentTaskUpdate

    card_id = uuid4()
    operation = "nutrition_entry_create" if task_type == "nutrition_record_draft" else "food_create"
    tool_name = (
        "propose_nutrition_entry"
        if task_type == "nutrition_record_draft"
        else "propose_custom_food"
    )
    agent = make_react_agent(
        {
            "messages": [
                ToolMessage(
                    name=tool_name,
                    tool_call_id="estimated-food",
                    content=json.dumps(
                        {
                            "status": "confirmation_required",
                            "confirmation": {
                                "confirmation_id": str(card_id),
                                "operation_type": operation,
                                "status": "pending",
                                "impact": "确认后保存",
                                "version": 1,
                                "expires_at": "2099-01-01T00:00:00Z",
                            },
                        }
                    ),
                ),
                AIMessage(content="按常见份量估算了草稿，请核对后确认。"),
            ]
        }
    )
    context = MagicMock()
    context.tool_runs = []
    monkeypatch.setattr(
        "nxtrep_backend.services.agent_handlers.general.load_personal_context",
        AsyncMock(return_value={}),
    )
    task = make_input(task_type=task_type).task.model_copy(
        update={
            "task_update": AgentTaskUpdate(
                parameters={"food_name": "葱烧鸡腿肉"}, missing_fields=["amount_g"]
            ),
            "missing_fields": ["amount_g"],
            "food_catalog_actions": actions,
        }
    )
    branch = replace(
        make_input(task_type=task_type),
        task=task,
        message="帮我记录葱烧鸡腿肉" if not actions else "食品库新增葱烧鸡腿肉",
    )
    result = await GeneralQuestionBranchHandler(lambda _: agent, tool_context=context).execute(
        branch
    )
    assert result.status == "completed" and result.requires_confirmation
    assert result.confirmation_cards[0].confirmation_id == card_id
    agent.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_food_asks_what_was_eaten_without_running_tools():
    from nxtrep_backend.schemas.agent_task import AgentTaskUpdate

    agent = make_react_agent({})
    task = make_input(task_type="nutrition_record_draft").task.model_copy(
        update={
            "task_update": AgentTaskUpdate(missing_fields=["food_name"]),
            "missing_fields": ["food_name"],
        }
    )
    result = await make_handler(agent).execute(
        replace(make_input(task_type="nutrition_record_draft"), task=task, message="帮我记午饭")
    )
    assert result.status == "needs_input"
    assert "吃了哪些食物" in result.result["task_answer"]
    agent.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_nested_grams_are_explained_without_running_tools():
    from nxtrep_backend.schemas.agent_task import AgentTaskUpdate

    agent = make_react_agent({})
    task = make_input(task_type="nutrition_record_draft").task.model_copy(
        update={
            "task_update": AgentTaskUpdate(
                parameters={"items": [{"food_name": "米饭", "amount_g": -200}]}
            ),
        }
    )
    result = await make_handler(agent).execute(
        replace(make_input(task_type="nutrition_record_draft"), task=task)
    )
    assert result.status == "needs_input"
    assert "无效的克数" in result.result["task_answer"]
    agent.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "required_context,should_estimate", [([], True), (["profile"], True), (["workout"], True)]
)
async def test_generic_food_question_can_estimate_but_personal_data_requirements_remain(
    required_context, should_estimate
):
    from nxtrep_backend.schemas.agent_task import AgentTaskUpdate

    agent = make_react_agent({"messages": [AIMessage(content="按常见一份估算，约200至300千卡。 ")]})
    task = make_input(required_context=required_context).task.model_copy(
        update={
            "task_update": AgentTaskUpdate(
                parameters={"food_name": "番茄炒蛋"}, missing_fields=["amount_g"]
            ),
            "missing_fields": ["amount_g"],
        }
    )
    result = await make_handler(agent).execute(
        replace(make_input(), task=task, message="一份番茄炒蛋大概多少热量")
    )
    assert result.status == ("completed" if should_estimate else "needs_input")
    if required_context:
        agent.ainvoke.assert_awaited_once()
    else:
        agent.ainvoke.assert_not_awaited()
