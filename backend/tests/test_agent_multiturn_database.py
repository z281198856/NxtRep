"""Run the multi-turn graph against real PostgreSQL and original business services."""

import os
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from test_agent_multiturn_pipeline import make_graph, route_to, tool_context

from nxtrep_backend.db.models import (
    AgentMessage,
    Confirmation,
    Exercise,
    NutritionEntry,
    User,
    Workout,
    WorkoutSet,
)
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.conversation import SqlAlchemyConversationRepository
from nxtrep_backend.repositories.exercise import SqlAlchemyExercisesRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.repositories.workout import SqlAlchemyWorkoutRepository
from nxtrep_backend.schemas.agent import AgentChatRequest
from nxtrep_backend.schemas.nutrition import NutritionEntryCreateRequest
from nxtrep_backend.services.agent_task_state import TaskStateManager
from nxtrep_backend.services.agent_workflow import AgentWorkflowService
from nxtrep_backend.services.confirmation import DatabaseConfirmationService
from nxtrep_backend.services.conversation import ConversationService
from nxtrep_backend.services.exercise import ExercisesService
from nxtrep_backend.services.nutrition import NutritionService
from nxtrep_backend.services.workout import WorkoutService
from nxtrep_backend.services.workout_record import WorkoutRecordService

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


async def seed(session):
    user = User(username=f"multiturn-eval-{uuid4().hex}", password_setup_required=False)
    session.add(user)
    await session.flush()
    exercises = [
        Exercise(owner_user_id=user.id, name_zh=name, equipment="barbell")
        for name in ("多轮验收卧推", "多轮验收上斜卧推")
    ]
    session.add_all(exercises)
    await session.flush()
    confirmations = SqlAlchemyConfirmationRepository(session)
    commands = DatabaseConfirmationService(confirmations)
    workout = WorkoutService(
        SqlAlchemyWorkoutRepository(session), SqlAlchemyTrainingRepository(session)
    )
    nutrition = NutritionService(SqlAlchemyNutritionRepository(session), confirmations)
    service = WorkoutRecordService(
        workout, confirmations, ExercisesService(SqlAlchemyExercisesRepository(session))
    )
    context = tool_context(
        user.id,
        service,
        workout_service=workout,
        nutrition_service=nutrition,
        confirmation_service=commands,
    )
    conversations = ConversationService(SqlAlchemyConversationRepository(session))
    return user, exercises, context, commands, conversations


@pytest.mark.asyncio
async def test_persistent_slots_long_context_correction_append_and_business_undo():
    async with SessionFactory() as session:
        owner_id = None
        try:
            user, exercises, context, commands, conversations = await seed(session)
            owner_id = user.id

            def route(message, **_):
                if "记录" in message:
                    return route_to("workout_record_draft", {"exercise_name": exercises[0].name_zh})
                if "再加" in message:
                    return route_to("workout_record_draft", {"exercise_name": exercises[1].name_zh})
                return route_to("general_question")

            router = SimpleNamespace(route=AsyncMock(side_effect=route))
            workflow = AgentWorkflowService(
                make_graph(router, context, conversations.save_task_state), conversations
            )
            identifier = None

            async def turn(message):
                nonlocal identifier
                response = await workflow.chat(
                    user_id=user.id,
                    request=AgentChatRequest(message=message, conversation_id=identifier),
                )
                identifier = response.conversation_id
                return response

            await turn("帮我记录今天卧推")
            conversation = await conversations.get_conversation(
                user_id=user.id, conversation_id=identifier
            )
            task_id = TaskStateManager.load(conversation.task_state).active_task.task_id
            await turn("60kg")
            assert (
                await session.scalar(
                    select(func.count()).select_from(Workout).where(Workout.user_id == user.id)
                )
                == 0
            )
            pending = await turn("四组每组8个")
            assert len(pending.confirmation_cards) == 1
            created = await commands.approve(
                user.id, pending.confirmation_cards[0].confirmation_id, 1
            )
            workout_id = UUID(created.result["workout_id"])
            bench_id = UUID(created.result["workout_exercise_id"])
            assert len(created.result["sets"]) == 4

            for _ in range(30):
                answer = await turn("一份鸡腿饭多少热量？")
                assert not answer.confirmation_cards
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AgentMessage)
                    .where(AgentMessage.conversation_id == identifier)
                )
                == 66
            )
            conversation = await conversations.get_conversation(
                user_id=user.id, conversation_id=identifier
            )
            task = TaskStateManager.load(conversation.task_state).active_task
            assert task.task_id == task_id and task.entities["workout_id"] == str(workout_id)

            correction = await turn("不对，是55kg")
            assert correction.confirmation_cards[0].operation_type == "workout_record_update"
            before = (
                await context.workout_record_service.read_for_change(
                    user.id, workout_id=workout_id, workout_exercise_id=bench_id
                )
            )["selected_record"]
            assert {Decimal(row["weight_kg"]) for row in before["sets"]} == {Decimal("60")}
            await commands.approve(user.id, correction.confirmation_cards[0].confirmation_id, 1)
            changed = (
                await context.workout_record_service.read_for_change(
                    user.id, workout_id=workout_id, workout_exercise_id=bench_id
                )
            )["selected_record"]
            assert {Decimal(row["weight_kg"]) for row in changed["sets"]} == {Decimal("55")}
            assert (
                await session.scalar(
                    select(func.count()).select_from(Workout).where(Workout.user_id == user.id)
                )
                == 1
            )

            append = await turn("再加一个上斜卧推")
            assert append.status == "needs_input" and not append.confirmation_cards
            await turn("30kg")
            append = await turn("三组每组12次")
            appended = await commands.approve(
                user.id, append.confirmation_cards[0].confirmation_id, 1
            )
            assert appended.result["workout_id"] == str(workout_id)
            incline_id = UUID(appended.result["workout_exercise_id"])
            undo = await turn("算了，刚才那条不要了")
            assert undo.confirmation_cards[0].operation_type == "workout_record_void"
            assert (
                await context.workout_record_service.read_for_change(
                    user.id, workout_id=workout_id, workout_exercise_id=incline_id
                )
            )["status"] == "available"
            await commands.approve(user.id, undo.confirmation_cards[0].confirmation_id, 1)
            aggregate = await context.workout_service.get_aggregate(user.id, workout_id)
            assert len(aggregate.sets_by_exercise.get(bench_id, [])) == 4
            assert not aggregate.sets_by_exercise.get(incline_id)
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WorkoutSet)
                    .where(WorkoutSet.workout_exercise_id == bench_id)
                )
                == 4
            )
        finally:
            await session.rollback()
            if owner_id is not None:
                await session.execute(delete(Exercise).where(Exercise.owner_user_id == owner_id))
                await session.execute(delete(User).where(User.id == owner_id))
                await session.commit()


@pytest.mark.asyncio
async def test_saved_meal_named_reference_changes_only_selected_item_and_ambiguous_delete_asks():
    async with SessionFactory() as session:
        owner_id = None
        try:
            user, _, context, commands, conversations = await seed(session)
            owner_id = user.id
            meal = await context.nutrition_service.propose_entry(
                user_id=user.id,
                body=NutritionEntryCreateRequest(
                    meal_type="lunch",
                    eaten_at=datetime.now(UTC),
                    items=[
                        {
                            "name": name,
                            "amount_g": amount,
                            "basis_amount_g": 100,
                            "kcal": 150,
                            "protein_g": 20,
                            "carbs_g": 10,
                            "fat_g": 3,
                            "source": "model_estimated",
                            "confidence": "low",
                        }
                        for name, amount in (("米饭", 200), ("鸡胸肉", 150))
                    ],
                ),
            )
            await commands.approve(user.id, meal.id, meal.version)
            entry_id = UUID(meal.result["resource_id"])
            conversation = await conversations.create_conversation(
                user_id=user.id, title="多轮餐食验收"
            )
            state = TaskStateManager.apply_plan({}, "nutrition_entry_update_draft")
            state = TaskStateManager.commit_results(
                state,
                [
                    {
                        "status": "available",
                        "selected_entry": {
                            "entry_id": str(entry_id),
                            "version": 1,
                            "date": "2026-10-08",
                            "meal_type": "lunch",
                            "items": [
                                {"name": "米饭", "amount_g": "200"},
                                {"name": "鸡胸肉", "amount_g": "150"},
                            ],
                        },
                    }
                ],
            )
            await conversations.save_task_state(
                user_id=user.id,
                conversation_id=conversation.id,
                task_state=state.model_dump(mode="json"),
            )
            router = SimpleNamespace(
                route=AsyncMock(
                    return_value=route_to(
                        "nutrition_entry_delete_draft", entities={"entry_id": str(entry_id)}
                    )
                )
            )
            workflow = AgentWorkflowService(
                make_graph(router, context, conversations.save_task_state), conversations
            )
            correction = await workflow.chat(
                user_id=user.id,
                request=AgentChatRequest(
                    message="刚才那个鸡胸肉改成200g", conversation_id=conversation.id
                ),
            )
            assert correction.confirmation_cards[0].operation_type == "nutrition_entry_update"
            assert correction.confirmation_cards[0].after["changes"] == [
                {"item_index": 1, "amount_g": "200"}
            ]
            entry = await context.nutrition_service.get_saved_entry(user.id, entry_id)
            assert Decimal(entry.items[1]["amount_g"]) == Decimal("150")
            await commands.approve(user.id, correction.confirmation_cards[0].confirmation_id, 1)
            entry = await context.nutrition_service.get_saved_entry(user.id, entry_id)
            assert Decimal(entry.items[0]["amount_g"]) == Decimal("200")
            assert Decimal(entry.items[1]["amount_g"]) == Decimal("200")
            count = (
                select(func.count())
                .select_from(Confirmation)
                .where(Confirmation.user_id == user.id)
            )
            before = await session.scalar(count)
            clarification = await workflow.chat(
                user_id=user.id,
                request=AgentChatRequest(message="把刚才那个删了", conversation_id=conversation.id),
            )
            assert clarification.status == "needs_input" and not clarification.confirmation_cards
            assert await session.scalar(count) == before
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(NutritionEntry)
                    .where(NutritionEntry.user_id == user.id)
                )
                == 1
            )
            removal = await workflow.chat(
                user_id=user.id,
                request=AgentChatRequest(
                    message="只删除午饭中的鸡胸肉，保留米饭和整顿午饭",
                    conversation_id=conversation.id,
                ),
            )
            assert removal.status == "completed" and len(removal.confirmation_cards) == 1
            removal_card = removal.confirmation_cards[0]
            assert removal_card.operation_type == "nutrition_entry_update"
            assert removal_card.after["remove_item_indices"] == [1]
            assert removal_card.after["changes"] == []
            await commands.approve(user.id, removal_card.confirmation_id, 1)
            entry = await context.nutrition_service.get_saved_entry(user.id, entry_id)
            assert len(entry.items) == 1 and entry.items[0]["name"] == "米饭"
            assert Decimal(entry.items[0]["amount_g"]) == 200
            assert len(router.semantic_calls) == 3
            router.route.assert_awaited_once()
        finally:
            await session.rollback()
            if owner_id is not None:
                await session.execute(delete(Exercise).where(Exercise.owner_user_id == owner_id))
                await session.execute(delete(User).where(User.id == owner_id))
                await session.commit()
