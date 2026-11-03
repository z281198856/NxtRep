"""Recovery uses exact task/call/owned-card links, never proximity or matching prose."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from nxtrep_backend.db.models import AgentConversation, AgentRun, Confirmation, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.schemas.agent_task import AgentTask
from nxtrep_backend.services.agent_task_recovery import recover_task_confirmation
from nxtrep_backend.services.agent_task_state import TaskStateManager

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


async def seed(session):
    user = User(username=f"task-recovery-{uuid4().hex}", password_setup_required=False)
    session.add(user)
    await session.flush()
    conversation = AgentConversation(user_id=user.id)
    session.add(conversation)
    await session.flush()
    task = AgentTask(
        task_type="workout_record_draft",
        parameters={
            "exercise_name": "卧推",
            "weight_kg": "60",
            "sets": 4,
            "reps": 8,
        },
    )
    return user, conversation, task


async def add_evidence(session, user, conversation, task, **changes):
    identifier, call_id = uuid4(), str(uuid4())
    confirmation = Confirmation(
        id=identifier,
        user_id=changes.get("card_user_id", user.id),
        operation_type=changes.get("operation_type", "workout_record_create"),
        status=changes.get("card_status", "pending"),
        after={"request": task.parameters},
        reason="恢复验收",
        impact="确认后记录卧推",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    if confirmation.status == "succeeded":
        confirmation.result = {
            "success": True,
            "workout_id": str(uuid4()),
            "workout_exercise_id": str(uuid4()),
        }
    record = {
        "tool_name": "propose_workout_record",
        "tool_call_id": call_id,
        "task_id": changes.get("record_task_id", str(task.task_id)),
        "status": "confirmation_required",
    }
    operation = {
        "tool_name": "propose_workout_record",
        "status": "confirmation_required",
        "tool_call_id": changes.get("operation_call_id", call_id),
        "confirmation_id": str(identifier),
    }
    run = AgentRun(
        user_id=changes.get("run_user_id", user.id),
        conversation_id=changes.get("run_conversation_id", conversation.id),
        status="failed",
        request_payload={"message": "恢复测试"},
        started_at=datetime.now(UTC),
        checkpoint={
            "tool_runs": [record],
            "operations": [operation],
            "confirmation_refs": [] if changes.get("omit_returned_ref") else [str(identifier)],
        },
    )
    session.add_all([confirmation, run])
    await session.flush()
    return confirmation, run


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "succeeded"])
async def test_exact_task_evidence_restores_authoritative_status_and_business_result(status):
    async with SessionFactory() as session:
        try:
            user, conversation, task = await seed(session)
            card, _ = await add_evidence(session, user, conversation, task, card_status=status)
            recovered = await recover_task_confirmation(session, user.id, conversation.id, task)
            assert recovered.entities["confirmation_id"] == str(card.id)
            assert recovered.status == (
                "awaiting_confirmation" if status == "pending" else "completed"
            )
            if status == "succeeded":
                assert recovered.entities["workout_id"] == card.result["workout_id"]
            else:
                assert "workout_id" not in recovered.entities
                prepared = TaskStateManager.prepare_turn(
                    {"active_task": recovered.model_dump(mode="json")}, "算了"
                )
                assert prepared.requires_business_action and not prepared.handled
            assert not task.entities
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"record_task_id": str(uuid4())},
        {"operation_call_id": str(uuid4())},
        {"omit_returned_ref": True},
        {"operation_type": "nutrition_entry_create"},
        {"card_status": "cancelled"},
    ],
    ids=["wrong_task", "wrong_call", "missing_returned_ref", "wrong_operation", "cancelled_card"],
)
async def test_similar_recent_proposal_without_required_links_is_not_a_recovery(changes):
    async with SessionFactory() as session:
        try:
            user, conversation, task = await seed(session)
            await add_evidence(session, user, conversation, task, **changes)
            assert await recover_task_confirmation(session, user.id, conversation.id, task) is None
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign_field", ["card_user_id", "run_user_id", "run_conversation_id"])
async def test_foreign_user_or_conversation_evidence_never_changes_task(foreign_field):
    async with SessionFactory() as session:
        try:
            user, conversation, task = await seed(session)
            other, other_conversation, _ = await seed(session)
            foreign = other_conversation.id if foreign_field == "run_conversation_id" else other.id
            await add_evidence(session, user, conversation, task, **{foreign_field: foreign})
            assert await recover_task_confirmation(session, user.id, conversation.id, task) is None
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_multiple_owned_results_require_selection_instead_of_latest_guess():
    async with SessionFactory() as session:
        try:
            user, conversation, task = await seed(session)
            first, _ = await add_evidence(session, user, conversation, task)
            second, _ = await add_evidence(session, user, conversation, task)
            recovered = await recover_task_confirmation(session, user.id, conversation.id, task)
            assert recovered.status == "collecting" and recovered.missing_fields == ["selection"]
            assert "confirmation_id" not in recovered.entities
            assert {candidate.id for candidate in recovered.candidates} == {first.id, second.id}
            assert {candidate.kind for candidate in recovered.candidates} == {"confirmation"}
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_cancel_tool_cannot_be_used_as_a_proposal_recovery_link():
    async with SessionFactory() as session:
        try:
            user, conversation, task = await seed(session)
            _, run = await add_evidence(session, user, conversation, task)
            run.checkpoint = {
                **run.checkpoint,
                "tool_runs": [
                    {**run.checkpoint["tool_runs"][0], "tool_name": "cancel_confirmation"}
                ],
            }
            await session.flush()
            assert await recover_task_confirmation(session, user.id, conversation.id, task) is None
            assert (
                len(
                    list(
                        await session.scalars(
                            select(Confirmation).where(Confirmation.user_id == user.id)
                        )
                    )
                )
                == 1
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_remove_one_food_task_can_recover_its_nutrition_update_confirmation():
    async with SessionFactory() as session:
        try:
            user, conversation, task = await seed(session)
            task.task_type = "nutrition_entry_delete_draft"
            card, _ = await add_evidence(
                session, user, conversation, task, operation_type="nutrition_entry_update"
            )
            recovered = await recover_task_confirmation(session, user.id, conversation.id, task)
            assert recovered.status == "awaiting_confirmation"
            assert recovered.entities["confirmation_id"] == str(card.id)
        finally:
            await session.rollback()
