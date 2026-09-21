from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.api.routes import body_progress as body_progress_route
from nxtrep_backend.providers.model_errors import VisionModelBusyError


def test_image_workflow_configures_single_photo_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = MagicMock()
    session = MagicMock(spec=AsyncSession)
    primary_model = MagicMock(name="primary_model")
    fallback_model = MagicMock(name="fallback_model")
    assessor = MagicMock(name="assessor")
    workflow = MagicMock(name="workflow")
    assessor_factory = MagicMock(return_value=assessor)
    workflow_factory = MagicMock(return_value=workflow)

    monkeypatch.setattr(body_progress_route, "get_settings", lambda: settings)
    monkeypatch.setattr(
        body_progress_route,
        "build_image_storage_provider",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        body_progress_route,
        "build_vision_model",
        MagicMock(return_value=primary_model),
    )
    monkeypatch.setattr(
        body_progress_route,
        "build_fallback_vision_model",
        MagicMock(return_value=fallback_model),
    )
    monkeypatch.setattr(body_progress_route, "GlmBodyImageAssessor", assessor_factory)
    monkeypatch.setattr(body_progress_route, "BodyImageWorkflow", workflow_factory)

    result = body_progress_route._image_workflow(session)

    assert result is workflow
    assessor_factory.assert_called_once_with(
        primary_model,
        fallback_model=fallback_model,
    )


def test_vision_busy_is_returned_as_retryable_api_error() -> None:
    with pytest.raises(ApiError) as raised:
        body_progress_route._raise_vision_busy(VisionModelBusyError("provider overloaded"))

    assert raised.value.status_code == 503
    assert raised.value.code == "VISION_MODEL_BUSY"
    assert raised.value.headers == {"Retry-After": "5"}
