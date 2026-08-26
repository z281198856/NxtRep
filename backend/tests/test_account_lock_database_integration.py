import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from nxtrep_backend.core.security import hash_password
from nxtrep_backend.db.models import Credential, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.main import app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests",
)


@pytest.mark.asyncio
async def test_failed_logins_persist_and_lock_account_through_http_route() -> None:
    username = f"lock-integration-{uuid4().hex}"
    user_id = None
    async with SessionFactory.begin() as session:
        user = User(
            username=username,
            password_setup_required=False,
            credential=Credential(password_hash=hash_password("correct-password")),
        )
        session.add(user)
        await session.flush()
        user_id = user.id

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            statuses = []
            for _ in range(5):
                response = await client.post(
                    "/api/v1/auth/login",
                    json={"username": username, "password": "wrong-password"},
                )
                statuses.append(response.status_code)

        assert statuses == [401, 401, 401, 401, 423]
        async with SessionFactory() as session:
            stored = await session.scalar(select(Credential).where(Credential.user_id == user_id))
            assert stored is not None
            assert stored.failed_login_attempts == 5
            assert stored.locked_until is not None
    finally:
        async with SessionFactory.begin() as session:
            await session.execute(delete(User).where(User.id == user_id))
