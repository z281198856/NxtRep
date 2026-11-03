import json
from dataclasses import asdict
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from nxtrep_backend.services.agent_context_builder import (
    bound_conversation,
    bound_messages,
    bound_payload,
)
from nxtrep_backend.services.conversation import (
    AgentConversationContext,
    ConversationMessageContext,
)


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str))


def test_storage_history_is_unchanged_while_related_context_is_selected():
    messages = tuple(
        ConversationMessageContext(
            role="user" if index % 2 else "assistant",
            content=f"第{index}条饮食问题" if index != 5 else "卧推之前从60kg修改成55kg",
        )
        for index in range(60)
    )
    identifier = str(uuid4())
    context = AgentConversationContext(
        recent_messages=messages,
        task_state={
            "active_task": {
                "task_id": identifier,
                "task_type": "workout_record_update_draft",
                "entities": {"workout_id": str(uuid4())},
                "parameters": {"exercise_name": "卧推", "weight_kg": "55"},
            },
        },
    )
    bounded = bound_conversation(context, "刚才卧推改回60kg")
    assert context.recent_messages == messages
    assert len(context.recent_messages) == 60
    assert len(bounded.recent_messages) <= 12
    assert any("从60kg修改成55kg" in message.content for message in bounded.recent_messages)
    assert bounded.recent_messages[-1] == messages[-1]
    assert bounded.task_state["active_task"]["task_id"] == identifier


def test_all_dynamic_conversation_parts_share_a_total_budget():
    context = AgentConversationContext(
        summary="旧总结" * 20_000,
        recent_messages=tuple(
            ConversationMessageContext("assistant", "很长回复" * 10_000) for _ in range(40)
        ),
        meal_confirmations=tuple(
            {"confirmation_id": str(uuid4()), "after": "a" * 10_000} for _ in range(20)
        ),
        task_state={
            "active_task": {
                "task_id": str(uuid4()),
                "entities": {"entry_id": str(uuid4())},
                "parameters": {"notes": "笔记" * 20_000},
            }
        },
    )
    projected = bound_conversation(context, "继续")
    assert size(asdict(projected)) <= 24_000
    assert (
        projected.task_state["active_task"]["entities"]
        == context.task_state["active_task"]["entities"]
    )
    assert size(projected.task_state) <= 6_000
    assert size(projected.meal_confirmations) <= 3_500
    assert len(projected.summary) <= 3_500


@pytest.mark.parametrize("limit", [512, 1_000, 2_000, 8_000])
def test_smaller_context_limits_remain_valid(limit):
    context = AgentConversationContext(
        summary="x" * 10_000,
        task_state={
            "active_task": {"task_id": str(uuid4()), "entities": {"entry_id": str(uuid4())}},
        },
        recent_messages=tuple(
            ConversationMessageContext("user", "数据" * 10_000) for _ in range(8)
        ),
    )
    assert size(asdict(bound_conversation(context, limit=limit))) <= limit


@pytest.mark.parametrize(
    "value",
    [
        '汉字\n\t"\\' * 10_000,
        {"document": "q" * 40_000, "workout_id": "123", "success": True},
        [{"a": "长" * 20_000} for _ in range(100)],
        {"nested": {"nested": {"nested": ["x" * 30_000]}}},
    ],
    ids=["escaped_text", "document_and_ids", "large_array", "nested_payload"],
)
def test_payload_is_valid_json_under_budget_including_escaped_strings(value):
    projected = bound_payload(value, 1_000)
    encoded = json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
    assert len(encoded) <= 1_000
    json.loads(encoded)


def test_payload_prioritizes_real_business_ids_over_large_document():
    projected = bound_payload(
        {"document": "x" * 100_000, "entry_id": "actual-id", "success": True}, 512
    )
    assert projected["entry_id"] == "actual-id"
    assert projected["success"] is True


def test_tool_call_and_results_remain_paired_without_rewriting_arguments():
    call = AIMessage(
        content="",
        tool_calls=[{"id": "call-1", "name": "search_food", "args": {"query": "鸡腿饭"}}],
    )
    result = ToolMessage(content='{"status":"empty"}', tool_call_id="call-1")
    messages = [
        HumanMessage(content="x" * 30_000),
        call,
        result,
        HumanMessage(content="换个搜索词"),
    ]
    projected = bound_messages(messages, 2_000)
    assert projected == [call, result, messages[-1]]
    assert projected[0] is call
    assert projected[1] is result


def test_orphan_and_incomplete_tool_blocks_are_not_sent_to_model():
    orphan = ToolMessage(content="孤立结果", tool_call_id="unknown")
    incomplete = AIMessage(content="", tool_calls=[{"id": "pending", "name": "read", "args": {}}])
    user = HumanMessage(content="继续")
    assert bound_messages([orphan, incomplete, user], 2_000) == [user]


def test_oversized_tool_result_drops_entire_block_not_just_its_parent():
    call = AIMessage(content="", tool_calls=[{"id": "huge", "name": "read", "args": {}}])
    result = ToolMessage(content="x" * 10_000, tool_call_id="huge")
    user = HumanMessage(content="继续")
    assert bound_messages([call, result, user], 1_000) == [user]


def test_no_nonfinite_json_values_or_arbitrary_runtime_objects_are_retained():
    projected = bound_payload({"value": float("nan"), "infinite": float("inf")}, 100)
    assert projected == {"value": None, "infinite": None}
