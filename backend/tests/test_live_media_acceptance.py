"""Explicit local media acceptance using synthetic fixtures, without personal photos."""

import asyncio
import io
import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import alibabacloud_oss_v2 as oss
import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from test_agent_live_acceptance import ROOT, live_account  # noqa: F401, F811

from nxtrep_backend.core.config import get_settings
from nxtrep_backend.db.models import ImageAsset
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.providers.storage import build_image_storage_provider

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1" or os.getenv("RUN_LIVE_MEDIA_TESTS") != "1",
    reason="Opt-in local API, configured storage and vision provider",
)


@pytest.mark.asyncio(loop_scope="session")
async def test_live_food_upload_recognition_and_body_storage(live_account):  # noqa: F811
    client, user_id, _, _, _ = live_account
    storage = build_image_storage_provider(get_settings())
    assets = []
    evidence = {"food_source": "synthetic banana illustration generated for acceptance"}

    async def upload(data, purpose):
        intent = await client.post(
            "/media/images/upload-intents",
            json={"purpose": purpose, "content_type": "image/jpeg", "content_length": len(data)},
        )
        assert intent.status_code == 201, "Image upload intent failed"
        body = intent.json()
        assets.append(UUID(body["asset_id"]))
        async with httpx.AsyncClient(timeout=90) as external:
            response = await external.put(body["upload_url"], content=data, headers=body["headers"])
        assert response.status_code in {200, 201}, "Direct test-image upload failed"
        complete = await client.post(
            f"/media/images/{body['asset_id']}/complete",
            json={"expected_content_type": "image/jpeg", "expected_content_length": len(data)},
        )
        assert complete.status_code == 200 and complete.json()["status"] == "ready"
        return body["asset_id"]

    try:
        # This synthetic fixture avoids external dataset availability and personal photos.
        from PIL import ImageDraw

        illustration = Image.new("RGB", (512, 512), "white")
        drawing = ImageDraw.Draw(illustration)
        drawing.arc((70, 10, 460, 390), 5, 170, fill=(240, 202, 35), width=65)
        drawing.line((90, 230, 70, 190), fill=(120, 80, 30), width=14)
        image_bytes = io.BytesIO()
        illustration.save(image_bytes, format="JPEG")
        asset_id = await upload(image_bytes.getvalue(), "nutrition_entry")
        evidence["food_upload"] = "ready"
        result = await client.post(
            "/nutrition/entry-drafts:estimate-image",
            json={
                "image_asset_id": asset_id,
                "meal_type": "snack",
                "eaten_at": datetime.now(UTC).isoformat(),
                "notes": "合成香蕉示意图，仅用于独立测试账户接口验收",
            },
        )
        evidence["recognition_http"] = result.status_code
        if result.status_code == 200:
            estimate = result.json()
            evidence["recognition"] = estimate
            assert any("香蕉" in food["name"] for food in estimate["recognition"]["foods"])
            items = []
            for item in estimate["calculation"]["items"]:
                detected = item["match"]["detected"]
                if selected := item["match"].get("selected"):
                    items.append(
                        {
                            "food_version_id": selected["food_version_id"],
                            "amount_g": detected["estimated_amount_g"],
                        }
                    )
                elif item.get("nutrition"):
                    items.append(
                        {
                            "name": detected["name"],
                            "amount_g": detected["estimated_amount_g"],
                            "basis_amount_g": detected["estimated_amount_g"],
                            **item["nutrition"]["estimated"],
                            "source": "model_estimated",
                            "confidence": "low",
                        }
                    )
            assert items, "Recognition had no complete savable nutrition estimate"
            saved = await client.post(
                "/nutrition/entries",
                headers={"Idempotency-Key": str(uuid4())},
                json={
                    "meal_type": "snack",
                    "eaten_at": datetime.now(UTC).isoformat(),
                    "items": items,
                    "notes": "独立测试账户明确核对后保存；不是用户个人记录",
                },
            )
            assert saved.status_code == 201
            evidence["food_saved"] = True
        else:
            code = result.json().get("error", {}).get("code")
            evidence["vision_error_code"] = code
            assert result.status_code == 503 and code in {
                "VISION_MODEL_BUSY",
                "NUTRITION_IMAGE_UNAVAILABLE",
            }
            evidence["food_saved"] = False
        # No real person's body image is read or assessed.
        buffer = io.BytesIO()
        Image.new("RGB", (256, 256), "gray").save(buffer, format="JPEG")
        calibration = await upload(buffer.getvalue(), "body_progress")
        photo = await client.post(
            "/body/progress-photos",
            json={
                "image_asset_id": calibration,
                "captured_at": datetime.now(UTC).isoformat(),
                "view": "unknown",
                "notes": "合成灰色校准图，只测试保存；不触发体态评估",
            },
        )
        assert photo.status_code == 201
        evidence["body_upload_save"] = "passed_without_assessment"
    finally:
        (ROOT / ".local" / "agent-media-live-acceptance.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        async with SessionFactory() as session:
            owned = list(
                await session.scalars(
                    select(ImageAsset).where(
                        ImageAsset.user_id == user_id, ImageAsset.id.in_(assets)
                    )
                )
            )
            for asset in owned:
                expected = storage.create_object_key(user_id, asset.id, "image/jpeg")
                assert asset.object_key == expected, (
                    "Refuse cleanup outside this test user's objects"
                )
                await asyncio.to_thread(
                    storage._client.delete_object,
                    oss.DeleteObjectRequest(
                        bucket=storage._configuration.bucket, key=asset.object_key
                    ),
                )
