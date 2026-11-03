import os
from datetime import date, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from nxtrep_backend.agents.tools.confirmation import build_confirmation_cancel_tools
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.db.models import CalendarEvent, CalendarRescheduleDraft, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.training import SqlAlchemyTrainingRepository
from nxtrep_backend.schemas.training import RescheduleDraftCreateRequest
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationNotFoundError,
    DatabaseConfirmationService,
)
from nxtrep_backend.services.training import (
    TrainingConflictError,
    TrainingNotFoundError,
    TrainingService,
    TrainingValidationError,
)

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


async def pending_shift(session):
    user = User(username=f"multiturn-{uuid4().hex}", password_setup_required=False)
    session.add(user)
    await session.flush()
    source = date.today() + timedelta(days=30)
    event = CalendarEvent(
        user_id=user.id,
        scheduled_date=source,
        status="planned",
        title="测试训练",
        estimated_minutes=45,
    )
    session.add(event)
    await session.flush()
    repository = SqlAlchemyConfirmationRepository(session)
    training = TrainingService(SqlAlchemyTrainingRepository(session), repository)
    draft = await training.create_reschedule_draft(
        user.id,
        RescheduleDraftCreateRequest(
            missed_event_id=event.id,
            strategy="shift",
            target_date=source + timedelta(days=1),
        ),
    )
    card = await training.submit_reschedule(user.id, draft.id, draft.version)
    return user, event, training, repository, card


@pytest.mark.asyncio
async def test_revised_schedule_only_new_card_can_apply_and_original_event_is_preserved():
    async with SessionFactory() as session:
        try:
            user, event, training, repository, old = await pending_shift(session)
            old_version = old.version
            source = event.scheduled_date
            target = source + timedelta(days=2)
            draft, new = await training.revise_pending_reschedule(
                user.id,
                old.id,
                old_version,
                RescheduleDraftCreateRequest(
                    missed_event_id=event.id,
                    strategy="shift",
                    target_date=target,
                ),
            )
            assert event.scheduled_date == source
            assert old.status == "rejected" and new.status == "pending"
            assert new.after["replaces_confirmation_id"] == str(old.id)
            assert draft.after_events[0]["scheduled_date"] == target.isoformat()
            with pytest.raises(DatabaseConfirmationConflictError):
                await DatabaseConfirmationService(repository).approve(user.id, old.id, old_version)
            await DatabaseConfirmationService(repository).approve(user.id, new.id, new.version)
            assert event.scheduled_date == target
            with pytest.raises(DatabaseConfirmationConflictError):
                await DatabaseConfirmationService(repository).approve(user.id, new.id, 1)
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(CalendarEvent)
                    .where(CalendarEvent.user_id == user.id)
                )
                == 1
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_invalid_replacement_keeps_old_pending_and_rolls_back_candidate_draft():
    async with SessionFactory() as session:
        try:
            user, event, training, _, old = await pending_shift(session)
            blocked = event.scheduled_date + timedelta(days=3)
            session.add(
                CalendarEvent(
                    user_id=user.id,
                    scheduled_date=blocked,
                    status="planned",
                    title="已占用",
                    estimated_minutes=30,
                )
            )
            await session.flush()
            with pytest.raises(TrainingValidationError):
                await training.revise_pending_reschedule(
                    user.id,
                    old.id,
                    old.version,
                    RescheduleDraftCreateRequest(
                        missed_event_id=event.id, strategy="shift", target_date=blocked
                    ),
                )
            await session.refresh(old)
            assert old.status == "pending" and old.version == 1
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(CalendarRescheduleDraft)
                    .where(CalendarRescheduleDraft.user_id == user.id)
                )
                == 1
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_chat_cancel_is_user_scoped_repeat_safe_and_never_applies_draft():
    async with SessionFactory() as session:
        try:
            user, event, _, repository, card = await pending_shift(session)
            source = event.scheduled_date
            context = MagicMock(spec=AgentToolContext)
            context.user_id = user.id
            context.confirmation_service = DatabaseConfirmationService(repository)
            tool = build_confirmation_cancel_tools(context)[0]
            first = await tool.ainvoke({"confirmation_id": str(card.id), "expected_version": 1})
            again = await tool.ainvoke({"confirmation_id": str(card.id), "expected_version": 1})
            assert first == again and first["status"] == "cancelled"
            assert event.scheduled_date == source
            with pytest.raises(DatabaseConfirmationConflictError):
                await context.confirmation_service.approve(user.id, card.id, 1)
            context.user_id = uuid4()
            with pytest.raises(DatabaseConfirmationNotFoundError):
                await tool.ainvoke({"confirmation_id": str(card.id), "expected_version": 1})
            assert card.status == "cancelled"
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["stale_version", "executed", "other_user", "other_event"])
async def test_replacement_rejects_stale_foreign_or_mismatched_requests(case):
    async with SessionFactory() as session:
        try:
            user, event, training, _, old = await pending_shift(session)
            if case == "executed":
                old.status = "succeeded"
            initial_status = old.status
            initial_date = event.scheduled_date
            with pytest.raises(
                TrainingNotFoundError if case == "other_user" else TrainingConflictError
            ):
                await training.revise_pending_reschedule(
                    uuid4() if case == "other_user" else user.id,
                    old.id,
                    99 if case == "stale_version" else old.version,
                    RescheduleDraftCreateRequest(
                        missed_event_id=uuid4() if case == "other_event" else event.id,
                        strategy="shift",
                        target_date=initial_date + timedelta(days=2),
                    ),
                )
            await session.refresh(old)
            assert old.status == initial_status
            assert event.scheduled_date == initial_date
        finally:
            await session.rollback()
