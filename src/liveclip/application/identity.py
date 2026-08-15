from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from pydantic import BaseModel, ConfigDict

from liveclip.application.workspace import SystemRole, WorkspaceUser

MIN_PASSWORD_CHARACTERS = 12
MAX_PASSWORD_CHARACTERS = 128


class AuthenticationFailed(PermissionError):
    """Credentials or an opaque session could not be authenticated."""


class LoginRateLimited(PermissionError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("login attempts are temporarily limited")
        self.retry_after_seconds = max(1, retry_after_seconds)


class AdministrationDenied(PermissionError):
    """The caller is not an active system administrator."""


class IdentityConflict(RuntimeError):
    """An identity mutation conflicts with an invariant or existing account."""


class ManagedUser(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    user_id: str
    username: str
    display_name: str
    system_role: SystemRole
    is_active: bool
    password_configured: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None

    def as_workspace_user(self) -> WorkspaceUser:
        return WorkspaceUser(
            user_id=self.user_id,
            username=self.username,
            display_name=self.display_name,
            system_role=self.system_role,
        )


class UserAdministrationResult(BaseModel):
    """One atomic administrator mutation and its post-mutation user snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    user: ManagedUser
    users: tuple[ManagedUser, ...]


class AuthUserRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    user: ManagedUser
    password_hash: str | None
    auth_version: int


class AuthenticatedSession(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    session_id: str
    user: WorkspaceUser
    expires_at: datetime
    caller_scope: str


class SessionGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    raw_token: str
    csrf_token: str
    session: AuthenticatedSession


class IdentityRepository(Protocol):
    def password_login_required(self) -> bool: ...

    def find_auth_user(self, username: str) -> AuthUserRecord | None: ...

    def check_login_allowed(self, *, identity_hash: str, now: datetime) -> int | None: ...

    def record_login_failure(
        self,
        *,
        identity_hash: str,
        now: datetime,
        window_seconds: int,
        maximum_attempts: int,
        block_seconds: int,
        correlation_id: str | None,
    ) -> int | None: ...

    def create_session(
        self,
        *,
        user: AuthUserRecord,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
        correlation_id: str | None,
    ) -> AuthenticatedSession: ...

    def get_session(self, *, token_hash: str, now: datetime) -> AuthenticatedSession | None: ...

    def revoke_session(
        self,
        *,
        token_hash: str,
        now: datetime,
        correlation_id: str | None,
    ) -> None: ...

    def list_users(self, *, actor: WorkspaceUser) -> tuple[ManagedUser, ...]: ...

    def create_user(
        self,
        *,
        actor: WorkspaceUser,
        username: str,
        display_name: str,
        system_role: SystemRole,
        password_hash: str,
        now: datetime,
        correlation_id: str | None,
    ) -> UserAdministrationResult: ...

    def update_user(
        self,
        *,
        actor: WorkspaceUser,
        user_id: str,
        display_name: str | None,
        system_role: SystemRole | None,
        is_active: bool | None,
        now: datetime,
        correlation_id: str | None,
    ) -> UserAdministrationResult: ...

    def reset_password(
        self,
        *,
        actor: WorkspaceUser,
        user_id: str,
        password_hash: str,
        now: datetime,
        correlation_id: str | None,
    ) -> UserAdministrationResult: ...

    def bootstrap_administrator(
        self,
        *,
        username: str,
        password_hash: str | None,
        now: datetime,
    ) -> None: ...


class PasswordService:
    """Argon2id password hashing with an explicit, reviewable cost profile."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=3,
            memory_cost=65_536,
            parallelism=1,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )
        self._dummy_hash = self._hasher.hash("liveclip-dummy-password-never-used")

    def hash(self, password: str) -> str:
        _validate_password(password)
        return self._hasher.hash(password)

    def verify(self, password_hash: str | None, password: str) -> bool:
        candidate = password_hash or self._dummy_hash
        try:
            verified = self._hasher.verify(candidate, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
        return bool(verified) and password_hash is not None


class AuthenticationService:
    def __init__(
        self,
        repository: IdentityRepository,
        *,
        password_service: PasswordService | None = None,
        session_ttl: timedelta = timedelta(hours=12),
        login_window_seconds: int = 900,
        login_max_attempts: int = 5,
        login_block_seconds: int = 900,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._passwords = password_service or PasswordService()
        self._session_ttl = session_ttl
        self._login_window_seconds = login_window_seconds
        self._login_max_attempts = login_max_attempts
        self._login_block_seconds = login_block_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    def login(
        self,
        *,
        username: str,
        password: str,
        correlation_id: str | None = None,
    ) -> SessionGrant:
        normalized = _normalize_username(username)
        identity_hash = _digest(normalized)
        now = self._clock()
        retry_after = self._repository.check_login_allowed(
            identity_hash=identity_hash,
            now=now,
        )
        if retry_after is not None:
            raise LoginRateLimited(retry_after)
        record = self._repository.find_auth_user(normalized)
        password_hash = (
            record.password_hash if record is not None and record.user.is_active else None
        )
        if not self._passwords.verify(password_hash, password):
            retry_after = self._repository.record_login_failure(
                identity_hash=identity_hash,
                now=now,
                window_seconds=self._login_window_seconds,
                maximum_attempts=self._login_max_attempts,
                block_seconds=self._login_block_seconds,
                correlation_id=correlation_id,
            )
            if retry_after is not None:
                raise LoginRateLimited(retry_after)
            raise AuthenticationFailed("username or password is invalid")
        if record is None:  # Defensive: verification cannot succeed against the dummy hash.
            raise AuthenticationFailed("username or password is invalid")
        raw_token = self._token_factory()
        if len(raw_token) < 32:
            raise RuntimeError("session token factory returned insufficient entropy")
        session = self._repository.create_session(
            user=record,
            token_hash=_digest(raw_token),
            created_at=now,
            expires_at=now + self._session_ttl,
            correlation_id=correlation_id,
        )
        return SessionGrant(
            raw_token=raw_token,
            csrf_token=self.csrf_token(raw_token),
            session=session,
        )

    def login_required(self) -> bool:
        return self._repository.password_login_required()

    def authenticate_session(self, raw_token: str) -> AuthenticatedSession:
        if not raw_token:
            raise AuthenticationFailed("session is invalid")
        session = self._repository.get_session(token_hash=_digest(raw_token), now=self._clock())
        if session is None:
            raise AuthenticationFailed("session is invalid")
        return session

    def require_csrf(self, raw_token: str, provided_token: str | None) -> None:
        if provided_token is None or not hmac.compare_digest(
            self.csrf_token(raw_token), provided_token
        ):
            raise AuthenticationFailed("CSRF validation failed")

    def logout(self, raw_token: str, *, correlation_id: str | None = None) -> None:
        self._repository.revoke_session(
            token_hash=_digest(raw_token),
            now=self._clock(),
            correlation_id=correlation_id,
        )

    @staticmethod
    def csrf_token(raw_token: str) -> str:
        return hmac.new(
            raw_token.encode("utf-8"),
            b"liveclip-csrf-v1",
            hashlib.sha256,
        ).hexdigest()


class UserAdministrationService:
    def __init__(
        self,
        repository: IdentityRepository,
        *,
        password_service: PasswordService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._passwords = password_service or PasswordService()
        self._clock = clock or (lambda: datetime.now(UTC))

    def list_users(self, actor: WorkspaceUser) -> tuple[ManagedUser, ...]:
        _require_administrator(actor)
        return self._repository.list_users(actor=actor)

    def create_user(
        self,
        *,
        actor: WorkspaceUser,
        username: str,
        display_name: str,
        system_role: SystemRole,
        password: str,
        correlation_id: str | None = None,
    ) -> UserAdministrationResult:
        _require_administrator(actor)
        return self._repository.create_user(
            actor=actor,
            username=_normalize_username(username),
            display_name=display_name.strip(),
            system_role=system_role,
            password_hash=self._passwords.hash(password),
            now=self._clock(),
            correlation_id=correlation_id,
        )

    def update_user(
        self,
        *,
        actor: WorkspaceUser,
        user_id: str,
        display_name: str | None = None,
        system_role: SystemRole | None = None,
        is_active: bool | None = None,
        correlation_id: str | None = None,
    ) -> UserAdministrationResult:
        _require_administrator(actor)
        normalized_name = display_name.strip() if display_name is not None else None
        if normalized_name == "":
            raise ValueError("display name cannot be empty")
        return self._repository.update_user(
            actor=actor,
            user_id=user_id,
            display_name=normalized_name,
            system_role=system_role,
            is_active=is_active,
            now=self._clock(),
            correlation_id=correlation_id,
        )

    def reset_password(
        self,
        *,
        actor: WorkspaceUser,
        user_id: str,
        password: str,
        correlation_id: str | None = None,
    ) -> UserAdministrationResult:
        _require_administrator(actor)
        return self._repository.reset_password(
            actor=actor,
            user_id=user_id,
            password_hash=self._passwords.hash(password),
            now=self._clock(),
            correlation_id=correlation_id,
        )

    def bootstrap(self, *, username: str, password: str | None) -> None:
        password_hash = self._passwords.hash(password) if password is not None else None
        self._repository.bootstrap_administrator(
            username=_normalize_username(username),
            password_hash=password_hash,
            now=self._clock(),
        )


def _require_administrator(actor: WorkspaceUser) -> None:
    if actor.system_role != "administrator":
        raise AdministrationDenied("system administrator permission is required")


def _validate_password(password: str) -> None:
    if not MIN_PASSWORD_CHARACTERS <= len(password) <= MAX_PASSWORD_CHARACTERS:
        raise ValueError(
            f"password must contain {MIN_PASSWORD_CHARACTERS} to "
            f"{MAX_PASSWORD_CHARACTERS} characters"
        )
    if password.isspace() or "\x00" in password:
        raise ValueError("password contains invalid characters")


def _normalize_username(username: str) -> str:
    return username.strip().lower()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
