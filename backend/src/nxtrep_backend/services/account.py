from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hmac import compare_digest

from sqlalchemy.exc import IntegrityError

from nxtrep_backend.core.config import Settings, get_settings
from nxtrep_backend.core.security import hash_password, verify_password
from nxtrep_backend.core.tokens import (
    create_access_token,
    create_opaque_token,
    hash_opaque_token,
)
from nxtrep_backend.db.models import (
    Credential,
    Profile,
    RefreshSession,
    User,
    UserStatus,
)
from nxtrep_backend.repositories.user import SqlAlchemyUserRepository


class UsernameAlreadyExistsError(RuntimeError):
    """用户名已经存在。"""


class InvalidSetupTokenError(RuntimeError):
    """首次设置密码 Token 无效、已使用或已过期。"""


class InvalidCredentialsError(RuntimeError):
    """用户名或密码错误。"""


class AccountDisabledError(RuntimeError):
    """账号已被禁用。"""


class PasswordSetupRequiredError(RuntimeError):
    """账号还没有完成首次密码设置。"""


class AccountLockedError(RuntimeError):
    """账号当前处于锁定状态。"""


class InvalidRefreshTokenError(RuntimeError):
    """Refresh Token 无效、已撤销或已经过期。"""


@dataclass(frozen=True, slots=True)
class PrecreatedUser:
    user: User
    setup_token: str
    setup_token_expires_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedTokenPair:
    user: User
    access_token: str
    refresh_token: str
    expires_in: int


class AccountService:
    max_failed_login_attempts = 5
    lockout_duration = timedelta(minutes=15)

    def __init__(
        self,
        repository: SqlAlchemyUserRepository,
        settings: Settings | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings or get_settings()

    async def precreate_user(
        self,
        *,
        username: str,
        display_name: str | None = None,
        is_admin: bool = False,
    ) -> PrecreatedUser:
        normalized_username = username.strip()
        normalized_display_name = display_name.strip() or None if display_name is not None else None

        existing_user = await self._repository.get_by_username(normalized_username)

        if existing_user is not None:
            raise UsernameAlreadyExistsError(f"Username {normalized_username!r} already exists")

        setup_token = create_opaque_token()
        setup_token_expires_at = datetime.now(UTC) + timedelta(
            minutes=self._settings.password_setup_token_expire_minutes
        )

        user = User(
            username=normalized_username,
            is_admin=is_admin,
            password_setup_required=True,
            credential=Credential(
                password_hash=None,
                setup_token_hash=hash_opaque_token(setup_token),
                setup_token_expires_at=setup_token_expires_at,
            ),
            profile=Profile(
                display_name=normalized_display_name,
            ),
        )

        try:
            await self._repository.add(user)
        except IntegrityError as exc:
            # 即使两个请求同时创建相同用户名，
            # 数据库唯一索引也会阻止重复账号。
            raise UsernameAlreadyExistsError(
                f"Username {normalized_username!r} already exists"
            ) from exc

        return PrecreatedUser(
            user=user,
            setup_token=setup_token,
            setup_token_expires_at=setup_token_expires_at,
        )

    async def setup_password(
        self,
        *,
        username: str,
        setup_token: str,
        new_password: str,
    ) -> IssuedTokenPair:
        now = datetime.now(UTC)

        user = await self._repository.get_by_username(
            username,
            for_update=True,
        )

        if user is None or user.credential is None:
            raise InvalidSetupTokenError("Invalid or expired setup token")

        credential = user.credential
        submitted_token_hash = hash_opaque_token(setup_token)

        setup_token_is_invalid = (
            not user.password_setup_required
            or credential.setup_token_hash is None
            or credential.setup_token_expires_at is None
            or credential.setup_token_expires_at <= now
            or not compare_digest(
                credential.setup_token_hash,
                submitted_token_hash,
            )
        )

        if setup_token_is_invalid:
            raise InvalidSetupTokenError("Invalid or expired setup token")

        credential.password_hash = hash_password(new_password)
        credential.password_changed_at = now
        credential.setup_token_hash = None
        credential.setup_token_expires_at = None
        credential.failed_login_attempts = 0
        credential.locked_until = None

        user.password_setup_required = False

        access_token = create_access_token(
            user.id,
            self._settings,
        )
        refresh_token = create_opaque_token()
        refresh_token_expires_at = now + timedelta(days=self._settings.refresh_token_expire_days)

        refresh_session = RefreshSession(
            user_id=user.id,
            token_hash=hash_opaque_token(refresh_token),
            expires_at=refresh_token_expires_at,
        )

        await self._repository.add_refresh_session(refresh_session)

        return IssuedTokenPair(
            user=user,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self._settings.access_token_expire_minutes * 60,
        )

    async def login(
        self,
        *,
        username: str,
        password: str,
        device_name: str | None = None,
    ) -> IssuedTokenPair:
        now = datetime.now(UTC)

        user = await self._repository.get_by_username(
            username,
            for_update=True,
        )

        if user is None or user.credential is None:
            raise InvalidCredentialsError("Invalid username or password")

        if user.status != UserStatus.ACTIVE.value:
            raise AccountDisabledError("Account is disabled")

        credential = user.credential

        if user.password_setup_required or credential.password_hash is None:
            raise PasswordSetupRequiredError("Password setup is required")

        if credential.locked_until is not None and credential.locked_until > now:
            raise AccountLockedError("Account is temporarily locked")

        if credential.locked_until is not None:
            credential.locked_until = None
            credential.failed_login_attempts = 0

        if not verify_password(password, credential.password_hash):
            credential.failed_login_attempts += 1
            if credential.failed_login_attempts >= self.max_failed_login_attempts:
                credential.locked_until = now + self.lockout_duration
                raise AccountLockedError("Account is temporarily locked")
            raise InvalidCredentialsError("Invalid username or password")

        credential.failed_login_attempts = 0
        credential.locked_until = None
        user.last_login_at = now

        access_token = create_access_token(
            user.id,
            self._settings,
        )
        refresh_token = create_opaque_token()
        refresh_token_expires_at = now + timedelta(days=self._settings.refresh_token_expire_days)

        refresh_session = RefreshSession(
            user_id=user.id,
            token_hash=hash_opaque_token(refresh_token),
            device_name=device_name,
            expires_at=refresh_token_expires_at,
        )

        await self._repository.add_refresh_session(refresh_session)

        return IssuedTokenPair(
            user=user,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self._settings.access_token_expire_minutes * 60,
        )

    async def refresh_tokens(
        self,
        *,
        refresh_token: str,
    ) -> IssuedTokenPair:
        now = datetime.now(UTC)
        submitted_token_hash = hash_opaque_token(refresh_token)

        refresh_session = await self._repository.get_active_refresh_session_by_token_hash(
            submitted_token_hash,
            for_update=True,
        )

        if refresh_session is None:
            raise InvalidRefreshTokenError("Invalid or expired refresh token")

        user = refresh_session.user

        if user.deleted_at is not None:
            raise InvalidRefreshTokenError("Invalid or expired refresh token")

        if user.status != UserStatus.ACTIVE.value:
            raise AccountDisabledError("Account is disabled")

        if user.password_setup_required:
            raise InvalidRefreshTokenError("Invalid or expired refresh token")

        # 旧 Refresh Token 使用一次后立即失效。
        refresh_session.last_used_at = now
        refresh_session.revoked_at = now

        access_token = create_access_token(
            user.id,
            self._settings,
        )
        new_refresh_token = create_opaque_token()
        new_refresh_token_expires_at = now + timedelta(
            days=self._settings.refresh_token_expire_days
        )

        new_refresh_session = RefreshSession(
            user_id=user.id,
            token_hash=hash_opaque_token(new_refresh_token),
            device_name=refresh_session.device_name,
            expires_at=new_refresh_token_expires_at,
        )

        await self._repository.add_refresh_session(new_refresh_session)

        return IssuedTokenPair(
            user=user,
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=self._settings.access_token_expire_minutes * 60,
        )
