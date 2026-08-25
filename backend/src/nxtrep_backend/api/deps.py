from typing import Annotated
from uuid import UUID

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.core.config import Settings, get_settings
from nxtrep_backend.core.tokens import (
    AuthConfigurationError,
    InvalidAccessTokenError,
    decode_access_token,
)
from nxtrep_backend.db.models import User, UserStatus
from nxtrep_backend.db.session import get_db_session
from nxtrep_backend.repositories.user import SqlAlchemyUserRepository

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    session: DbSession,
    settings: AppSettings,
) -> User:
    if credentials is None:
        raise ApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTHENTICATION_REQUIRED",
            message="Bearer access token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = decode_access_token(
            credentials.credentials,
            settings,
        )
    except InvalidAccessTokenError as exc:
        raise ApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_ACCESS_TOKEN",
            message="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AuthConfigurationError as exc:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AUTH_NOT_CONFIGURED",
            message="Authentication service is not configured",
        ) from exc

    repository = SqlAlchemyUserRepository(session)
    user = await repository.get_by_id(user_id)

    if user is None:
        raise ApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_ACCESS_TOKEN",
            message="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.status != UserStatus.ACTIVE.value:
        raise ApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="ACCOUNT_DISABLED",
            message="Account is disabled",
        )

    if user.password_setup_required:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="PASSWORD_SETUP_REQUIRED",
            message="Password setup is required",
        )

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_user_id(
    user: CurrentUser,
) -> UUID:
    return user.id


CurrentUserId = Annotated[UUID, Depends(get_current_user_id)]
