import os
from copy import deepcopy
from datetime import date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_saved_meal_changes_database import seed

from nxtrep_backend.core.timezones import CHINA_TIMEZONE
from nxtrep_backend.db.models import NutritionEntry, NutritionEntryRevision
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.schemas.nutrition import NutritionDateChangeRequest
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationService,
)

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Local PostgreSQL")


async def prepare(session, source=date(2026, 10, 11), target=date(2026, 10, 10)):
    user, service, repo, _, first = await seed(session)
    first.eaten_at = datetime.combine(source, datetime.min.time().replace(hour=12), CHINA_TIMEZONE)
    second = NutritionEntry(
        user_id=user.id,
        meal_type="dinner",
        eaten_at=datetime.combine(source, datetime.min.time().replace(hour=18), CHINA_TIMEZONE),
        items=deepcopy(first.items),
        totals=deepcopy(first.totals),
        notes="晚餐原备注",
    )
    existing = NutritionEntry(
        user_id=user.id,
        meal_type="breakfast",
        eaten_at=datetime.combine(target, datetime.min.time().replace(hour=8), CHINA_TIMEZONE),
        items=[],
        totals={"kcal": "50", "protein_g": "0", "carbs_g": "0", "fat_g": "0"},
    )
    session.add_all([second, existing])
    await session.flush()
    body = NutritionDateChangeRequest(
        source_date=source,
        target_date=target,
        entries=[{"entry_id": e.id, "expected_version": e.version} for e in [first, second]],
        reason="日期记错，改成前一天",
    )
    return user, service, repo, [first, second], existing, body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source,target",
    [(date(2026, 10, 11), date(2026, 10, 10)), (date(2026, 10, 1), date(2026, 9, 30))],
)
async def test_move_preserves_snapshots_ids_target_meals_and_updates_stats_once(source, target):
    async with SessionFactory() as session:
        try:
            user, service, repo, entries, existing, body = await prepare(session, source, target)
            snapshots = [deepcopy(service._entry_snapshot(e)) for e in entries]
            existing_before = deepcopy(service._entry_snapshot(existing))
            card = await service.propose_saved_date_change(user.id, body)
            assert [service._entry_snapshot(e) for e in entries] == snapshots
            assert len(card.after["preview"]["entries"]) == 2
            commands = DatabaseConfirmationService(repo)
            await commands.approve(user.id, card.id, card.version)
            for entry, original in zip(entries, snapshots, strict=True):
                assert entry.eaten_at.astimezone(CHINA_TIMEZONE).date() == target
                now = service._entry_snapshot(entry)
                for key, value in original.items():
                    if key not in {"eaten_at", "version"}:
                        assert now[key] == value
                assert entry.version == 2
            assert service._entry_snapshot(existing) == existing_before
            assert (await service.daily_summary(user.id, source))["consumed"]["kcal"] == 0
            assert (await service.daily_summary(user.id, target))["consumed"]["kcal"] == 870
            with pytest.raises(DatabaseConfirmationConflictError):
                await commands.approve(user.id, card.id, 1)
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(NutritionEntry)
                    .where(NutritionEntry.user_id == user.id)
                )
                == 3
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(NutritionEntryRevision)
                    .where(NutritionEntryRevision.entry_id.in_([e.id for e in entries]))
                )
                == 2
            )
        finally:
            await session.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["stale", "deleted", "foreign", "wrong_day"])
async def test_batch_preflight_failure_never_moves_any_meal(failure):
    async with SessionFactory() as session:
        try:
            user, service, repo, entries, _, body = await prepare(session)
            card = await service.propose_saved_date_change(user.id, body)
            # Make the row which will be locked last invalid.
            broken = sorted(entries, key=lambda e: str(e.id))[-1]
            if failure == "stale":
                broken.version += 1
            elif failure == "deleted":
                broken.deleted_at = datetime.now(CHINA_TIMEZONE)
            elif failure == "foreign":
                card.after = {
                    **card.after,
                    "request": {
                        **body.model_dump(mode="json"),
                        "entries": [{"entry_id": str(uuid4()), "expected_version": 1}],
                    },
                }
            else:
                broken.eaten_at = broken.eaten_at.replace(day=9)
            await session.flush()
            for entry in entries:
                await session.refresh(entry)
            before = [deepcopy(service._entry_snapshot(e)) for e in entries]
            with pytest.raises(DatabaseConfirmationConflictError):
                await DatabaseConfirmationService(repo).approve(user.id, card.id, card.version)
            assert [service._entry_snapshot(e) for e in entries] == before
            assert card.status == "pending"
        finally:
            await session.rollback()


@pytest.mark.asyncio
async def test_revised_date_card_invalidates_old_card_and_cancel_keeps_data():
    async with SessionFactory() as session:
        try:
            user, service, repo, entries, _, body = await prepare(session)
            before = [deepcopy(service._entry_snapshot(e)) for e in entries]
            old = await service.propose_saved_date_change(user.id, body)
            revised = await service.propose_saved_date_change(
                user.id,
                body.model_copy(update={"target_date": date(2026, 10, 9)}),
                replaces_id=old.id,
                replaces_version=old.version,
            )
            assert old.status == "cancelled" and revised.after["replaces_confirmation_id"] == str(
                old.id
            )
            commands = DatabaseConfirmationService(repo)
            with pytest.raises(DatabaseConfirmationConflictError):
                await commands.approve(user.id, old.id, 1)
            await commands.cancel(user.id, revised.id, revised.version)
            assert [service._entry_snapshot(e) for e in entries] == before
        finally:
            await session.rollback()
