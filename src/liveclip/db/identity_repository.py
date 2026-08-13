from __future__ import annotations

import math
from datetime import datetime, timedelta

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import IntegrityError

from liveclip.application.identity import (
    AuthenticatedSession,
    AuthUserRecord,
    IdentityConflict,
    ManagedUser,
)
from liveclip.application.workspace import SystemRole, WorkspaceUser
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.models import (
    AuditEventRow,
    AuthLoginAttemptRow,
    AuthSessionRow,
    WorkspaceUserRow,
)


class SqlAlchemyIdentityRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def find_auth_user(self, username: str) -> AuthUserRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(*_USER_COLUMNS).where(WorkspaceUserRow.username == username)
            ).mappings().one_or_none()
        return _auth_record(row) if row is not None else None

    def password_login_required(self) -> bool:
        with self._engine.connect() as connection:
            count = connection.scalar(
                select(func.count())
                .select_from(WorkspaceUserRow)
                .where(
                    WorkspaceUserRow.is_active.is_(True),
                    WorkspaceUserRow.password_hash.is_not(None),
                )
            )
        return bool(count)

    def check_login_allowed(self, *, identity_hash: str, now: datetime) -> int | None:
        with self._engine.connect() as connection:
            blocked_until = connection.scalar(
                select(AuthLoginAttemptRow.blocked_until).where(
                    AuthLoginAttemptRow.identity_hash == identity_hash
                )
            )
        if blocked_until is None or blocked_until <= now:
            return None
        return max(1, math.ceil((blocked_until - now).total_seconds()))

    def record_login_failure(
        self,
        *,
        identity_hash: str,
        now: datetime,
        window_seconds: int,
        maximum_attempts: int,
        block_seconds: int,
        correlation_id: str | None,
    ) -> int | None:
        with begin_immediate(self._engine) as connection:
            row = connection.execute(
                select(AuthLoginAttemptRow).where(
                    AuthLoginAttemptRow.identity_hash == identity_hash
                )
            ).scalar_one_or_none()
            if row is None or row.window_started_at + timedelta(seconds=window_seconds) <= now:
                failed_count = 1
                if row is None:
                    connection.execute(
                        insert(AuthLoginAttemptRow).values(
                            identity_hash=identity_hash,
                            failed_count=failed_count,
                            window_started_at=now,
                            blocked_until=None,
                            updated_at=now,
                        )
                    )
                else:
                    connection.execute(
                        update(AuthLoginAttemptRow)
                        .where(AuthLoginAttemptRow.identity_hash == identity_hash)
                        .values(
                            failed_count=failed_count,
                            window_started_at=now,
                            blocked_until=None,
                            updated_at=now,
                        )
                    )
            else:
                failed_count = int(row.failed_count) + 1
            blocked_until = (
                now + timedelta(seconds=block_seconds)
                if failed_count >= maximum_attempts
                else None
            )
            if row is not None and row.window_started_at + timedelta(seconds=window_seconds) > now:
                connection.execute(
                    update(AuthLoginAttemptRow)
                    .where(AuthLoginAttemptRow.identity_hash == identity_hash)
                    .values(
                        failed_count=failed_count,
                        blocked_until=blocked_until,
                        updated_at=now,
                    )
                )
            _audit(
                connection,
                actor=None,
                action="auth.login_failed",
                target_type="login_identity",
                target_id=identity_hash[:16],
                before=None,
                after={"rate_limited": blocked_until is not None},
                correlation_id=correlation_id,
                now=now,
            )
        if blocked_until is None:
            return None
        return max(1, math.ceil((blocked_until - now).total_seconds()))

    def create_session(
        self,
        *,
        user: AuthUserRecord,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
        correlation_id: str | None,
    ) -> AuthenticatedSession:
        with begin_immediate(self._engine) as connection:
            current = connection.execute(
                select(*_USER_COLUMNS).where(WorkspaceUserRow.id == user.user.user_id)
            ).mappings().one_or_none()
            if (
                current is None
                or not current.is_active
                or current.auth_version != user.auth_version
                or current.password_hash is None
            ):
                raise IdentityConflict("account changed during authentication")
            session_id = new_id()
            connection.execute(
                insert(AuthSessionRow).values(
                    id=session_id,
                    user_id=current.id,
                    token_hash=token_hash,
                    user_auth_version=current.auth_version,
                    created_at=created_at,
                    last_seen_at=created_at,
                    expires_at=expires_at,
                    revoked_at=None,
                )
            )
            connection.execute(
                update(WorkspaceUserRow)
                .where(WorkspaceUserRow.id == current.id)
                .values(last_login_at=created_at, updated_at=created_at)
            )
            connection.execute(
                delete(AuthLoginAttemptRow).where(
                    AuthLoginAttemptRow.identity_hash == _sha256(current.username)
                )
            )
            workspace_user = _managed_user(current).as_workspace_user()
            _audit(
                connection,
                actor=workspace_user,
                action="auth.login_succeeded",
                target_type="session",
                target_id=session_id,
                before=None,
                after={"expires_at": expires_at.isoformat()},
                correlation_id=correlation_id,
                now=created_at,
            )
        return AuthenticatedSession(
            session_id=session_id,
            user=workspace_user,
            expires_at=expires_at,
            caller_scope=f"session:{session_id}",
        )

    def get_session(self, *, token_hash: str, now: datetime) -> AuthenticatedSession | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(
                    AuthSessionRow.id,
                    AuthSessionRow.expires_at,
                    AuthSessionRow.last_seen_at,
                    AuthSessionRow.user_auth_version,
                    WorkspaceUserRow.id.label("user_id"),
                    WorkspaceUserRow.username,
                    WorkspaceUserRow.display_name,
                    WorkspaceUserRow.system_role,
                    WorkspaceUserRow.auth_version,
                    WorkspaceUserRow.is_active,
                )
                .join(WorkspaceUserRow, WorkspaceUserRow.id == AuthSessionRow.user_id)
                .where(
                    AuthSessionRow.token_hash == token_hash,
                    AuthSessionRow.revoked_at.is_(None),
                    AuthSessionRow.expires_at > now,
                )
            ).one_or_none()
        if (
            row is None
            or not bool(row.is_active)
            or int(row.user_auth_version) != int(row.auth_version)
        ):
            return None
        if row.last_seen_at + timedelta(minutes=5) <= now:
            with begin_immediate(self._engine) as connection:
                connection.execute(
                    update(AuthSessionRow)
                    .where(
                        AuthSessionRow.id == row.id,
                        AuthSessionRow.revoked_at.is_(None),
                    )
                    .values(last_seen_at=now)
                )
        user = WorkspaceUser(
            user_id=str(row.user_id),
            username=str(row.username),
            display_name=str(row.display_name),
            system_role=str(row.system_role),  # type: ignore[arg-type]
        )
        return AuthenticatedSession(
            session_id=str(row.id),
            user=user,
            expires_at=row.expires_at,
            caller_scope=f"session:{row.id}",
        )

    def revoke_session(
        self,
        *,
        token_hash: str,
        now: datetime,
        correlation_id: str | None,
    ) -> None:
        with begin_immediate(self._engine) as connection:
            row = connection.execute(
                select(
                    AuthSessionRow.id,
                    WorkspaceUserRow.id.label("user_id"),
                    WorkspaceUserRow.username,
                    WorkspaceUserRow.display_name,
                    WorkspaceUserRow.system_role,
                )
                .join(WorkspaceUserRow, WorkspaceUserRow.id == AuthSessionRow.user_id)
                .where(AuthSessionRow.token_hash == token_hash)
            ).one_or_none()
            if row is None:
                return
            connection.execute(
                update(AuthSessionRow)
                .where(AuthSessionRow.id == row.id, AuthSessionRow.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            _audit(
                connection,
                actor=WorkspaceUser(
                    user_id=str(row.user_id),
                    username=str(row.username),
                    display_name=str(row.display_name),
                    system_role=str(row.system_role),  # type: ignore[arg-type]
                ),
                action="auth.logout",
                target_type="session",
                target_id=str(row.id),
                before={"active": True},
                after={"active": False},
                correlation_id=correlation_id,
                now=now,
            )

    def list_users(self) -> tuple[ManagedUser, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(*_USER_COLUMNS).order_by(
                    WorkspaceUserRow.display_name,
                    WorkspaceUserRow.username,
                )
            ).mappings()
            return tuple(_managed_user(row) for row in rows)

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
    ) -> ManagedUser:
        if not display_name:
            raise ValueError("display name cannot be empty")
        user_id = new_id()
        try:
            with begin_immediate(self._engine) as connection:
                connection.execute(
                    insert(WorkspaceUserRow).values(
                        id=user_id,
                        username=username,
                        display_name=display_name,
                        system_role=system_role,
                        password_hash=password_hash,
                        auth_version=0,
                        last_login_at=None,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                )
                created = connection.execute(
                    select(*_USER_COLUMNS).where(WorkspaceUserRow.id == user_id)
                ).mappings().one()
                result = _managed_user(created)
                _audit(
                    connection,
                    actor=actor,
                    action="user.created",
                    target_type="user",
                    target_id=user_id,
                    before=None,
                    after=_audit_user(result),
                    correlation_id=correlation_id,
                    now=now,
                )
        except IntegrityError as exc:
            raise IdentityConflict("username already exists") from exc
        return result

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
    ) -> ManagedUser:
        with begin_immediate(self._engine) as connection:
            target = connection.execute(
                select(*_USER_COLUMNS).where(WorkspaceUserRow.id == user_id)
            ).mappings().one_or_none()
            if target is None:
                raise LookupError("user does not exist")
            before = _managed_user(target)
            next_role = system_role if system_role is not None else before.system_role
            next_active = is_active if is_active is not None else before.is_active
            if before.system_role == "administrator" and before.is_active and (
                next_role != "administrator" or not next_active
            ):
                other_admins = connection.scalar(
                    select(func.count())
                    .select_from(WorkspaceUserRow)
                    .where(
                        WorkspaceUserRow.system_role == "administrator",
                        WorkspaceUserRow.is_active.is_(True),
                        WorkspaceUserRow.id != user_id,
                    )
                )
                if not other_admins:
                    raise IdentityConflict("at least one active administrator is required")
            values: dict[str, object] = {"updated_at": now}
            if display_name is not None:
                values["display_name"] = display_name
            if system_role is not None:
                values["system_role"] = system_role
            if is_active is not None:
                values["is_active"] = is_active
            security_changed = (
                (system_role is not None and system_role != before.system_role)
                or (is_active is not None and is_active != before.is_active)
            )
            if security_changed:
                values["auth_version"] = WorkspaceUserRow.auth_version + 1
            connection.execute(
                update(WorkspaceUserRow).where(WorkspaceUserRow.id == user_id).values(**values)
            )
            if security_changed:
                connection.execute(
                    update(AuthSessionRow)
                    .where(AuthSessionRow.user_id == user_id, AuthSessionRow.revoked_at.is_(None))
                    .values(revoked_at=now)
                )
            current = connection.execute(
                select(*_USER_COLUMNS).where(WorkspaceUserRow.id == user_id)
            ).mappings().one()
            result = _managed_user(current)
            _audit(
                connection,
                actor=actor,
                action="user.updated",
                target_type="user",
                target_id=user_id,
                before=_audit_user(before),
                after=_audit_user(result),
                correlation_id=correlation_id,
                now=now,
            )
        return result

    def reset_password(
        self,
        *,
        actor: WorkspaceUser,
        user_id: str,
        password_hash: str,
        now: datetime,
        correlation_id: str | None,
    ) -> ManagedUser:
        with begin_immediate(self._engine) as connection:
            target = connection.execute(
                select(*_USER_COLUMNS).where(WorkspaceUserRow.id == user_id)
            ).mappings().one_or_none()
            if target is None:
                raise LookupError("user does not exist")
            connection.execute(
                update(WorkspaceUserRow)
                .where(WorkspaceUserRow.id == user_id)
                .values(
                    password_hash=password_hash,
                    auth_version=WorkspaceUserRow.auth_version + 1,
                    updated_at=now,
                )
            )
            connection.execute(
                update(AuthSessionRow)
                .where(AuthSessionRow.user_id == user_id, AuthSessionRow.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            current = connection.execute(
                select(*_USER_COLUMNS).where(WorkspaceUserRow.id == user_id)
            ).mappings().one()
            result = _managed_user(current)
            _audit(
                connection,
                actor=actor,
                action="user.password_reset",
                target_type="user",
                target_id=user_id,
                before=None,
                after={"sessions_revoked": True},
                correlation_id=correlation_id,
                now=now,
            )
        return result

    def bootstrap_administrator(
        self,
        *,
        username: str,
        password_hash: str | None,
        now: datetime,
    ) -> None:
        with begin_immediate(self._engine) as connection:
            password_admins = int(
                connection.scalar(
                    select(func.count())
                    .select_from(WorkspaceUserRow)
                    .where(
                        WorkspaceUserRow.system_role == "administrator",
                        WorkspaceUserRow.is_active.is_(True),
                        WorkspaceUserRow.password_hash.is_not(None),
                    )
                )
                or 0
            )
            active_admins = int(
                connection.scalar(
                    select(func.count())
                    .select_from(WorkspaceUserRow)
                    .where(
                        WorkspaceUserRow.system_role == "administrator",
                        WorkspaceUserRow.is_active.is_(True),
                    )
                )
                or 0
            )
            target = connection.execute(
                select(*_USER_COLUMNS).where(WorkspaceUserRow.username == username)
            ).mappings().one_or_none()
            if target is None:
                connection.execute(
                    insert(WorkspaceUserRow).values(
                        id=new_id(),
                        username=username,
                        display_name="本机管理员",
                        system_role=(
                            "administrator"
                            if active_admins == 0
                            or (password_hash is not None and password_admins == 0)
                            else "member"
                        ),
                        password_hash=password_hash,
                        auth_version=0,
                        last_login_at=None,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                )
                return
            values: dict[str, object] = {}
            needs_accessible_admin = active_admins == 0 or (
                password_hash is not None and password_admins == 0
            )
            if needs_accessible_admin:
                values.update(system_role="administrator", is_active=True)
            if password_hash is not None and target.password_hash is None:
                values["password_hash"] = password_hash
            if values:
                values["updated_at"] = now
                connection.execute(
                    update(WorkspaceUserRow)
                    .where(WorkspaceUserRow.id == target.id)
                    .values(**values)
                )


_USER_COLUMNS = (
    WorkspaceUserRow.id,
    WorkspaceUserRow.username,
    WorkspaceUserRow.display_name,
    WorkspaceUserRow.system_role,
    WorkspaceUserRow.password_hash,
    WorkspaceUserRow.auth_version,
    WorkspaceUserRow.last_login_at,
    WorkspaceUserRow.is_active,
    WorkspaceUserRow.created_at,
    WorkspaceUserRow.updated_at,
)


def _auth_record(row: RowMapping) -> AuthUserRecord:
    return AuthUserRecord(
        user=_managed_user(row),
        password_hash=row.password_hash,
        auth_version=row.auth_version,
    )


def _managed_user(row: RowMapping) -> ManagedUser:
    role = str(row.system_role)
    if role not in {"administrator", "member"}:
        raise RuntimeError("workspace user system role is invalid")
    return ManagedUser(
        user_id=row.id,
        username=row.username,
        display_name=row.display_name,
        system_role=role,  # type: ignore[arg-type]
        is_active=row.is_active,
        password_configured=row.password_hash is not None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_login_at=row.last_login_at,
    )


def _audit_user(user: ManagedUser) -> dict[str, object]:
    return {
        "username": user.username,
        "display_name": user.display_name,
        "system_role": user.system_role,
        "is_active": user.is_active,
        "password_configured": user.password_configured,
    }


def _audit(
    connection: Connection,
    *,
    actor: WorkspaceUser | None,
    action: str,
    target_type: str,
    target_id: str | None,
    before: dict[str, object] | None,
    after: dict[str, object] | None,
    correlation_id: str | None,
    now: datetime,
) -> None:
    connection.execute(
        insert(AuditEventRow).values(
            id=new_id(),
            actor_user_id=actor.user_id if actor else None,
            actor_username=actor.username if actor else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            project_id=None,
            before_json=before,
            after_json=after,
            correlation_id=correlation_id,
            created_at=now,
        )
    )


def _sha256(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
