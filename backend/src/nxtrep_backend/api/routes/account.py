from fastapi import APIRouter

from nxtrep_backend.api.deps import CurrentUser
from nxtrep_backend.schemas.auth import CurrentAccountResponse

router = APIRouter()


@router.get("/me", response_model=CurrentAccountResponse)
async def get_current_account(user: CurrentUser) -> CurrentAccountResponse:
    return CurrentAccountResponse(
        id=user.id,
        username=user.username,
        status=user.status,
        is_admin=user.is_admin,
        password_setup_required=user.password_setup_required,
        profile_initialized=(
            user.profile is not None
            and user.profile.experience_level is not None
            and user.profile.weekly_training_days is not None
        ),
    )
