from fastapi import APIRouter, status

from nxtrep_backend.api.deps import CurrentUserId
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.domain.confirmation import ConfirmationNotFoundError
from nxtrep_backend.schemas.confirmation import (
    ConfirmationCreate,
    ConfirmationDecisionRequest,
    ConfirmationResponse,
)
from nxtrep_backend.services.confirmation import get_confirmation_service

router = APIRouter()


@router.post("", response_model=ConfirmationResponse, status_code=status.HTTP_201_CREATED)
async def create_confirmation(
    body: ConfirmationCreate,
    user_id: CurrentUserId,
) -> ConfirmationResponse:
    draft = await get_confirmation_service().create(user_id=user_id, data=body)
    return ConfirmationResponse.model_validate(draft)


@router.post("/{confirmation_id}/decision", response_model=ConfirmationResponse)
async def decide_confirmation(
    confirmation_id: str,
    body: ConfirmationDecisionRequest,
    user_id: CurrentUserId,
) -> ConfirmationResponse:
    try:
        draft = await get_confirmation_service().decide(
            user_id=user_id,
            confirmation_id=confirmation_id,
            decision=body.decision,
        )
    except ConfirmationNotFoundError as exc:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="CONFIRMATION_NOT_FOUND",
            message=str(exc),
        ) from exc
    return ConfirmationResponse.model_validate(draft)
