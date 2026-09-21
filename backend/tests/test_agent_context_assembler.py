from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.schemas.agent import AgentIntentPlan, AgentIntentTask
from nxtrep_backend.services.agent_context import AgentContextAssembler
from nxtrep_backend.services.memory import MemoryService


def make_task(task_type: str, required_context: list[str] | None = None):
    return AgentIntentTask(
        task_type=task_type,
        required_context=required_context or [],
        confidence="high",
        routing_reason="test",
    )


@pytest.mark.asyncio
async def test_training_task_loads_only_relevant_memories() -> None:
    service = MagicMock(spec=MemoryService)
    service.list_memories = AsyncMock(
        return_value=[
            SimpleNamespace(id=uuid4(), category="equipment", content="只有哑铃", version=1),
            SimpleNamespace(id=uuid4(), category="allergy", content="花生过敏", version=1),
            SimpleNamespace(
                id=uuid4(),
                category="communication_preference",
                content="回答简洁",
                version=1,
            ),
        ]
    )
    assembler = AgentContextAssembler(service)
    user_id = uuid4()

    memories = await assembler.load_memories(
        user_id=user_id,
        intent_plan=AgentIntentPlan(tasks=[make_task("training_plan_draft")]),
    )

    assert {item.category for item in memories} == {
        "equipment",
        "communication_preference",
    }
    service.list_memories.assert_awaited_once_with(
        user_id=user_id,
        category=None,
        limit=50,
    )


@pytest.mark.asyncio
async def test_explicit_memory_context_loads_all_categories() -> None:
    item = SimpleNamespace(
        id=uuid4(),
        category="dietary_preference",
        content="不吃牛肉",
        version=2,
    )
    service = MagicMock(spec=MemoryService)
    service.list_memories = AsyncMock(return_value=[item])
    assembler = AgentContextAssembler(service)

    memories = await assembler.load_memories(
        user_id=uuid4(),
        intent_plan=AgentIntentPlan(tasks=[make_task("structured_data_query", ["memory"])]),
    )

    assert len(memories) == 1
    assert memories[0].content == "不吃牛肉"
