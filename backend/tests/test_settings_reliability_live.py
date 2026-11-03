"""Opt-in local API/model acceptance; disposable account and synthetic image only."""

import asyncio
import io
import json
import os
from datetime import UTC, datetime
from time import monotonic
from uuid import UUID, uuid4

import alibabacloud_oss_v2 as oss
import httpx
import pytest
from PIL import Image, ImageDraw
from sqlalchemy import func, select
from test_agent_live_acceptance import ROOT, live_account  # noqa: F401

from nxtrep_backend.api.routes.media import get_image_storage_provider
from nxtrep_backend.db.models import BodyMeasurement, ImageAsset, NutritionEntry
from nxtrep_backend.db.session import SessionFactory

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1" or os.getenv("RUN_SETTINGS_RELIABILITY_LIVE") != "1",
    reason="Opt-in disposable settings/AI/synthetic image acceptance",
)
EVIDENCE = ROOT / ".local/settings-reliability-live.json"


def record(event):
    previous = json.loads(EVIDENCE.read_text(encoding="utf-8")) if EVIDENCE.exists() else []
    EVIDENCE.write_text(
        json.dumps([*previous, event], ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def counts(user_id):
    async with SessionFactory() as session:
        return [
            await session.scalar(
                select(func.count()).select_from(model).where(model.user_id == user_id)
            )
            for model in (BodyMeasurement, NutritionEntry)
        ]


@pytest.mark.asyncio(loop_scope="session")
async def test_settings_persist_without_changing_measurements_and_ai_replays_once(live_account):  # noqa: F811
    client, user_id, *_ = live_account
    before_counts = await counts(user_id)
    profile = (await client.get("/profile")).json()
    original = (await client.get("/settings")).json()
    changed = await client.patch(
        "/settings",
        json={
            "unit_system": "imperial",
            "privacy_mode": "summary",
            "expected_version": original["version"],
        },
    )
    assert changed.status_code == 200
    current = (await client.get("/settings")).json()
    assert current["unit_system"] == "imperial" and current["privacy_mode"] == "summary"
    after_profile = (await client.get("/profile")).json()
    assert after_profile["height_cm"] == profile["height_cm"]
    assert after_profile["weight_kg"] == profile["weight_kg"]
    stale = await client.patch(
        "/settings", json={"unit_system": "metric", "expected_version": original["version"]}
    )
    assert stale.status_code == 409
    null = await client.patch(
        "/settings", json={"unit_system": None, "expected_version": current["version"]}
    )
    assert null.status_code == 422
    record(
        {
            "event": "settings",
            "persisted": True,
            "stale_conflict": True,
            "null_rejected": True,
            "canonical_measurements_unchanged": True,
        }
    )

    conversation = await client.post("/agent/conversations", json={})
    assert conversation.status_code in {200, 201}
    body = {
        "conversation_id": conversation.json()["id"],
        "client_turn_id": str(uuid4()),
        "message": "我问的是本 App 训练日志中的训练容量：怎么算？已记录的热身组是否计入？"
        "不用查询或修改我的个人记录，请用两三句话解释。",
    }
    started = monotonic()
    response = await client.post("/agent/chat", json=body)
    elapsed = round(monotonic() - started, 2)
    payload = response.json()
    record(
        {
            "event": "ai_reply",
            "http_status": response.status_code,
            "duration_seconds": elapsed,
            "status": payload.get("status"),
            "message": payload.get("message"),
            "error": payload.get("error"),
        }
    )
    assert response.status_code == 200
    assert payload["status"] == "completed" and len(payload["message"].strip()) > 10
    assert not payload["confirmation_cards"]
    replay = await client.post("/agent/chat", json=body)
    assert replay.status_code == 200
    assert replay.json()["run_id"] == payload["run_id"]
    assert replay.json()["message"] == payload["message"]
    assert await counts(user_id) == before_counts
    record({"event": "ai_replay", "same_run": True, "no_measurement_or_meal_writes": True})


@pytest.mark.asyncio(loop_scope="session")
async def test_synthetic_photo_upload_recognition_and_reuse(live_account):  # noqa: F811
    client, user_id, *_ = live_account
    before_counts = await counts(user_id)
    image = Image.new("RGB", (480, 320), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 65, 410, 255), outline="blue", width=5)
    draw.text((155, 150), "NXTREP TEST 123", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()
    asset_id = None
    try:
        intent_response = await client.post(
            "/media/images/upload-intents",
            json={
                "purpose": "nutrition_entry",
                "content_type": "image/png",
                "content_length": len(data),
            },
        )
        assert intent_response.status_code == 201
        intent = intent_response.json()
        asset_id = UUID(intent["asset_id"])
        async with httpx.AsyncClient(timeout=60) as uploader:
            try:
                upload = await uploader.put(
                    intent["upload_url"], headers=intent["headers"], content=data
                )
            except Exception:
                raise AssertionError("Synthetic upload failed; signed URL omitted") from None
        assert upload.status_code < 400
        ready = await client.post(
            f"/media/images/{asset_id}/complete",
            json={
                "expected_content_type": "image/png",
                "expected_content_length": len(data),
            },
        )
        assert ready.status_code == 200 and ready.json()["status"] == "ready"
        body = {
            "image_asset_id": str(asset_id),
            "meal_type": "lunch",
            "eaten_at": datetime.now(UTC).isoformat(),
        }
        for attempt in range(2):
            started = monotonic()
            result = await client.post("/nutrition/entry-drafts:estimate-image", json=body)
            elapsed = round(monotonic() - started, 2)
            payload = result.json()
            record(
                {
                    "event": "synthetic_photo",
                    "attempt": attempt + 1,
                    "http_status": result.status_code,
                    "duration_seconds": elapsed,
                    "same_asset": True,
                    "error": payload.get("error"),
                }
            )
            assert result.status_code == 200
            assert payload["recognition"]["foods"] == [], "Non-food image must not fabricate a meal"
            assert payload["calculation"]["is_complete"] is False
        assert await counts(user_id) == before_counts
    finally:
        if asset_id is not None:
            async with SessionFactory() as session:
                asset = await session.get(ImageAsset, asset_id)
                if asset is not None:
                    assert asset.user_id == user_id and str(asset_id) in asset.object_key
                    storage = get_image_storage_provider()
                    try:
                        await asyncio.to_thread(
                            storage._client.delete_object,
                            oss.DeleteObjectRequest(
                                bucket=storage._configuration.bucket, key=asset.object_key
                            ),
                        )
                    except Exception:
                        raise AssertionError("Synthetic image cleanup failed") from None
                    record({"event": "cleanup", "synthetic_image_deleted": True})
