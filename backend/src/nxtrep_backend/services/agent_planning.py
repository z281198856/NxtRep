from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from uuid import UUID

from nxtrep_backend.agents.intent_router import AgentIntentRouter
from nxtrep_backend.schemas.agent import (
    AgentChatRequest,
    AgentContextHints,
    AgentIntentPlan,
)
from nxtrep_backend.schemas.agent_task import AgentTaskUpdate
from nxtrep_backend.services.agent_context import (
    ActiveMemoryContext,
    AgentContextAssembler,
)
from nxtrep_backend.services.agent_context_builder import bound_conversation
from nxtrep_backend.services.agent_media import (
    AgentImageAssetResolver,
    ResolvedAgentImage,
)
from nxtrep_backend.services.agent_nutrition_feedback import is_nutrition_estimate_feedback
from nxtrep_backend.services.agent_task_parameters import (
    ground_meal_date_parameters,
    normalize_task_parameters,
    remaining_draft_fields,
)
from nxtrep_backend.services.agent_task_state import (
    TaskStateManager,
    candidate_entities,
    is_business_removal_request,
)
from nxtrep_backend.services.conversation import AgentConversationContext


@dataclass(frozen=True, slots=True)
class PlannedAgentRequest:
    images: tuple[ResolvedAgentImage, ...]
    intent_plan: AgentIntentPlan
    conversation_context: AgentConversationContext = AgentConversationContext()
    memories: tuple[ActiveMemoryContext, ...] = ()
    context_hints: AgentContextHints = field(default_factory=AgentContextHints)


class AgentRequestPlanner:
    def __init__(
        self,
        *,
        resolver: AgentImageAssetResolver,
        intent_router: AgentIntentRouter,
        context_assembler: AgentContextAssembler,
        state_writer: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        self._resolver = resolver
        self._intent_router = intent_router
        self._context_assembler = context_assembler
        self._state_writer = state_writer

    async def plan(
        self,
        *,
        user_id: UUID,
        request: AgentChatRequest,
        conversation_context: AgentConversationContext,
    ) -> PlannedAgentRequest:
        if request.image_asset_ids:
            images = await self._resolver.resolve(
                user_id=user_id,
                asset_ids=request.image_asset_ids,
            )
        else:
            images = []

        original_state = conversation_context.task_state
        prepared = TaskStateManager.prepare_turn(original_state, request.message)
        removal_requested = is_business_removal_request(request.message)
        hints = (
            prepared.model_dump(mode="json", exclude={"state"})
            if prepared.parameters or prepared.handled or prepared.selection
            or prepared.transition or prepared.clarification_required
            else {}
        )
        if prepared.selection:
            # Raw candidate order is not evidence of the list the user saw.
            hints.pop("selection", None)
            hints.pop("entities", None)
            hints["parameters"] = {key: value for key, value in hints.get("parameters", {}).items()
                                   if key not in {"exercise_name", "food_name"}}
        displayed = TaskStateManager.displayed_selection(
            original_state, request.message, conversation_context.recent_messages,
        )
        if displayed:
            hints["displayed_selection"] = displayed
        # Parsing supplies context; it never grants permission or bypasses the LLM.
        intent_plan = await self._intent_router.route(
            message=request.message,
            images=images,
            conversation_context=bound_conversation(
                replace(conversation_context, input_hints=hints), request.message, limit=16000
            ),
            context_hints=request.context_hints,
        )
        conversation_context = replace(conversation_context, input_hints={})
        state = TaskStateManager.load(original_state)
        tasks = []
        for task in intent_plan.tasks:
            update = task.task_update or AgentTaskUpdate(missing_fields=task.missing_fields)
            active = state.active_task
            if (
                active and task.task_type == "workout_record_draft"
                and update.transition == "correct"
                and active.entities.get("workout_exercise_id")
            ):
                task = task.model_copy(update={"task_type": "workout_record_update_draft"})
            if (
                active and prepared.parameters
                and prepared.transition in {"continue", "correct"}
                and update.transition in {"continue", "correct"}
                and task.task_type == active.task_type
            ):
                update = update.model_copy(update={
                    "parameters": {
                        **{key: value for key, value in prepared.parameters.items()
                           if key not in {"exercise_name", "food_name"}},
                        **update.parameters,
                    },
                })
            if active and update.transition == "cancel":
                cancelled = TaskStateManager.apply_plan(state, active.task_type, update)
                if cancelled.active_task and cancelled.active_task.status == "cancelled":
                    state = cancelled
                    task = task.model_copy(update={"task_type": "general_question"})
                elif active.status == "awaiting_confirmation" or any(
                    candidate.kind == "confirmation" for candidate in active.candidates
                ):
                    task = task.model_copy(update={"task_type": "confirmation_cancel"})
                    update = update.model_copy(update={"transition": "correct"})
                elif active.entities.get("workout_exercise_id"):
                    task = task.model_copy(update={"task_type": "workout_record_void_draft"})
                    update = update.model_copy(update={"transition": "correct"})
                elif active.entities.get("entry_id") or active.entities.get("meal_id"):
                    task = task.model_copy(update={"task_type": "nutrition_entry_delete_draft"})
                    update = update.model_copy(update={"transition": "correct"})
            if active and task.task_type in {
                "nutrition_entry_update_draft", "nutrition_entry_delete_draft",
                "workout_record_update_draft", "workout_record_void_draft",
                "workout_record_draft",
            } and update.transition != "new" and "selection" not in update.missing_fields:
                matches = []
                for candidate in active.candidates:
                    identity = candidate_entities(candidate)
                    if not identity or any(
                        key in update.entities and update.entities[key] != value
                        for key, value in identity.items()
                    ):
                        continue
                    name = update.parameters.get(
                        "exercise_name" if candidate.kind == "exercise" else "food_name"
                    )
                    identified = all(
                        update.entities.get(key) == value for key, value in identity.items()
                    )
                    if identified or (
                        candidate.kind in {"exercise", "meal_item", "food_item"}
                        and name == candidate.label
                    ):
                        matches.append(identity)
                if len(matches) == 1:
                    # Ground the model's chosen name/ID, never the parser's ordinal.
                    # The displayed list can have a different order from raw search.
                    update = update.model_copy(update={
                        "entities": {**matches[0], **update.entities},
                    })
            if (
                displayed and active and task.task_type == active.task_type
                and update.transition in {"continue", "correct"}
                and all(key not in update.entities or update.entities[key] == value
                        for key, value in displayed["entities"].items())
            ):
                # Intent came from the model; the selected row comes from the
                # actual prior reply, not a search ordering or guessed alias.
                update = update.model_copy(update={
                    "entities": {**displayed["entities"], **update.entities},
                    "missing_fields": [f for f in update.missing_fields if f != "selection"],
                })
                task = task.model_copy(update={
                    "missing_fields": [f for f in task.missing_fields if f != "selection"],
                })
            if prepared.clarification_required and removal_requested:
                # A semantic plan cannot authorize choosing one of several candidates
                # when the user supplied only a generic deletion reference.
                update = update.model_copy(update={
                    "transition": "continue",
                    "entities": {k: v for k, v in update.entities.items() if k != "item_index"},
                    "missing_fields": [*update.missing_fields, "selection"],
                })
                if state.active_task:
                    state.active_task.entities.pop("item_index", None)
            if task.task_type == "nutrition_entry_update_draft":
                previous_parameters = (
                    state.active_task.parameters
                    if state.active_task and update.transition != "new" else {}
                )
                update = update.model_copy(update={"parameters": ground_meal_date_parameters(
                    request.message, update.parameters, previous_parameters,
                    timezone=request.context_hints.timezone,
                    occurred_at=request.context_hints.occurred_at,
                )})
            valid_parameters, invalid_parameters = normalize_task_parameters(
                update.parameters,
                timezone=request.context_hints.timezone,
                occurred_at=request.context_hints.occurred_at,
                task_type=task.task_type,
            )
            if invalid_parameters and state.active_task:
                # A rejected correction must not quietly reuse the previous value.
                for field in invalid_parameters:
                    state.active_task.parameters.pop(field, None)
            update = update.model_copy(
                update={
                    "parameters": valid_parameters,
                    "invalid_fields": list(
                        dict.fromkeys([*update.invalid_fields, *invalid_parameters])
                    ),
                    "missing_fields": list(
                        dict.fromkeys(
                            [*task.missing_fields, *update.missing_fields, *invalid_parameters]
                        )
                    ),
                }
            )
            if (
                task.task_type == "nutrition_entry_update_draft"
                and valid_parameters.get("action") == "change_date"
                and valid_parameters.get("scope") in {"day", "meals"}
            ):
                # An explicit day or multi-meal scope is resolved by the source-day read,
                # not by an old single food/meal selection.
                meal_keys = {"entry_id", "meal_id", "item_index"}
                update = update.model_copy(update={
                    "entities": {k: v for k, v in update.entities.items() if k not in meal_keys}
                })
                if state.active_task and update.transition in {"continue", "correct"}:
                    for key in meal_keys:
                        state.active_task.entities.pop(key, None)
            if task.task_update is not None:
                # Internal IDs must be supported by state or the current input. The
                # existing read tools can discover other owned entities afterwards.
                known = state.active_task.entities if state.active_task else {}
                if update.transition == "correct":
                    grounded = [previous for previous in TaskStateManager.tasks(state) if any(
                        key.endswith("_id") and update.entities.get(key) == value
                        for key, value in previous.entities.items()
                    )]
                    if len(grounded) == 1:
                        known = grounded[0].entities
                if update.transition == "resume":
                    restored = TaskStateManager.resume_candidate(state, update, task.task_type)
                    known = restored.entities if restored else {}
                if not known and update.transition == "correct" and state.suspended_task:
                    known = state.suspended_task.entities
                verified_meals = {
                    (key, str(item[key]))
                    for item in conversation_context.meal_confirmations
                    for key in ("confirmation_id", "entry_id")
                    if item.get(key)
                }
                verified_candidates = {
                    (key, str(value))
                    for candidate in (state.active_task.candidates if state.active_task else [])
                    if update.transition != "new"
                    for key, value in candidate_entities(candidate).items()
                }
                reference_pairs = set(verified_meals)
                for previous_task in TaskStateManager.tasks(state):
                    if previous_task:
                        reference_pairs.update(previous_task.entities.items())
                        reference_pairs.update(previous_task.reference_entities.items())
                references = {
                    key: value for key, value in update.reference_entities.items()
                    if not key.endswith("_id")
                    or (key, str(value)) in reference_pairs
                    or str(value) in request.message
                }
                update = update.model_copy(update={"reference_entities": references})
                update = update.model_copy(
                    update={
                        "entities": {
                            key: value
                            for key, value in update.entities.items()
                            if not key.endswith("_id")
                            or str(value) == str(known.get(key))
                            or (key, str(value)) in verified_meals
                            or (key, str(value)) in verified_candidates
                            or str(value) in request.message
                        }
                    }
                )
            if (
                state.active_task
                and update.transition in {"continue", "correct"}
                and task.task_type
                in {
                    "nutrition_record_draft",
                    "nutrition_entry_update_draft",
                    "nutrition_entry_delete_draft",
                }
                and isinstance(update.parameters.get("food_name"), str)
                and update.parameters["food_name"] in request.message
                and update.parameters["food_name"]
                != state.active_task.parameters.get("food_name")
            ):
                # Naming another food in the same meal is a local target switch.
                # Discard the previous food position and resolve the new name from
                # the actual meal read; the meal ID remains subject to conflict checks.
                state.active_task.entities.pop("item_index", None)
                update = update.model_copy(
                    update={
                        "entities": {
                            key: value
                            for key, value in update.entities.items()
                            if key != "item_index"
                        }
                    }
                )
            state = TaskStateManager.apply_plan(state, task.task_type, update)
            active = state.active_task
            if active and task.task_type == active.task_type:
                if (
                    task.task_type in {"nutrition_record_draft", "nutrition_entry_update_draft"}
                    and is_nutrition_estimate_feedback(request.message)
                    and any(
                        active.entities.get(key)
                        for key in ("confirmation_id", "entry_id", "meal_id")
                    )
                ):
                    # Reestimating an existing model item does not require new eaten
                    # grams. Preserve target ambiguity and explicitly invalid values.
                    estimable = {
                        "amount_g",
                        "basis_amount_g",
                        "kcal",
                        "protein_g",
                        "carbs_g",
                        "fat_g",
                        "nutrients",
                        "nutrition",
                    }
                    active.missing_fields = [
                        field
                        for field in active.missing_fields
                        if field.rsplit(".", 1)[-1] not in estimable
                        or field in active.invalid_fields
                        or field.rsplit(".", 1)[-1] in active.invalid_fields
                    ]
                    food = active.parameters.get("food_name")
                    if (
                        isinstance(food, str)
                        and food not in request.message
                        and "food_name" not in update.parameters
                    ):
                        # Meal-wide estimate feedback must not inherit the rice (or
                        # another food) selected by a previous portion-only correction.
                        active.entities.pop("item_index", None)
                        active.parameters.pop("food_name", None)
                        if "amount_g" not in update.parameters:
                            active.parameters.pop("amount_g", None)
                active.missing_fields = remaining_draft_fields(
                    task.task_type,
                    active.missing_fields,
                    active.parameters,
                    active.entities,
                    invalid_fields=active.invalid_fields,
                    food_catalog_actions=task.food_catalog_actions,
                    required_context=task.required_context,
                )
                active.invalid_fields = [
                    field for field in active.invalid_fields if field in active.missing_fields
                ]
                if active.status in {"collecting", "ready"}:
                    active.status = "collecting" if active.missing_fields else "ready"
                    if active.current_step != "await_user_details":
                        active.current_step = (
                            "collect_parameters" if active.missing_fields else "propose_action"
                        )
                update = update.model_copy(
                    update={
                        "entities": active.entities,
                        "reference_entities": active.reference_entities,
                        "parameters": {
                            **active.parameters,
                            "_changed_fields": list(update.parameters),
                        },
                        "missing_fields": active.missing_fields,
                        "invalid_fields": active.invalid_fields,
                    }
                )
                task = task.model_copy(
                    update={
                        "task_id": active.task_id,
                        "task_update": update,
                        "missing_fields": active.missing_fields,
                        "invalid_fields": active.invalid_fields,
                    }
                )
            tasks.append(task)
        intent_plan = intent_plan.model_copy(update={"tasks": tasks})
        raw_state = (
            state.model_dump(mode="json") if state.active_task or state.suspended_task else {}
        )
        conversation_context = replace(conversation_context, task_state=raw_state)
        if self._state_writer is not None and request.conversation_id is not None and raw_state:
            await self._state_writer(
                user_id=user_id,
                conversation_id=request.conversation_id,
                task_state=conversation_context.task_state,
            )
        memories = await self._context_assembler.load_memories(
            user_id=user_id,
            intent_plan=intent_plan,
        )

        return PlannedAgentRequest(
            images=tuple(images),
            intent_plan=intent_plan,
            conversation_context=conversation_context,
            memories=memories,
            context_hints=request.context_hints,
        )
