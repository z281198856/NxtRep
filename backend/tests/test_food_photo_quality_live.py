"""Opt-in original-photo acceptance for the Nutrition page, without saving meals."""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import alibabacloud_oss_v2 as oss
import httpx
import pytest
from sqlalchemy import func, select
from test_agent_live_acceptance import ROOT, live_account  # noqa: F401

from nxtrep_backend.api.routes.media import get_image_storage_provider
from nxtrep_backend.db.models import ImageAsset, NutritionEntry
from nxtrep_backend.db.session import SessionFactory

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1"
    or os.getenv("RUN_FOOD_PHOTO_LIVE_TESTS") != "1"
    or not os.getenv("FOOD_PHOTO_ACCEPTANCE_IMAGE"),
    reason="Explicit food image and live API required",
)
EVIDENCE = ROOT / ".local/food-photo-quality-live.json"


@pytest.mark.asyncio(loop_scope="session")
async def test_nutrition_page_photo_and_user_correction_are_read_only(live_account):  # noqa: F811
    client, user_id, *_ = live_account
    asset_id = None
    events = []
    try:
        data = Path(os.environ["FOOD_PHOTO_ACCEPTANCE_IMAGE"]).read_bytes()
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
        try:
            async with httpx.AsyncClient(timeout=60) as uploader:
                uploaded = await uploader.put(
                    intent["upload_url"], headers=intent["headers"], content=data
                )
        except Exception:
            raise AssertionError("Temporary image upload failed; signed URL omitted") from None
        assert uploaded.status_code < 400
        ready = await client.post(
            f"/media/images/{asset_id}/complete",
            json={"expected_content_type": "image/png", "expected_content_length": len(data)},
        )
        assert ready.status_code == 200 and ready.json()["status"] == "ready"

        async def count():
            async with SessionFactory() as session:
                return await session.scalar(
                    select(func.count())
                    .select_from(NutritionEntry)
                    .where(NutritionEntry.user_id == user_id)
                )

        baseline = await count()
        body = {
            "image_asset_id": str(asset_id),
            "meal_type": "lunch",
            "eaten_at": datetime.now(UTC).isoformat(),
            "notes": None,
        }
        first = await client.post("/nutrition/entry-drafts:estimate-image", json=body)
        events.append(
            {"event": "initial_photo", "http_status": first.status_code, "response": first.json()}
        )
        EVIDENCE.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        assert first.status_code == 200, "Inspect food-photo-quality-live.json"
        draft = first.json()
        foods = draft["recognition"]["foods"]
        assert len(foods) == 3 and draft["calculation"]["is_complete"]
        assert any("米饭" in f["name"] for f in foods)
        assert any("番茄" in f["name"] or "西红柿" in f["name"] for f in foods)
        assert not any(f["name"] in {"炒鸡蛋", "鸡蛋", "炒蛋"} for f in foods)
        assert all(f.get("portion_basis") for f in foods)
        assert await count() == baseline

        # A synthetic user correction tests execution fidelity, not photo ground truth.
        reviewed = [dict(food) for food in foods]
        rice = next(food for food in reviewed if "米饭" in food["name"])
        rice.update(
            estimated_amount_g="150",
            amount_min_g="150",
            amount_max_g="150",
            portion_basis="测试输入的150克，不代表图片真实重量",
            portion_confidence="low",
        )
        meat = next(
            food
            for food in reviewed
            if "米饭" not in food["name"]
            and "番茄" not in food["name"]
            and "西红柿" not in food["name"]
        )
        meat["name"] = "洋葱炒肉（肉类品种未确定）"
        meat["visual_evidence"] = None
        corrected = await client.post(
            "/nutrition/entry-drafts:estimate-image",
            json={**body, "reviewed_foods": reviewed, "notes": "按常见家常做法估算，未称重。"},
        )
        events.append(
            {
                "event": "corrected_photo",
                "http_status": corrected.status_code,
                "response": corrected.json(),
            }
        )
        assert corrected.status_code == 200
        revised = corrected.json()
        assert revised["calculation"]["is_complete"]
        assert revised["eaten_at"] == draft["eaten_at"]
        assert revised["recognition"]["foods"] == reviewed
        assert await count() == baseline
        events.append(
            {
                "event": "verified",
                "no_formal_writes": True,
                "visible_food_classes": True,
                "corrected_names_and_grams_preserved": True,
            }
        )
    finally:
        if asset_id is not None:
            async with SessionFactory() as session:
                asset = await session.get(ImageAsset, asset_id)
                if asset is not None:
                    assert asset.user_id == user_id and str(user_id) in asset.object_key
                    assert str(asset_id) in asset.object_key
                    storage = get_image_storage_provider()
                    try:
                        await asyncio.to_thread(
                            storage._client.delete_object,
                            oss.DeleteObjectRequest(
                                bucket=storage._configuration.bucket, key=asset.object_key
                            ),
                        )
                    except Exception:
                        raise AssertionError("Temporary image cleanup failed") from None
                    events.append({"event": "cleanup", "temporary_image_deleted": True})
        EVIDENCE.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
