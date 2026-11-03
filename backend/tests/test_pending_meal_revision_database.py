import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from nxtrep_backend.db.models import NutritionEntry, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.nutrition import (
    NutritionEntryCreateRequest,
    NutritionItemInput,
    NutritionPendingEntryRevisionRequest,
    NutritionPortionChange,
)
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationService,
)
from nxtrep_backend.services.nutrition import (
    NutritionConflictError,
    NutritionNotFoundError,
    NutritionService,
)

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


async def create_meal(session):
    user = User(username=f"portion-revision-{uuid4().hex}", password_setup_required=False)
    session.add(user)
    await session.flush()
    repository = SqlAlchemyConfirmationRepository(session)
    service = NutritionService(SqlAlchemyNutritionRepository(session), repository)
    card = await service.propose_entry(
        user_id=user.id,
        body=NutritionEntryCreateRequest(
            meal_type="lunch",
            eaten_at=datetime.now(UTC),
            items=[
                NutritionItemInput(
                    name="测试两份食物",
                    amount_g=200,
                    basis_amount_g=200,
                    kcal=400,
                    protein_g=20,
                    carbs_g=40,
                    fat_g=10,
                    source="model_estimated",
                    confidence="low",
                )
            ],
        ),
    )
    return user, service, repository, card


@pytest.mark.asyncio
async def test_revision_recalculates_invalidates_old_card_and_only_new_approval_saves():
    async with SessionFactory() as session:
        try:
            user, service, repository, old = await create_meal(session)
            old_version = old.version
            body = NutritionPendingEntryRevisionRequest(
                expected_version=old_version,
                changes=[
                    NutritionPortionChange(item_index=0, amount_g=100),
                ],
            )
            new = await service.revise_pending_entry(user.id, old.id, body)
            assert Decimal(new.after["preview"]["totals"]["kcal"]) == Decimal("200")
            assert new.after["entry"]["items"][0]["basis_amount_g"] == "200"
            assert new.after["replaces_confirmation_id"] == str(old.id)
            assert old.status == "rejected"
            assert not (
                await session.scalars(
                    select(NutritionEntry).where(NutritionEntry.user_id == user.id)
                )
            ).all()
            with pytest.raises(DatabaseConfirmationConflictError):
                await DatabaseConfirmationService(repository).approve(user.id, old.id, old_version)
            with pytest.raises(NutritionConflictError):
                await service.revise_pending_entry(user.id, old.id, body)
            await DatabaseConfirmationService(repository).approve(user.id, new.id, new.version)
            entries = (
                await session.scalars(
                    select(NutritionEntry).where(NutritionEntry.user_id == user.id)
                )
            ).all()
            assert len(entries) == 1
            assert Decimal(entries[0].totals["kcal"]) == Decimal("200")
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["succeeded", "rejected", "expired", "other_user", "bad_index"])
async def test_revision_rejects_stale_or_foreign_cards_without_changing_them(state):
    async with SessionFactory() as session:
        try:
            user, service, _, old = await create_meal(session)
            if state in {"succeeded", "rejected"}:
                old.status = state
            if state == "expired":
                old.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            body = NutritionPendingEntryRevisionRequest(
                expected_version=old.version,
                changes=[
                    NutritionPortionChange(
                        item_index=9 if state == "bad_index" else 0, amount_g=100
                    ),
                ],
            )
            with pytest.raises(
                NutritionNotFoundError if state == "other_user" else NutritionConflictError
            ):
                await service.revise_pending_entry(
                    uuid4() if state == "other_user" else user.id, old.id, body
                )
            if state in {"other_user", "bad_index"}:
                assert old.status == "pending"
                assert old.version == 1
        finally:
            await session.rollback()
