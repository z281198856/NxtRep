from collections.abc import AsyncIterator
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.api.deps import get_current_user
from nxtrep_backend.api.routes import nutrition as route
from nxtrep_backend.db.session import get_db_session
from nxtrep_backend.main import app
from nxtrep_backend.repositories.water import SqlAlchemyWaterRepository
from nxtrep_backend.schemas.water import WaterEntryCreateRequest


@pytest.fixture
def setup(monkeypatch):
    user = SimpleNamespace(id=uuid4())
    session = MagicMock(spec=AsyncSession)
    repo = SimpleNamespace(
        list_entries=AsyncMock(return_value=[]),
        create=AsyncMock(),
        delete=AsyncMock(return_value=False),
    )

    async def db() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db_session] = db
    monkeypatch.setattr(route, "SqlAlchemyWaterRepository", lambda _: repo)
    monkeypatch.setattr(route, "begin_idempotent", AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(route, "replay_response", lambda *args: None)
    monkeypatch.setattr(route, "complete_idempotent", AsyncMock())
    try:
        with TestClient(app) as client:
            yield client, user, repo
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db_session, None)


@pytest.mark.parametrize("amount", [0, -1, 5001, 1.5, True])
def test_water_rejects_invalid_amount(amount):
    with pytest.raises(ValidationError):
        WaterEntryCreateRequest(amount_ml=amount, consumed_at="2026-10-23T10:00:00+08:00")


def test_water_requires_timezone():
    with pytest.raises(ValidationError):
        WaterEntryCreateRequest(amount_ml=250, consumed_at="2026-10-23T10:00:00")


def test_create_list_delete_and_missing_record(setup):
    client, user, repo = setup
    entry = SimpleNamespace(
        id=uuid4(), amount_ml=250, consumed_at=datetime.fromisoformat("2026-10-23T10:00:00+08:00")
    )
    repo.create.return_value = entry
    response = client.post(
        "/api/v1/nutrition/water",
        headers={"Idempotency-Key": str(uuid4())},
        json={"amount_ml": 250, "consumed_at": entry.consumed_at.isoformat()},
    )
    assert response.status_code == 201
    assert response.json()["amount_ml"] == 250
    repo.create.assert_awaited_once_with(user.id, 250, entry.consumed_at)
    repo.list_entries.return_value = [entry]
    response = client.get("/api/v1/nutrition/water?date=2026-10-23")
    assert response.status_code == 200
    assert response.json()[0]["id"] == str(entry.id)
    repo.list_entries.assert_awaited_once_with(user.id, date(2026, 10, 23))
    repo.delete.return_value = True
    assert client.delete(f"/api/v1/nutrition/water/{entry.id}").status_code == 204
    repo.delete.assert_awaited_once_with(user.id, entry.id)
    repo.delete.return_value = False
    assert client.delete(f"/api/v1/nutrition/water/{entry.id}").status_code == 404


def test_water_total_does_not_change_meal_nutrients_or_completeness(setup, monkeypatch):
    client, _, repo = setup
    totals = {"kcal": 500, "protein_g": 30, "carbs_g": 60, "fat_g": 15}
    service = SimpleNamespace(
        daily_summary=AsyncMock(
            return_value={
                "date": "2026-10-23",
                "consumed": totals,
                "target": None,
                "remaining": None,
                "record_completeness": "0.33",
            }
        )
    )
    monkeypatch.setattr(route, "_service", lambda _: service)
    repo.list_entries.return_value = [
        SimpleNamespace(amount_ml=250),
        SimpleNamespace(amount_ml=500),
    ]
    response = client.get("/api/v1/nutrition/daily-summary?date=2026-10-23")
    assert response.status_code == 200
    body = response.json()
    assert body["water_ml"] == 750
    assert body["record_completeness"] == "0.33"
    assert float(body["consumed"]["kcal"]) == 500


@pytest.mark.asyncio
async def test_repository_scopes_day_and_owner_and_excludes_deleted_records():
    session = MagicMock(spec=AsyncSession)
    session.scalars = AsyncMock(return_value=[])
    repo = SqlAlchemyWaterRepository(session)
    owner = uuid4()
    await repo.list_entries(owner, date(2026, 10, 23))
    statement = session.scalars.call_args.args[0]
    sql = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert str(owner) in sql
    assert "deleted_at IS NULL" in sql
    assert "2026-10-23 00:00:00+08:00" in sql
    assert "2026-10-24 00:00:00+08:00" in sql
    session.scalar = AsyncMock(return_value=None)
    entry_id = uuid4()
    assert await repo.delete(owner, entry_id) is False
    sql = str(
        session.scalar.call_args.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert str(owner) in sql and str(entry_id) in sql
    assert "FOR UPDATE" in sql
