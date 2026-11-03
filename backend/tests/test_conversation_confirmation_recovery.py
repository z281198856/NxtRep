import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from nxtrep_backend.db.models import (
    AgentConversation,
    AgentRun,
    CalendarEvent,
    CalendarRescheduleDraft,
    Confirmation,
    NutritionEntry,
    NutritionTargetDraft,
    ProgressionDraft,
    TrainingPlanDraft,
    User,
    Workout,
)
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.conversation import SqlAlchemyConversationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.nutrition import (
    NutritionEntryCreateRequest,
    NutritionItemInput,
    NutritionPendingEntryRevisionRequest,
    NutritionPortionChange,
)
from nxtrep_backend.services.confirmation import DatabaseConfirmationService
from nxtrep_backend.services.conversation import AgentConversationNotFoundError, ConversationService
from nxtrep_backend.services.nutrition import NutritionService

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


def link_run(user, conversation, cards):
    return AgentRun(
        user_id=user.id,
        conversation_id=conversation.id,
        status="succeeded",
        request_payload={},
        started_at=datetime.now(UTC),
        result_payload={
            "confirmation_cards": [
                {"confirmation_id": str(card.id), "status": "pending", "version": 1}
                for card in cards
            ]
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("run_state", ["failed", "cancelled", "running"])
async def test_journal_recovers_real_owned_proposal_without_final_response(run_state):
    async with SessionFactory() as session:
        try:
            owner = User(username=f"journal-{uuid4().hex}", password_setup_required=False)
            other = User(username=f"journal-foreign-{uuid4().hex}", password_setup_required=False)
            session.add_all([owner, other])
            await session.flush()
            conversation = AgentConversation(user_id=owner.id)
            unrelated = AgentConversation(user_id=owner.id)
            session.add_all([conversation, unrelated])
            await session.flush()
            cards = [Confirmation(
                user_id=user.id, operation_type="food_create", after={"food": {"name": "草稿"}},
                reason="验收", impact="确认后保存", status="pending",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ) for user in (owner, other, owner)]
            session.add_all(cards)
            await session.flush()
            session.add_all([
                AgentRun(
                    user_id=owner.id, conversation_id=conversation.id, status=run_state,
                    request_payload={}, started_at=datetime.now(UTC), result_payload=None,
                    checkpoint={"node": "failed", "confirmation_refs": [
                        str(cards[0].id), str(cards[1].id), str(uuid4()), "invalid-id",
                    ]},
                ),
                AgentRun(
                    user_id=owner.id, conversation_id=unrelated.id, status="failed",
                    request_payload={}, started_at=datetime.now(UTC),
                    checkpoint={"confirmation_refs": [str(cards[2].id)]},
                ),
            ])
            await session.flush()
            service = ConversationService(SqlAlchemyConversationRepository(session))
            restored = await service.restore_confirmations(
                user_id=owner.id, conversation_id=conversation.id,
            )
            assert [card.confirmation_id for card in restored.confirmation_cards] == [cards[0].id]
            assert restored.confirmation_cards[0].status == "pending"
            assert restored.resolved_counts == {}
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_recovery_uses_current_states_and_enforces_conversation_and_owner_scope():
    async with SessionFactory() as session:
        try:
            owner = User(username=f"recover-{uuid4().hex}", password_setup_required=False)
            other = User(username=f"other-{uuid4().hex}", password_setup_required=False)
            session.add_all([owner, other])
            await session.flush()
            conversation = AgentConversation(user_id=owner.id)
            unrelated = AgentConversation(user_id=owner.id)
            session.add_all([conversation, unrelated])
            await session.flush()
            cards = []
            for state in ["pending", "succeeded", "cancelled", "rejected", "failed", "expired"]:
                cards.append(
                    Confirmation(
                        user_id=owner.id,
                        operation_type="food_create",
                        before=None,
                        after={"food": {"name": state}},
                        reason="验收",
                        impact="确认后添加",
                        status="pending" if state == "expired" else state,
                        expires_at=datetime.now(UTC)
                        + timedelta(hours=-1 if state == "expired" else 1),
                        version=3,
                    )
                )
            outside = Confirmation(
                user_id=owner.id,
                operation_type="food_create",
                after={},
                reason="另一段聊天",
                impact="不能混入",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            foreign = Confirmation(
                user_id=other.id,
                operation_type="food_create",
                after={},
                reason="其他账户",
                impact="不能混入",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            session.add_all([*cards, outside, foreign])
            await session.flush()
            session.add_all(
                [
                    link_run(owner, conversation, [*cards, foreign]),
                    link_run(owner, unrelated, [outside]),
                ]
            )
            await session.flush()
            service = ConversationService(SqlAlchemyConversationRepository(session))
            result = await service.restore_confirmations(
                user_id=owner.id, conversation_id=conversation.id
            )
            assert [c.confirmation_id for c in result.confirmation_cards] == [cards[0].id]
            assert result.confirmation_cards[0].version == 3
            assert [c.confirmation_id for c in result.completed_cards] == [cards[1].id]
            assert result.completed_cards[0].status == "succeeded"
            assert result.completed_cards[0].after == cards[1].after
            assert result.resolved_counts == {
                "succeeded": 1,
                "cancelled": 1,
                "rejected": 1,
                "failed": 1,
                "expired": 1,
            }
            with pytest.raises(AgentConversationNotFoundError):
                await service.restore_confirmations(
                    user_id=other.id, conversation_id=conversation.id
                )
            conversation.deleted_at = datetime.now(UTC)
            await session.flush()
            with pytest.raises(AgentConversationNotFoundError):
                await service.restore_confirmations(
                    user_id=owner.id, conversation_id=conversation.id
                )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_editor_replacements_without_new_runs_restore_only_latest_and_save_once():
    async with SessionFactory() as session:
        try:
            user = User(username=f"recover-meal-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            await session.flush()
            conversation = AgentConversation(user_id=user.id)
            session.add(conversation)
            await session.flush()
            commands = SqlAlchemyConfirmationRepository(session)
            nutrition = NutritionService(SqlAlchemyNutritionRepository(session), commands)
            old = await nutrition.propose_entry(
                user_id=user.id,
                body=NutritionEntryCreateRequest(
                    meal_type="lunch",
                    eaten_at=datetime.now(UTC),
                    items=[
                        NutritionItemInput(
                            name="熟米饭",
                            amount_g=200,
                            basis_amount_g=200,
                            kcal=230,
                            protein_g=5,
                            carbs_g=50,
                            fat_g=1,
                            source="model_estimated",
                            confidence="low",
                        )
                    ],
                ),
            )
            session.add(link_run(user, conversation, [old]))
            await session.flush()
            middle = await nutrition.revise_pending_entry(
                user.id,
                old.id,
                NutritionPendingEntryRevisionRequest(
                    expected_version=old.version,
                    changes=[NutritionPortionChange(item_index=0, amount_g=100)],
                ),
            )
            latest = await nutrition.revise_pending_entry(
                user.id,
                middle.id,
                NutritionPendingEntryRevisionRequest(
                    expected_version=middle.version,
                    changes=[NutritionPortionChange(item_index=0, amount_g=50)],
                ),
            )
            service = ConversationService(SqlAlchemyConversationRepository(session))
            snapshot = await service.restore_confirmations(
                user_id=user.id, conversation_id=conversation.id
            )
            assert [c.confirmation_id for c in snapshot.confirmation_cards] == [latest.id]
            assert snapshot.resolved_counts == {}
            assert float(snapshot.confirmation_cards[0].after["preview"]["totals"]["kcal"]) == 57.5
            context = await service._meal_confirmation_context(user.id, conversation.id)
            assert len(context) == 1 and context[0]["confirmation_id"] == str(latest.id)
            assert context[0]["status"] == "pending" and context[0]["entry_id"] is None
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(NutritionEntry)
                    .where(NutritionEntry.user_id == user.id)
                )
                == 0
            )
            await DatabaseConfirmationService(commands).approve(user.id, latest.id, latest.version)
            recovered = await ConversationService(
                SqlAlchemyConversationRepository(session)
            ).restore_confirmations(user_id=user.id, conversation_id=conversation.id)
            assert recovered.confirmation_cards == []
            assert len(recovered.completed_cards) == 1
            assert recovered.completed_cards[0].confirmation_id == latest.id
            assert recovered.completed_cards[0].status == "succeeded"
            assert recovered.completed_cards[0].version == latest.version
            assert float(recovered.completed_cards[0].after["preview"]["totals"]["kcal"]) == 57.5
            assert recovered.resolved_counts == {"succeeded": 1}
            context = await service._meal_confirmation_context(user.id, conversation.id)
            assert len(context) == 1 and context[0]["status"] == "succeeded"
            assert context[0]["entry_id"] == latest.result["resource_id"]
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(NutritionEntry)
                    .where(NutritionEntry.user_id == user.id)
                )
                == 1
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    [
        "training_plan_activate",
        "calendar_reschedule",
        "training_progression_apply",
        "nutrition_target_activate",
    ],
)
async def test_restored_training_cards_keep_reviewable_database_previews(operation):
    async with SessionFactory() as session:
        try:
            user = User(username=f"recover-preview-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            await session.flush()
            conversation = AgentConversation(user_id=user.id)
            session.add(conversation)
            if operation == "training_plan_activate":
                draft = TrainingPlanDraft(
                    user_id=user.id,
                    name="待确认计划",
                    weekly_frequency=3,
                    days=[{"name": "上肢日"}],
                    status="submitted",
                )
                key, field, expected = "plan_draft_id", "name", "待确认计划"
            elif operation == "calendar_reschedule":
                event = CalendarEvent(
                    user_id=user.id,
                    scheduled_date=datetime.now(UTC).date(),
                    status="planned",
                    title="训练",
                    estimated_minutes=45,
                )
                session.add(event)
                await session.flush()
                draft = CalendarRescheduleDraft(
                    user_id=user.id,
                    missed_event_id=event.id,
                    strategy="compression",
                    before_events=[{"estimated_minutes": 45}],
                    after_events=[{"estimated_minutes": 30}],
                    duration_change_minutes=-15,
                    volume_change_percent=-30,
                    status="submitted",
                )
                key, field, expected = "draft_id", "after_events", [{"estimated_minutes": 30}]
            elif operation == "nutrition_target_activate":
                draft = NutritionTargetDraft(
                    user_id=user.id,
                    effective_from=datetime.now(UTC).date(),
                    kcal_min=1800,
                    kcal_max=2000,
                    protein_min_g=100,
                    protein_max_g=120,
                    carbs_min_g=200,
                    carbs_max_g=250,
                    fat_min_g=50,
                    fat_max_g=70,
                    status="submitted",
                )
                key, field, expected = (
                    "target_id",
                    "values",
                    {
                        "kcal_min": 1800,
                        "kcal_max": 2000,
                        "protein_min_g": 100,
                        "protein_max_g": 120,
                        "carbs_min_g": 200,
                        "carbs_max_g": 250,
                        "fat_min_g": 50,
                        "fat_max_g": 70,
                    },
                )
            else:
                workout = Workout(user_id=user.id, started_at=datetime.now(UTC), status="completed")
                session.add(workout)
                await session.flush()
                draft = ProgressionDraft(
                    user_id=user.id,
                    workout_id=workout.id,
                    suggestions=[{"exercise_name": "深蹲", "weight_kg": 50}],
                    status="submitted",
                )
                key, field, expected = (
                    "draft_id",
                    "suggestions",
                    [{"exercise_name": "深蹲", "weight_kg": 50}],
                )
            session.add(draft)
            await session.flush()
            card = Confirmation(
                user_id=user.id,
                operation_type=operation,
                after={key: str(draft.id), "draft_version": draft.version},
                reason="验收",
                impact="确认后生效",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            session.add(card)
            await session.flush()
            session.add(link_run(user, conversation, [card]))
            await session.flush()
            result = await ConversationService(
                SqlAlchemyConversationRepository(session)
            ).restore_confirmations(user_id=user.id, conversation_id=conversation.id)
            assert result.confirmation_cards[0].draft[field] == expected
            result.model_dump(mode="json")
        finally:
            await session.rollback()
