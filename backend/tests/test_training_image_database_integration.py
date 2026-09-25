import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from nxtrep_backend.api.deps import get_current_user, get_db_session
from nxtrep_backend.api.routes import training as training_routes
from nxtrep_backend.db.models import ImageAsset, User
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.main import app

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.getenv("RUN_DATABASE_TESTS") != "1", reason="Requires PostgreSQL"),
]


async def test_image_import_uses_transcribed_exercises_and_rejects_unreadable_text(monkeypatch):
    async with SessionFactory() as session:
        transaction = await session.begin()
        previous_overrides = app.dependency_overrides.copy()
        try:
            user = User(username=f"image-import-{uuid4().hex}", password_setup_required=False)
            session.add(user)
            await session.flush()
            asset = ImageAsset(
                user_id=user.id,
                purpose="training_plan",
                object_key=f"images/{user.id}/{uuid4()}.jpg",
                content_type="image/jpeg",
                content_length=1024,
                status="ready",
                upload_expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
            session.add(asset)
            await session.flush()
            app.dependency_overrides[get_current_user] = lambda: user
            app.dependency_overrides[get_db_session] = lambda: session

            class Reader:
                text = "周一：哑铃地板卧推 3×8-12\n周四：哑铃高脚杯深蹲 4×8"
                calls = []

                async def read(self, *, user_id, asset_id):
                    self.calls.append((user_id, asset_id))
                    return self.text

            reader = Reader()
            monkeypatch.setattr(training_routes, "_image_reader", lambda _: reader)
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/training/plan-drafts:parse-image",
                    headers={"Idempotency-Key": str(uuid4())},
                    json={"image_asset_id": str(asset.id)},
                )
                assert response.status_code == 201, response.text
                draft = response.json()
                assert draft["recognized_text"] == reader.text
                exercise_names = [
                    item["exercise_name"] for day in draft["days"] for item in day["exercises"]
                ]
                assert exercise_names == ["哑铃地板卧推", "哑铃高脚杯深蹲"]
                assert reader.calls == [(user.id, asset.id)]

                reader.text = "周一：不存在的动作 3×8"
                bad = await client.post(
                    "/api/v1/training/plan-drafts:parse-image",
                    headers={"Idempotency-Key": str(uuid4())},
                    json={"image_asset_id": str(asset.id)},
                )
                assert bad.status_code == 422, bad.text
                assert bad.json()["error"]["details"]["recognized_text"] == reader.text

                asset.status = "pending_upload"
                await session.flush()
                not_ready = await client.post(
                    "/api/v1/training/plan-drafts:parse-image",
                    headers={"Idempotency-Key": str(uuid4())},
                    json={"image_asset_id": str(asset.id)},
                )
                assert not_ready.status_code == 409
                assert len(reader.calls) == 2
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous_overrides)
            await transaction.rollback()
