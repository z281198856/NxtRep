from fastapi import APIRouter, status

from nxtrep_backend.api.deps import DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.core.tokens import AuthConfigurationError
from nxtrep_backend.repositories.user import SqlAlchemyUserRepository
from nxtrep_backend.schemas.auth import (
    AuthUserResponse,
    LoginRequest,
    PasswordSetupRequest,
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
    PasswordSetupRequiredError,
)

router = APIRouter()


@router.post(
    "/login",
    response_model=TokenPairResponse,
    status_code=status.HTTP_200_OK,
)
async def login(
    body: LoginRequest,
    session: DbSession,
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

    return TokenPairResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
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

    return TokenPairResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
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

    return TokenPairResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        user=AuthUserResponse.model_validate(result.user),
    )
