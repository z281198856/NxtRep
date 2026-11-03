"""Recover malformed planning output before switching providers or executing tools."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_deepseek import ChatDeepSeek
from test_agent_intent_router import make_dependencies, make_task, meal_context

from nxtrep_backend.agents.intent_router import AgentIntentRouter, AgentIntentRoutingError
from nxtrep_backend.schemas.agent import AgentIntentPlan


@pytest.mark.asyncio
async def test_deepseek_planning_uses_json_channel_with_schema_and_local_validation():
    model = MagicMock(spec=ChatDeepSeek)
    structured = MagicMock()
    expected = AgentIntentPlan(tasks=[make_task("structured_data_query", [])])
    structured.ainvoke = AsyncMock(return_value={"parsed": expected})
    model.with_structured_output.return_value = structured
    result = await AgentIntentRouter(model).route(message="核对午餐营养", images=[])
    assert result == expected
    model.with_structured_output.assert_called_once_with(
        AgentIntentPlan, method="json_mode", include_raw=True,
    )
    prompt = structured.ainvoke.await_args.args[0][0].content
    assert "JSON Schema" in prompt and '"additionalProperties": false' in prompt
    assert '"missing_fields"' in prompt and '"needs_clarification"' in prompt


def malformed():
    arguments = '{"tasks": []}, "needs_clarification": true}'
    return {
        "parsed": None,
        "parsing_error": None,
        "raw": AIMessage(content="", invalid_tool_calls=[{
            "name": "AgentIntentPlan", "id": "bad-plan", "args": arguments,
            "error": "Extra data", "type": "invalid_tool_call",
        }]),
    }


@pytest.mark.parametrize("truncated", [True, False])
def test_partial_json_cannot_be_executed_even_if_sdk_returned_a_parsed_plan(truncated):
    plan = AgentIntentPlan(tasks=[make_task("nutrition_entry_delete_draft", [])])
    raw = AIMessage(
        content=plan.model_dump_json()[:-1] if truncated else plan.model_dump_json(),
        response_metadata={"finish_reason": "stop" if truncated else "length"},
    )
    with pytest.raises(AgentIntentRoutingError, match="structured output"):
        AgentIntentRouter._parse_response({"parsed": plan, "raw": raw, "parsing_error": None})


@pytest.mark.asyncio
async def test_primary_format_failure_is_corrected_before_using_slow_fallback():
    primary, first = make_dependencies()
    fallback, other = make_dependencies()
    task = make_task("nutrition_entry_delete_draft", []).model_copy(
        update={"missing_fields": ["selection"]}
    )
    expected = AgentIntentPlan(
        tasks=[task], needs_clarification=True,
        clarification_questions=["你要删除整餐，还是餐内哪项食物？"],
    )
    first.ainvoke.side_effect = [malformed(), {"parsed": expected}]
    result = await AgentIntentRouter(primary, fallback).route(
        message="把刚才那个删了", images=[], conversation_context=meal_context(),
    )
    assert result == expected
    assert first.ainvoke.await_count == 2
    other.ainvoke.assert_not_awaited()
    repair = first.ainvoke.await_args.args[0]
    assert isinstance(repair[-2], SystemMessage)
    assert isinstance(repair[-1], HumanMessage)
    diagnostic = json.loads(repair[-1].content)
    assert diagnostic["invalid_tool_calls"][0]["arguments"].endswith("true}")


@pytest.mark.asyncio
async def test_meal_feedback_review_also_recovers_invalid_json_without_fallback():
    primary, first = make_dependencies()
    fallback, other = make_dependencies()
    wrong = AgentIntentPlan(tasks=[make_task("nutrition_record_draft", [])])
    expected = AgentIntentPlan(tasks=[make_task("structured_data_query", [])])
    first.ainvoke.side_effect = [{"parsed": wrong}, malformed(), {"parsed": expected}]
    result = await AgentIntentRouter(primary, fallback).route(
        message="碳水应该不超过六十克", images=[], conversation_context=meal_context(),
    )
    assert result == expected
    assert first.ainvoke.await_count == 3
    other.ainvoke.assert_not_awaited()
    original_review = json.loads(first.ainvoke.await_args_list[1].args[0][-1].content)
    repaired_review = first.ainvoke.await_args_list[2].args[0]
    assert json.loads(repaired_review[1].content) == original_review
    assert original_review["validation_conflicts"][0]["code"] == "MEAL_FEEDBACK_IS_READ_ONLY"


@pytest.mark.asyncio
async def test_timeout_is_not_retried_as_a_format_failure():
    primary, first = make_dependencies()
    fallback, other = make_dependencies()
    first.ainvoke.side_effect = TimeoutError()
    expected = AgentIntentPlan(tasks=[make_task("general_question", [])])
    other.ainvoke.return_value = {"parsed": expected}
    result = await AgentIntentRouter(primary, fallback).route(message="解释训练容量", images=[])
    assert result == expected
    first.ainvoke.assert_awaited_once()
    other.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_review_has_the_same_bounded_format_recovery():
    primary, first = make_dependencies()
    fallback, other = make_dependencies()
    memory = AgentIntentPlan(tasks=[make_task("memory_write", [])])
    expected = AgentIntentPlan(tasks=[make_task("general_question", [])])
    first.ainvoke.side_effect = [{"parsed": memory}, malformed(), {"parsed": expected}]
    result = await AgentIntentRouter(primary, fallback).route(message="我喜欢哑铃训练", images=[])
    assert result == expected
    assert first.ainvoke.await_count == 3
    other.ainvoke.assert_not_awaited()
