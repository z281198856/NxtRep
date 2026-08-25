from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID, uuid4

import jwt
from jwt.exceptions import InvalidTokenError

from nxtrep_backend.core.config import Settings, get_settings

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"
OPAQUE_TOKEN_BYTES = 48


class AuthConfigurationError(RuntimeError):
    """认证相关配置缺失。"""


class InvalidAccessTokenError(ValueError):
    """Access Token 无效、被篡改或已经过期。"""


def _get_jwt_secret(settings: Settings) -> str:
    if settings.jwt_secret is None:
        raise AuthConfigurationError("JWT secret is not configured")

    secret = settings.jwt_secret.get_secret_value()

    if not secret:
        raise AuthConfigurationError("JWT secret is not configured")

    return secret


def create_access_token(
    user_id: UUID,
    settings: Settings | None = None,
) -> str:
    configuration = settings or get_settings()
    secret = _get_jwt_secret(configuration)
    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=configuration.access_token_expire_minutes)

    payload: dict[str, object] = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": issued_at,
        "exp": expires_at,
        "jti": str(uuid4()),
    }

    return jwt.encode(
        payload,
        secret,
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(
    token: str,
    settings: Settings | None = None,
) -> UUID:
    configuration = settings or get_settings()
    secret = _get_jwt_secret(configuration)

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            options={
                "require": ["sub", "type", "iat", "exp", "jti"],
            },
        )
    except InvalidTokenError as exc:
        raise InvalidAccessTokenError("Invalid access token") from exc

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise InvalidAccessTokenError("Invalid access token type")

    subject = payload.get("sub")
    token_id = payload.get("jti")

    if not isinstance(subject, str) or not subject:
        raise InvalidAccessTokenError("Invalid access token subject")

    if not isinstance(token_id, str) or not token_id:
        raise InvalidAccessTokenError("Invalid access token identifier")

    try:
        return UUID(subject)
    except ValueError as exc:
        raise InvalidAccessTokenError("Invalid access token subject") from exc


def create_opaque_token() -> str:
    """生成 Refresh Token 或首次设置密码 Token。"""
    return token_urlsafe(OPAQUE_TOKEN_BYTES)


def hash_opaque_token(token: str) -> str:
    """生成用于数据库保存和查询的 Token 哈希。"""
    if not token:
        raise ValueError("Token cannot be empty")

    return sha256(token.encode("utf-8")).hexdigest()
