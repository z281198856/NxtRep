import json
from dataclasses import dataclass
from uuid import UUID

from nxtrep_backend.schemas.agent import AgentIntentPlan, AgentIntentTask
from nxtrep_backend.services.agent_context_builder import bound_conversation, bound_payload
from nxtrep_backend.services.conversation import AgentConversationContext
from nxtrep_backend.services.memory import MemoryService


@dataclass(frozen=True, slots=True)
class ActiveMemoryContext:
    id: UUID
    category: str
    content: str
    version: int

    def as_dict(self) -> dict:
        return {
            "id": str(self.id),
            "category": self.category,
            "content": self.content,
            "version": self.version,
        }


TASK_MEMORY_CATEGORIES: dict[str, frozenset[str]] = {
    "schedule_change_draft": frozenset({"schedule", "exercise_limit", "communication_preference"}),
    "training_progression_draft": frozenset(
        {"exercise_limit", "equipment", "communication_preference"}
    ),
    "general_question": frozenset({"communication_preference"}),
    "training_plan_draft": frozenset(
        {
            "long_term_goal",
            "equipment",
            "schedule",
            "exercise_limit",
            "communication_preference",
        }
    ),
    "nutrition_analysis": frozenset(
        {
            "long_term_goal",
            "allergy",
            "dietary_preference",
            "communication_preference",
        }
    ),
    "nutrition_record_draft": frozenset(
        {
            "long_term_goal",
            "allergy",
            "dietary_preference",
            "communication_preference",
        }
    ),
    "nutrition_target_draft": frozenset(
        {"long_term_goal", "allergy", "dietary_preference", "communication_preference"}
    ),
    "body_assessment": frozenset({"long_term_goal", "exercise_limit", "communication_preference"}),
    "body_progress_comparison": frozenset(
        {"long_term_goal", "exercise_limit", "communication_preference"}
    ),
    "body_measurement_draft": frozenset({"exercise_limit", "communication_preference"}),
    "structured_data_query": frozenset({"communication_preference"}),
    "knowledge_retrieval": frozenset({"communication_preference"}),
}


def memory_categories_for_task(task: AgentIntentTask) -> frozenset[str] | None:
    if task.task_type == "memory_write" or "memory" in task.required_context:
        return None
    return TASK_MEMORY_CATEGORIES.get(task.task_type, frozenset())


class AgentContextAssembler:
    def __init__(self, memory_service: MemoryService) -> None:
        self._memory_service = memory_service

    async def load_memories(
        self,
        *,
        user_id: UUID,
        intent_plan: AgentIntentPlan,
    ) -> tuple[ActiveMemoryContext, ...]:
        requested_categories: set[str] = set()
        load_all = False
        for task in intent_plan.tasks:
            categories = memory_categories_for_task(task)
            if categories is None:
                load_all = True
                break
            requested_categories.update(categories)
        if not load_all and not requested_categories:
            return ()

        memories = await self._memory_service.list_memories(
            user_id=user_id,
            category=None,
            limit=50,
        )
        return tuple(
            ActiveMemoryContext(
                id=item.id,
                category=item.category,
                content=item.content,
                version=item.version,
            )
            for item in memories
            if load_all or item.category in requested_categories
        )

    @staticmethod
    def for_task(
        task: AgentIntentTask,
        memories: tuple[ActiveMemoryContext, ...],
    ) -> tuple[ActiveMemoryContext, ...]:
        categories = memory_categories_for_task(task)
        if categories is None:
            return memories
        return tuple(item for item in memories if item.category in categories)


def build_contextual_user_payload(
    *,
    current_message: str,
    conversation_context: AgentConversationContext,
    memories: tuple[ActiveMemoryContext, ...],
) -> str:
    if (
        not conversation_context.summary
        and not conversation_context.recent_messages
        and not memories
        and not conversation_context.task_state
    ):
        return current_message
    return json.dumps(
        {
            "current_user_message": current_message,
            "conversation_context": bound_conversation(
                conversation_context, current_message, limit=12000
            ).as_dict(),
            "active_long_term_memories": bound_payload([item.as_dict() for item in memories], 2000),
        },
        ensure_ascii=False,
    )
