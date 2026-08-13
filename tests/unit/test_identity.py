from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from liveclip.application.identity import (
    AuthenticatedSession,
    AuthenticationFailed,
    AuthenticationService,
    AuthUserRecord,
    ManagedUser,
    PasswordService,
)


def test_passwords_are_argon2id_hashed_and_never_equal_plaintext() -> None:
    service = PasswordService()
    password = "safe local password 2026"
    encoded = service.hash(password)

    assert encoded.startswith("$argon2id$")
    assert password not in encoded
    assert service.verify(encoded, password)
    assert not service.verify(encoded, "wrong local password")
    assert not service.verify(None, password)


@pytest.mark.parametrize("password", ["short", " " * 12, "valid-length\x00bad"])
def test_password_policy_rejects_unsafe_values(password: str) -> None:
    with pytest.raises(ValueError):
        PasswordService().hash(password)


class FakeIdentityRepository:
    def __init__(self, record: AuthUserRecord) -> None:
        self.record = record
        self.token_hash: str | None = None
        self.revoked = False

    def password_login_required(self) -> bool:
        return True

    def check_login_allowed(self, **_: object) -> int | None:
        return None

    def find_auth_user(self, username: str) -> AuthUserRecord | None:
        return self.record if username == self.record.user.username else None

    def record_login_failure(self, **_: object) -> int | None:
        return None

    def create_session(
        self,
        *,
        user: AuthUserRecord,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
        correlation_id: str | None,
    ) -> AuthenticatedSession:
        del correlation_id
        self.token_hash = token_hash
        return AuthenticatedSession(
            session_id="session-1",
            user=user.user.as_workspace_user(),
            expires_at=expires_at,
            caller_scope="session:session-1",
        )

    def get_session(self, *, token_hash: str, now: datetime) -> AuthenticatedSession | None:
        del now
        if token_hash != self.token_hash or self.revoked:
            return None
        return AuthenticatedSession(
            session_id="session-1",
            user=self.record.user.as_workspace_user(),
            expires_at=datetime(2026, 8, 14, tzinfo=UTC),
            caller_scope="session:session-1",
        )

    def revoke_session(self, **_: object) -> None:
        self.revoked = True


def test_session_is_opaque_csrf_bound_and_revocable() -> None:
    passwords = PasswordService()
    instant = datetime(2026, 8, 13, tzinfo=UTC)
    repository = FakeIdentityRepository(
        AuthUserRecord(
            user=ManagedUser(
                user_id="u" * 32,
                username="admin",
                display_name="管理员",
                system_role="administrator",
                is_active=True,
                password_configured=True,
                created_at=instant,
                updated_at=instant,
                last_login_at=None,
            ),
            password_hash=passwords.hash("safe local password 2026"),
            auth_version=0,
        )
    )
    auth = AuthenticationService(
        repository,  # type: ignore[arg-type]
        password_service=passwords,
        session_ttl=timedelta(hours=1),
        clock=lambda: instant,
        token_factory=lambda: "opaque-session-token-with-more-than-32-characters",
    )

    grant = auth.login(username="ADMIN", password="safe local password 2026")
    assert repository.token_hash is not None
    assert grant.raw_token not in repository.token_hash
    assert auth.authenticate_session(grant.raw_token).user.username == "admin"
    auth.require_csrf(grant.raw_token, grant.csrf_token)
    with pytest.raises(AuthenticationFailed):
        auth.require_csrf(grant.raw_token, "wrong")
    auth.logout(grant.raw_token)
    with pytest.raises(AuthenticationFailed):
        auth.authenticate_session(grant.raw_token)
