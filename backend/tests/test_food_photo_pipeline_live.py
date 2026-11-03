"""Opt-in full food-photo API acceptance using a user-specified food image."""

import asyncio
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

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
    reason="Explicit food photo, configured vision service and local API required",
)
EVIDENCE = ROOT / ".local/food-photo-pipeline-live.json"


@pytest.mark.asyncio(loop_scope="session")
async def test_real_photo_natural_meal_date_draft_and_read_only_assessment(live_account):  # noqa: F811
    client, user_id, *_ = live_account
    data = Path(os.environ["FOOD_PHOTO_ACCEPTANCE_IMAGE"]).read_bytes()
    asset_id = None
    events = []
    try:
        response = await client.post(
            "/media/images/upload-intents",
            json={
                "purpose": "chat_attachment",
                "content_type": "image/png",
                "content_length": len(data),
            },
        )
        assert response.status_code == 201, "Photo upload intent failed"
        intent = response.json()
        asset_id = UUID(intent["asset_id"])
        # Never use the authenticated App client for a signed object-storage URL.
        try:
            async with httpx.AsyncClient(timeout=60) as upload_client:
                uploaded = await upload_client.put(
                    intent["upload_url"], headers=intent["headers"], content=data
                )
        except Exception:
            raise AssertionError("Temporary photo upload failed; signed URL omitted") from None
        assert uploaded.status_code < 400, "Temporary photo object upload rejected"
        completed = await client.post(
            f"/media/images/{asset_id}/complete",
            json={"expected_content_type": "image/png", "expected_content_length": len(data)},
        )
        assert completed.status_code == 200 and completed.json()["status"] == "ready"
        events.append({"event": "upload", "ready": True})

        async def count_entries():
            async with SessionFactory() as session:
                return await session.scalar(
                    select(func.count())
                    .select_from(NutritionEntry)
                    .where(NutritionEntry.user_id == user_id)
                )

        async def chat(message):
            result = await client.post(
                "/agent/chat",
                json={
                    "message": message,
                    "image_asset_ids": [str(asset_id)],
                    "client_turn_id": str(uuid4()),
                    "context_hints": {
                        "occurred_at": datetime.now(UTC).isoformat(),
                        "timezone": None,
                        "meal_type": None,
                    },
                },
            )
            payload = result.json()
            events.append(
                {
                    "event": "chat",
                    "request": message,
                    "http_status": result.status_code,
                    "response": payload,
                }
            )
            EVIDENCE.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
            assert result.status_code == 200, "Inspect food-photo-pipeline-live.json"
            assert payload["status"] == "completed", "Inspect food-photo-pipeline-live.json"
            assert all(b["status"] == "completed" for b in payload["analysis_results"])
            return payload

        before = await count_entries()
        result = await chat("这是昨天中午吃的")
        assert len(result["confirmation_cards"]) == 1
        card = result["confirmation_cards"][0]
        entry = card["after"]["entry"]
        expected_day = datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
        assert entry["meal_type"] == "lunch" and entry["eaten_at"].startswith(str(expected_day))
        items = card["after"]["preview"]["items"]
        assert len(items) >= 3 and any("饭" in item["name"] for item in items)
        assert "暂按12:00" in entry["notes"]
        assert not any(
            text in result["message"] for text in ("缺餐次", "餐次信息", "确认项尚未生成")
        )
        assert await count_entries() == before, "Draft must not create a formal meal"

        query = await chat("只评估这张午饭照片的大概热量，不记录饮食，也不要生成草稿。")
        assert not query["confirmation_cards"] and await count_entries() == before
        analysis = next(
            b for b in query["analysis_results"] if b["task_type"] == "nutrition_analysis"
        )
        assert not analysis["requires_confirmation"]
        assert analysis["result"]["calculation"]["is_complete"]
        estimated_kcal = float(analysis["result"]["calculation"]["totals"]["estimated"]["kcal"])
        reply_kcal = [
            float(value.replace(",", ""))
            for value in re.findall(r"(\d[\d,]*(?:\.\d+)?)\s*(?:千卡|大卡|kcal)", query["message"])
        ]
        assert any(
            abs(value - estimated_kcal) <= max(5, estimated_kcal * 0.02) for value in reply_kcal
        ), "Reply must convey the actual photo estimate, allowing normal rounding"
        assert not any(
            text in query["message"]
            for text in ("没有返回可用", "结果都是空", "没有可用的具体数值")
        ), "Completed photo calculation must not be described as empty"
        events.append(
            {
                "event": "verified",
                "yesterday_lunch": True,
                "draft_only": True,
                "read_only_assessment": True,
                "reply_conveys_calculated_energy": True,
            }
        )
    finally:
        # Remove only this synthetic account's exact test object; never delete the original image.
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
                        raise AssertionError("Temporary test photo cleanup failed") from None
                    events.append({"event": "cleanup", "temporary_image_deleted": True})
        EVIDENCE.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
