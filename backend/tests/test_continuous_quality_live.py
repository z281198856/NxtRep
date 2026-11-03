"""Bounded, repeatable real-model checks on disposable accounts and consented images."""

import asyncio
import io
import json
import mimetypes
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

import alibabacloud_oss_v2 as oss
import httpx
import pytest
import pytest_asyncio
from PIL import Image, ImageDraw
from sqlalchemy import func, select
from test_agent_live_acceptance import live_account  # noqa: F401

from nxtrep_backend.api.routes.media import get_image_storage_provider
from nxtrep_backend.core.config import get_settings
from nxtrep_backend.db.models import BodyMeasurement, ImageAsset, NutritionEntry, WorkoutSet
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.evaluation.answer_quality import check_volume_answer
from nxtrep_backend.evaluation.photo_quality import (
    PhotoQualitySample,
    load_photo_samples,
    photo_fingerprint,
    score_photo,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_CONTINUOUS_QUALITY_LIVE") != "1", reason="Explicit live quality run required"
)
REPEATS = int(os.getenv("QUALITY_REPEATS", "1"))
ROOT = Path(__file__).resolve().parents[2]


def evidence(row):
    path = Path(os.environ["QUALITY_EVIDENCE_PATH"])
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    path.write_text(json.dumps([*previous, row], ensure_ascii=False, indent=2), encoding="utf-8")


@pytest_asyncio.fixture(loop_scope="session")
async def quality_account(live_account):  # noqa: F811
    client, user_id, *_ = live_account
    settings = get_settings()
    evidence(
        {
            "event": "configured_models",
            "models": {
                key: getattr(settings, key)
                for key in (
                    "deepseek_model",
                    "glm_model",
                    "glm_vision_model",
                    "food_vision_model",
                    "food_vision_fallback_model",
                )
            },
        }
    )
    return client, user_id


async def formal_counts(user_id):
    async with SessionFactory() as session:
        measurements = await session.scalar(
            select(func.count())
            .select_from(BodyMeasurement)
            .where(BodyMeasurement.user_id == user_id)
        )
        meals = await session.scalar(
            select(func.count())
            .select_from(NutritionEntry)
            .where(NutritionEntry.user_id == user_id)
        )
        # Workout sets are scoped through the user's workout, not globally.
        from nxtrep_backend.db.models import Workout

        sets = await session.scalar(
            select(func.count())
            .select_from(WorkoutSet)
            .join(Workout, Workout.id == WorkoutSet.workout_id)
            .where(Workout.user_id == user_id)
        )
        return [measurements, meals, sets]


@pytest.mark.asyncio(loop_scope="session")
async def test_real_ai_answer_replay_and_draft_revision(quality_account):
    client, user_id = quality_account
    before = await formal_counts(user_id)
    for repeat in range(REPEATS):
        body = {
            "message": (
                "请解释本应用训练容量怎样计算，记录过的热身组是否计入？只解释口径，不修改数据。"
            ),
            "client_turn_id": str(uuid4()),
        }
        started = monotonic()
        response = await client.post("/agent/chat", json=body)
        payload = response.json()
        checks = {
            "http_success": response.status_code == 200,
            "completed": payload.get("status") == "completed",
            "no_confirmation": not payload.get("confirmation_cards"),
            **check_volume_answer(payload.get("message", "")),
            "no_internal_jargon": not any(
                x in payload.get("message", "")
                for x in ("tool_call", "Traceback", "execution_bundle")
            ),
        }
        replay = await client.post("/agent/chat", json=body)
        checks["idempotent_replay"] = (
            replay.status_code == 200
            and bool(payload.get("run_id"))
            and (
                replay.json().get("run_id") == payload.get("run_id")
                and replay.json().get("message") == payload.get("message")
            )
        )
        checks["no_formal_writes"] = await formal_counts(user_id) == before
        evidence(
            {
                "case_id": "ai-volume-replay",
                "repeat": repeat + 1,
                "seconds": round(monotonic() - started, 3),
                "checks": checks,
                "passed": all(checks.values()),
                "message": payload.get("message"),
            }
        )
        assert all(checks.values()), "AI quality gate failed; inspect private quality evidence"

    conversation = await client.post("/agent/conversations", json={"title": "质量验证"})
    assert conversation.status_code in (200, 201)
    conversation_id = conversation.json()["id"]
    for index, message in enumerate(
        [
            "帮我记今天午餐熟米饭100克，按常见营养估算，先给待确认草稿。",
            "把刚才待确认的熟米饭改成150克，其余不变，重新给待确认草稿。",
        ]
    ):
        started = monotonic()
        response = await client.post(
            "/agent/chat",
            json={
                "conversation_id": conversation_id,
                "message": message,
                "client_turn_id": str(uuid4()),
            },
        )
        payload = response.json()
        cards = payload.get("confirmation_cards", [])
        checks = {
            "http_success": response.status_code == 200,
            "has_confirmation": bool(cards),
            "no_formal_writes": await formal_counts(user_id) == before,
        }
        if index == 1:
            revised_items = [
                item
                for card in cards
                for item in ((card.get("after") or {}).get("preview") or {}).get("items", [])
            ]
            checks["corrected_portion"] = len(revised_items) == 1 and (
                "米饭" in revised_items[0].get("name", "")
                and Decimal(str(revised_items[0].get("amount_g", 0))) == Decimal("150")
            )
        evidence(
            {
                "case_id": f"ai-draft-turn-{index + 1}",
                "seconds": round(monotonic() - started, 3),
                "checks": checks,
                "passed": all(checks.values()),
            }
        )
        assert all(checks.values()), "Multi-turn quality gate failed; inspect private evidence"


@pytest.mark.asyncio(loop_scope="session")
async def test_real_photo_boundaries_and_optional_weighed_samples(quality_account):
    client, user_id = quality_account
    before = await formal_counts(user_id)
    image = Image.new("RGB", (480, 320), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 50, 430, 270), outline="blue", width=6)
    draw.text((140, 155), "NXTREP QUALITY 123", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    synthetic = PhotoQualitySample(
        sample_id="synthetic-non-food", image_path="synthetic", non_food=True
    )
    samples = [(synthetic, buffer.getvalue(), "image/png", None)]
    manifest = os.getenv("QUALITY_PHOTO_MANIFEST")
    if manifest:
        for sample in load_photo_samples(Path(manifest)):
            content_type = mimetypes.guess_type(sample.image_path)[0]
            assert content_type in {"image/png", "image/jpeg", "image/webp"}, (
                "Unsupported sample type"
            )
            samples.append(
                (
                    sample,
                    Path(sample.image_path).read_bytes(),
                    content_type,
                    photo_fingerprint(sample),
                )
            )
    for sample, data, content_type, fingerprint in samples:
        asset_id = None
        try:
            intent = await client.post(
                "/media/images/upload-intents",
                json={
                    "purpose": "nutrition_entry",
                    "content_type": content_type,
                    "content_length": len(data),
                },
            )
            assert intent.status_code == 201, "Temporary quality image intent failed"
            upload = intent.json()
            asset_id = UUID(upload["asset_id"])
            try:
                async with httpx.AsyncClient(timeout=60) as uploader:
                    sent = await uploader.put(
                        upload["upload_url"], headers=upload["headers"], content=data
                    )
            except Exception:
                raise AssertionError(
                    "Temporary quality upload failed; signed URL omitted"
                ) from None
            assert sent.status_code < 400
            ready = await client.post(
                f"/media/images/{asset_id}/complete",
                json={"expected_content_type": content_type, "expected_content_length": len(data)},
            )
            assert ready.status_code == 200
            for repeat in range(REPEATS):
                started = monotonic()
                response = await client.post(
                    "/nutrition/entry-drafts:estimate-image",
                    json={
                        "image_asset_id": str(asset_id),
                        "meal_type": "lunch",
                        "eaten_at": datetime.now(UTC).isoformat(),
                    },
                )
                result = {
                    "case_id": sample.sample_id,
                    "repeat": repeat + 1,
                    "seconds": round(monotonic() - started, 3),
                    "http_status": response.status_code,
                    "sha256": fingerprint,
                    "reused_asset": True,
                }
                if response.status_code == 200:
                    try:
                        result.update(score_photo(sample, response.json()))
                    except (KeyError, TypeError, ValueError):
                        result.update(passed=False, error="INVALID_PHOTO_RESPONSE")
                else:
                    result.update(passed=False, error="PHOTO_REQUEST_FAILED")
                result["no_formal_writes"] = await formal_counts(user_id) == before
                result["passed"] = result.get("passed", False) and result["no_formal_writes"]
                evidence(result)
                assert result["passed"], (
                    "Photo quality gate failed; inspect private quality evidence"
                )
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
                            raise AssertionError("Temporary quality image cleanup failed") from None
                        evidence(
                            {
                                "event": "cleanup",
                                "sample_id": sample.sample_id,
                                "temporary_image_deleted": True,
                            }
                        )
