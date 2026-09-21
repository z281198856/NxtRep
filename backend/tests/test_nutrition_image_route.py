from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.agents.nutrition_vision import (
    FoodImageRecognitionError,
    FoodNutritionFallbackError,
)
from nxtrep_backend.api.deps import get_current_user
from nxtrep_backend.api.routes import nutrition as nutrition_route
from nxtrep_backend.core.config import StorageConfigurationError
from nxtrep_backend.db.models import User
from nxtrep_backend.db.session import get_db_session
from nxtrep_backend.main import app
from nxtrep_backend.providers.models import ModelConfigurationError
from nxtrep_backend.providers.storage import StorageProviderError
from nxtrep_backend.schemas.nutrition import (
    FoodImageRecognitionResult,
    NutritionDraftCalculation,
    NutritionEstimateRange,
    NutritionImageDraftResponse,
    NutritionTotals,
)
from nxtrep_backend.services.agent_media import (
    AgentImageAssetNotFoundError,
    AgentImageAssetNotReadyError,
)
from nxtrep_backend.services.nutrition_image import NutritionImagePurposeError


@pytest.fixture
def client() -> Iterator[tuple[TestClient, MagicMock]]:
    session = MagicMock(spec=AsyncSession)

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides[get_db_session] = override_db_session

    with TestClient(app) as test_client:
        yield test_client, session

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db_session, None)


def make_user() -> User:
    return User(
        id=uuid4(),
        username="nutrition-image-user",
        password_setup_required=False,
    )


def make_response(asset_id) -> NutritionImageDraftResponse:
    zero = NutritionTotals(
        kcal=Decimal("0"),
        protein_g=Decimal("0"),
        carbs_g=Decimal("0"),
        fat_g=Decimal("0"),
    )
    totals = NutritionEstimateRange(
        minimum=zero,
        estimated=zero,
        maximum=zero,
    )
    return NutritionImageDraftResponse(
        image_asset_id=asset_id,
        meal_type="lunch",
        eaten_at=datetime.fromisoformat("2026-08-31T12:30:00+08:00"),
        notes="米饭大约一碗",
        recognition=FoodImageRecognitionResult(
            foods=[],
            assumptions=[],
            follow_up_questions=["没有识别到食物，请重新拍摄。"],
        ),
        calculation=NutritionDraftCalculation(
            items=[],
            totals=totals,
            is_complete=False,
        ),
    )


def build_estimator_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> MagicMock:
    estimator = MagicMock()
    estimator.estimate = AsyncMock()
    monkeypatch.setattr(
        nutrition_route,
        "_build_nutrition_image_estimator",
        MagicMock(return_value=estimator),
        raising=False,
    )
    return estimator


def test_estimate_image_route_returns_editable_nutrition_draft(
    client: tuple[TestClient, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, session = client
    user = make_user()
    asset_id = uuid4()
    app.dependency_overrides[get_current_user] = lambda: user
    estimator = build_estimator_mock(monkeypatch)
    estimator.estimate.return_value = make_response(asset_id)

    response = test_client.post(
        "/api/v1/nutrition/entry-drafts:estimate-image",
        json={
            "image_asset_id": str(asset_id),
            "meal_type": "lunch",
            "eaten_at": "2026-08-31T12:30:00+08:00",
            "notes": "米饭大约一碗",
        },
    )

    assert response.status_code == 200
    assert response.json()["image_asset_id"] == str(asset_id)
    assert response.json()["calculation"]["is_complete"] is False
    nutrition_route._build_nutrition_image_estimator.assert_called_once_with(session)
    estimator.estimate.assert_awaited_once()
    assert estimator.estimate.await_args.kwargs["user_id"] == user.id


@pytest.mark.parametrize(
    ("error", "status_code", "error_code"),
    [
        (AgentImageAssetNotFoundError(), 404, "IMAGE_ASSET_NOT_FOUND"),
        (AgentImageAssetNotReadyError(), 409, "IMAGE_ASSET_NOT_READY"),
        (NutritionImagePurposeError(), 422, "NUTRITION_IMAGE_PURPOSE_INVALID"),
        (StorageProviderError(), 503, "IMAGE_STORAGE_UNAVAILABLE"),
        (FoodImageRecognitionError(), 502, "VISION_MODEL_INVALID_RESPONSE"),
        (FoodNutritionFallbackError(), 502, "VISION_MODEL_INVALID_RESPONSE"),
        (ModelConfigurationError(), 503, "NUTRITION_IMAGE_NOT_CONFIGURED"),
        (StorageConfigurationError(), 503, "NUTRITION_IMAGE_NOT_CONFIGURED"),
    ],
)
def test_estimate_image_route_maps_pipeline_errors(
    client: tuple[TestClient, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
    error: RuntimeError,
    status_code: int,
    error_code: str,
) -> None:
    test_client, _ = client
    app.dependency_overrides[get_current_user] = lambda: make_user()
    estimator = build_estimator_mock(monkeypatch)
    estimator.estimate.side_effect = error

    response = test_client.post(
        "/api/v1/nutrition/entry-drafts:estimate-image",
        json={
            "image_asset_id": str(uuid4()),
            "meal_type": "lunch",
            "eaten_at": "2026-08-31T12:30:00+08:00",
        },
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
