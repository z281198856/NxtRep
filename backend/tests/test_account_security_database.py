"""Real database/API checks using disposable accounts, no model calls."""

import asyncio
import os
import secrets
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from nxtrep_backend.core.security import hash_password
from nxtrep_backend.core.tokens import create_access_token
from nxtrep_backend.db.models import Credential, Profile, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.main import app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1", reason="Requires local PostgreSQL"
)


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver/api/v1")


async def seed_account():
    user_id = uuid4()
    username, password = f"security-{uuid4().hex[:12]}", secrets.token_urlsafe(24)
    async with SessionFactory.begin() as session:
        session.add(
            User(
                id=user_id,
                username=username,
                password_setup_required=False,
                credential=Credential(password_hash=hash_password(password)),
                profile=Profile(experience_level="beginner", weekly_training_days=3),
            )
        )
    return user_id, username, password


async def login(client, username, password, name):
    response = await client.post(
        "/auth/login", json={"username": username, "password": password, "device_name": name}
    )
    assert response.status_code == 200
    return response.json()


def header(pair):
    return {"Authorization": "Bearer " + pair["access_token"]}


@pytest.mark.asyncio
async def test_devices_rotation_revocation_password_change_and_account_isolation(client):
    user_id, username, password = await seed_account()
    foreign_id, foreign_name, foreign_password = await seed_account()
    try:
        async with client:
            first = await login(client, username, password, "Current Android")
            other = await login(client, username, password, "Other device")
            foreign = await login(client, foreign_name, foreign_password, "Foreign account")
            sessions = await client.get("/auth/sessions", headers=header(other))
            assert sessions.status_code == 200
            other_id = next(row["id"] for row in sessions.json()["sessions"] if row["is_current"])
            response = await client.post(
                "/auth/refresh", json={"refresh_token": other["refresh_token"]}
            )
            assert response.status_code == 200
            rotated = response.json()
            assert rotated["refresh_token"] != other["refresh_token"]
            sessions = (await client.get("/auth/sessions", headers=header(rotated))).json()[
                "sessions"
            ]
            assert len(sessions) == 2
            assert next(row["id"] for row in sessions if row["is_current"]) == other_id
            assert (await client.get("/me", headers=header(other))).status_code == 200
            assert (
                await client.post("/auth/refresh", json={"refresh_token": other["refresh_token"]})
            ).status_code == 401

            foreign_sessions = (await client.get("/auth/sessions", headers=header(foreign))).json()[
                "sessions"
            ]
            result = await client.delete(
                f"/auth/sessions/{foreign_sessions[0]['id']}", headers=header(first)
            )
            assert result.status_code == 404
            assert (await client.get("/me", headers=header(foreign))).status_code == 200

            assert (
                await client.delete(f"/auth/sessions/{other_id}", headers=header(first))
            ).status_code == 204
            assert (await client.get("/me", headers=header(rotated))).status_code == 401
            assert (
                await client.post("/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
            ).status_code == 401
            assert (await client.get("/me", headers=header(first))).status_code == 200

            again = await login(client, username, password, "Other device again")
            assert (
                await client.post("/auth/sessions/revoke-others", headers=header(first))
            ).status_code == 204
            assert (await client.get("/me", headers=header(again))).status_code == 401
            current = (await client.get("/auth/sessions", headers=header(first))).json()["sessions"]
            assert len(current) == 1 and current[0]["is_current"]
            assert (
                await client.get(
                    "/me", headers={"Authorization": "Bearer " + create_access_token(user_id)}
                )
            ).status_code == 401

            new_password = secrets.token_urlsafe(24)
            wrong = await client.post(
                "/auth/password/change",
                headers=header(first),
                json={"current_password": "wrong", "new_password": new_password},
            )
            assert (
                wrong.status_code == 401
                and wrong.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"
            )
            changed = await client.post(
                "/auth/password/change",
                headers=header(first),
                json={
                    "current_password": password,
                    "new_password": new_password,
                    "device_name": "Current Android",
                },
            )
            assert changed.status_code == 200
            assert (await client.get("/me", headers=header(first))).status_code == 401
            assert (
                await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
            ).status_code == 401
            assert (await client.get("/me", headers=header(changed.json()))).status_code == 200
            assert (
                await client.post("/auth/login", json={"username": username, "password": password})
            ).status_code == 401
            await login(client, username, new_password, "New password verification")
    finally:
        async with SessionFactory.begin() as session:
            await session.execute(delete(User).where(User.id.in_([user_id, foreign_id])))


@pytest.mark.asyncio
async def test_refresh_racing_bulk_revoke_cannot_revive_another_login(client):
    user_id, username, password = await seed_account()
    try:
        async with client:
            first = await login(client, username, password, "Current")
            other = await login(client, username, password, "Other")
            refreshed, revoked = await asyncio.gather(
                client.post("/auth/refresh", json={"refresh_token": other["refresh_token"]}),
                client.post("/auth/sessions/revoke-others", headers=header(first)),
            )
            assert revoked.status_code == 204
            assert refreshed.status_code in {200, 401}
            if refreshed.status_code == 200:
                assert (
                    await client.get("/me", headers=header(refreshed.json()))
                ).status_code == 401
            remaining = (await client.get("/auth/sessions", headers=header(first))).json()[
                "sessions"
            ]
            assert len(remaining) == 1 and remaining[0]["is_current"]
    finally:
        async with SessionFactory.begin() as session:
            await session.execute(delete(User).where(User.id == user_id))


@pytest.mark.asyncio
async def test_password_change_wrong_attempts_are_persisted_and_limited(client):
    user_id, username, password = await seed_account()
    try:
        async with client:
            current = await login(client, username, password, "Current")
            statuses = []
            for _ in range(5):
                result = await client.post(
                    "/auth/password/change",
                    headers=header(current),
                    json={"current_password": "wrong", "new_password": "another-long-password"},
                )
                statuses.append(result.status_code)
            assert statuses == [401, 401, 401, 401, 423]
        async with SessionFactory() as session:
            credential = await session.scalar(
                select(Credential).where(Credential.user_id == user_id)
            )
            assert credential.failed_login_attempts == 5 and credential.locked_until is not None
    finally:
        async with SessionFactory.begin() as session:
            await session.execute(delete(User).where(User.id == user_id))
