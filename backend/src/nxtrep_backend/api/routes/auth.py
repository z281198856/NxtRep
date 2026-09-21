from uuid import UUID

from fastapi import APIRouter, Response, status

from nxtrep_backend.api.deps import CurrentUser, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.core.tokens import AuthConfigurationError
from nxtrep_backend.repositories.user import SqlAlchemyUserRepository
from nxtrep_backend.schemas.auth import (
    AuthUserResponse,
    LoginRequest,
    LogoutRequest,
    PasswordChangeRequest,
    PasswordSetupRequest,
    RefreshSessionListResponse,
    RefreshSessionResponse,
    RefreshTokenRequest,
    TokenPairResponse,
)
from nxtrep_backend.services.account import (
    AccountDisabledError,
    AccountLockedError,
    AccountService,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    InvalidSetupTokenError,
    PasswordReuseError,
    PasswordSetupRequiredError,
    RefreshSessionNotFoundError,
)

router = APIRouter()


def _disable_token_caching(response: Response) -> None:
    """Prevent credentials from being retained by mobile or intermediary caches."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post(
    "/login",
    response_model=TokenPairResponse,
    status_code=status.HTTP_200_OK,
)
async def login(
    body: LoginRequest,
    session: DbSession,
    response: Response,
) -> TokenPairResponse:
    repository = SqlAlchemyUserRepository(session)
    service = AccountService(repository)

    try:
        result = await service.login(
            username=body.username,
            password=body.password,
            device_name=body.device_name,
        )
    except InvalidCredentialsError as exc:
        await session.commit()
        raise ApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_CREDENTIALS",
            message="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AccountDisabledError as exc:
        raise ApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="ACCOUNT_DISABLED",
            message="Account is disabled",
        ) from exc
    except PasswordSetupRequiredError as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="PASSWORD_SETUP_REQUIRED",
            message="Password setup is required",
        ) from exc
    except AccountLockedError as exc:
        await session.commit()
        raise ApiError(
            status_code=status.HTTP_423_LOCKED,
            code="ACCOUNT_LOCKED",
            message="Account is temporarily locked",
        ) from exc
    except AuthConfigurationError as exc:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AUTH_NOT_CONFIGURED",
            message="Authentication service is not configured",
        ) from exc

    _disable_token_caching(response)
    return TokenPairResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        refresh_expires_in=result.refresh_expires_in,
        user=AuthUserResponse.model_validate(result.user),
    )


@router.post(
    "/refresh",
    response_model=TokenPairResponse,
    status_code=status.HTTP_200_OK,
)
async def refresh_tokens(
    body: RefreshTokenRequest,
    session: DbSession,
    response: Response,
) -> TokenPairResponse:
    repository = SqlAlchemyUserRepository(session)
    service = AccountService(repository)

    try:
        result = await service.refresh_tokens(
            refresh_token=body.refresh_token,
        )
    except InvalidRefreshTokenError as exc:
        raise ApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_REFRESH_TOKEN",
            message="Invalid or expired refresh token",
        ) from exc
    except AccountDisabledError as exc:
        raise ApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="ACCOUNT_DISABLED",
            message="Account is disabled",
        ) from exc
    except AuthConfigurationError as exc:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AUTH_NOT_CONFIGURED",
            message="Authentication service is not configured",
        ) from exc

    _disable_token_caching(response)
    return TokenPairResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        refresh_expires_in=result.refresh_expires_in,
        user=AuthUserResponse.model_validate(result.user),
    )


@router.post(
    "/password/setup",
    response_model=TokenPairResponse,
    status_code=status.HTTP_200_OK,
)
async def setup_password(
    body: PasswordSetupRequest,
    session: DbSession,
    response: Response,
) -> TokenPairResponse:
    repository = SqlAlchemyUserRepository(session)
    service = AccountService(repository)

    try:
        result = await service.setup_password(
            username=body.username,
            setup_token=body.setup_token,
            new_password=body.new_password,
        )
    except InvalidSetupTokenError as exc:
        raise ApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_SETUP_TOKEN",
            message="Invalid or expired setup token",
        ) from exc
    except AuthConfigurationError as exc:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AUTH_NOT_CONFIGURED",
            message="Authentication service is not configured",
        ) from exc

    _disable_token_caching(response)
    return TokenPairResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        refresh_expires_in=result.refresh_expires_in,
        user=AuthUserResponse.model_validate(result.user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    session: DbSession,
) -> Response:
    await AccountService(SqlAlchemyUserRepository(session)).logout(
        refresh_token=body.refresh_token,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password/change",
    response_model=TokenPairResponse,
    status_code=status.HTTP_200_OK,
)
async def change_password(
    body: PasswordChangeRequest,
    user: CurrentUser,
    session: DbSession,
    response: Response,
) -> TokenPairResponse:
    try:
        result = await AccountService(SqlAlchemyUserRepository(session)).change_password(
            user_id=user.id,
            current_password=body.current_password,
            new_password=body.new_password,
            device_name=body.device_name,
        )
    except InvalidCredentialsError as exc:
        raise ApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_CURRENT_PASSWORD",
            message="Current password is invalid",
        ) from exc
    except PasswordReuseError as exc:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="PASSWORD_REUSE_NOT_ALLOWED",
            message="New password must differ from current password",
        ) from exc
    except PasswordSetupRequiredError as exc:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="PASSWORD_SETUP_REQUIRED",
            message="Password setup is required",
        ) from exc
    except AccountDisabledError as exc:
        raise ApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="ACCOUNT_DISABLED",
            message="Account is disabled",
        ) from exc
    except AuthConfigurationError as exc:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AUTH_NOT_CONFIGURED",
            message="Authentication service is not configured",
        ) from exc

    _disable_token_caching(response)
    return TokenPairResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        refresh_expires_in=result.refresh_expires_in,
        user=AuthUserResponse.model_validate(result.user),
    )


@router.get("/sessions", response_model=RefreshSessionListResponse)
async def list_sessions(
    user: CurrentUser,
    session: DbSession,
) -> RefreshSessionListResponse:
    sessions = await AccountService(SqlAlchemyUserRepository(session)).list_sessions(
        user_id=user.id
    )
    return RefreshSessionListResponse(
        sessions=[RefreshSessionResponse.model_validate(item) for item in sessions]
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_session(
    session_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> Response:
    try:
        await AccountService(SqlAlchemyUserRepository(session)).revoke_session(
            user_id=user.id, session_id=session_id
        )
    except RefreshSessionNotFoundError as exc:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="REFRESH_SESSION_NOT_FOUND",
            message="Refresh session not found",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
