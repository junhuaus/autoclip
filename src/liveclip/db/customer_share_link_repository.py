"""SQLite persistence for customer share links (Stage 19d). Only token hashes are stored."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import aliased

from liveclip.application.customer_share_links import (
    ShareAccessKind,
    ShareLinkConflict,
    ShareLinkNotFound,
    ShareLinkSnapshot,
    ShareLinkStatus,
    ShareTarget,
)
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.models import (
    AuditEventRow,
    CustomerDeliveryClipRow,
    CustomerDeliveryRow,
    CustomerShareLinkRow,
    ProjectRow,
    WorkspaceUserRow,
)
from liveclip.domain.project_lifecycle import ProjectLifecycle
from liveclip.domain.state_transitions import DeliveryStatus

_VIEWED = "customer_share_link.viewed"
_DOWNLOADED = "customer_share_link.downloaded"


class SqlAlchemyShareLinkRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_link(
        self,
        *,
        project_id: str,
        delivery_id: str,
        acting_user_id: str,
        token_sha256: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> ShareLinkSnapshot:
        with begin_immediate(self._engine) as connection:
            delivery = connection.execute(
                select(
                    CustomerDeliveryRow.status,
                    CustomerDeliveryRow.zip_asset_id,
                    CustomerDeliveryRow.manifest_asset_id,
                    CustomerDeliveryRow.version,
                ).where(
                    CustomerDeliveryRow.id == delivery_id,
                    CustomerDeliveryRow.project_id == project_id,
                )
            ).one_or_none()
            if delivery is None:
                raise ShareLinkNotFound("customer delivery does not exist")
            if (
                delivery.status != DeliveryStatus.SUCCEEDED.value
                or delivery.zip_asset_id is None
                or delivery.manifest_asset_id is None
            ):
                raise ShareLinkConflict("only a finished customer delivery can be shared")
            link_id = new_id()
            connection.execute(
                insert(CustomerShareLinkRow).values(
                    id=link_id,
                    delivery_id=delivery_id,
                    project_id=project_id,
                    token_sha256=token_sha256,
                    created_by=acting_user_id,
                    created_at=created_at,
                    expires_at=expires_at,
                )
            )
            _audit(
                connection,
                actor_user_id=acting_user_id,
                action="customer_share_link.created",
                link_id=link_id,
                project_id=project_id,
                after={
                    "delivery_version": f"v{int(delivery.version):03d}",
                    "expires_at": expires_at.isoformat(),
                },
                now=created_at,
            )
            return _snapshot(connection, link_id, now=created_at)

    def list_links(
        self, *, project_id: str, delivery_id: str, now: datetime
    ) -> tuple[ShareLinkSnapshot, ...]:
        with self._engine.connect() as connection:
            if (
                connection.scalar(
                    select(CustomerDeliveryRow.id).where(
                        CustomerDeliveryRow.id == delivery_id,
                        CustomerDeliveryRow.project_id == project_id,
                    )
                )
                is None
            ):
                raise ShareLinkNotFound("customer delivery does not exist")
            ids = connection.scalars(
                select(CustomerShareLinkRow.id)
                .where(CustomerShareLinkRow.delivery_id == delivery_id)
                .order_by(CustomerShareLinkRow.created_at.desc(), CustomerShareLinkRow.id)
            ).all()
            return tuple(_snapshot(connection, str(value), now=now) for value in ids)

    def revoke_link(
        self, *, project_id: str, link_id: str, acting_user_id: str, now: datetime
    ) -> ShareLinkSnapshot:
        with begin_immediate(self._engine) as connection:
            row = connection.execute(
                select(CustomerShareLinkRow.revoked_at).where(
                    CustomerShareLinkRow.id == link_id,
                    CustomerShareLinkRow.project_id == project_id,
                )
            ).one_or_none()
            if row is None:
                raise ShareLinkNotFound("share link does not exist")
            if row.revoked_at is None:
                connection.execute(
                    update(CustomerShareLinkRow)
                    .where(
                        CustomerShareLinkRow.id == link_id,
                        CustomerShareLinkRow.revoked_at.is_(None),
                    )
                    .values(revoked_at=now, revoked_by=acting_user_id)
                )
                _audit(
                    connection,
                    actor_user_id=acting_user_id,
                    action="customer_share_link.revoked",
                    link_id=link_id,
                    project_id=project_id,
                    after={"revoked_at": now.isoformat()},
                    now=now,
                )
            return _snapshot(connection, link_id, now=now)

    def resolve(self, *, token_sha256: str, now: datetime) -> ShareTarget | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(
                    CustomerShareLinkRow.id,
                    CustomerShareLinkRow.expires_at,
                    CustomerDeliveryRow.id.label("delivery_id"),
                    CustomerDeliveryRow.project_id,
                    CustomerDeliveryRow.manifest_asset_id,
                    CustomerDeliveryRow.zip_asset_id,
                    CustomerDeliveryRow.title,
                    CustomerDeliveryRow.version,
                )
                .join(
                    CustomerDeliveryRow, CustomerDeliveryRow.id == CustomerShareLinkRow.delivery_id
                )
                .join(ProjectRow, ProjectRow.id == CustomerDeliveryRow.project_id)
                .where(
                    CustomerShareLinkRow.token_sha256 == token_sha256,
                    CustomerShareLinkRow.revoked_at.is_(None),
                    CustomerShareLinkRow.expires_at > now,
                    CustomerShareLinkRow.project_id == CustomerDeliveryRow.project_id,
                    CustomerDeliveryRow.status == DeliveryStatus.SUCCEEDED.value,
                    CustomerDeliveryRow.zip_asset_id.is_not(None),
                    CustomerDeliveryRow.manifest_asset_id.is_not(None),
                    ProjectRow.lifecycle != ProjectLifecycle.ARCHIVED.value,
                )
            ).one_or_none()
            if row is None:
                return None
            clips = connection.execute(
                select(
                    CustomerDeliveryClipRow.ordinal,
                    CustomerDeliveryClipRow.video_asset_id,
                    CustomerDeliveryClipRow.subtitle_asset_id,
                    CustomerDeliveryClipRow.title,
                ).where(CustomerDeliveryClipRow.delivery_id == row.delivery_id)
            ).all()
        return ShareTarget(
            link_id=str(row.id),
            delivery_id=str(row.delivery_id),
            project_id=str(row.project_id),
            expires_at=row.expires_at,
            manifest_asset_id=str(row.manifest_asset_id),
            zip_asset_id=str(row.zip_asset_id),
            title=str(row.title),
            delivery_version=f"v{int(row.version):03d}",
            clip_assets={
                int(clip.ordinal): (
                    str(clip.video_asset_id),
                    str(clip.subtitle_asset_id),
                    str(clip.title),
                )
                for clip in clips
            },
        )

    def record_access(
        self, *, target: ShareTarget, kind: ShareAccessKind, detail: str, now: datetime
    ) -> None:
        with begin_immediate(self._engine) as connection:
            connection.execute(
                insert(AuditEventRow).values(
                    id=new_id(),
                    actor_user_id=None,
                    actor_username=None,
                    action=_VIEWED if kind == "viewed" else _DOWNLOADED,
                    target_type="customer_share_link",
                    target_id=target.link_id,
                    project_id=target.project_id,
                    before_json=None,
                    after_json={"detail": detail[:40]},
                    correlation_id=None,
                    created_at=now,
                )
            )


def _snapshot(connection: Connection, link_id: str, *, now: datetime) -> ShareLinkSnapshot:
    creator = aliased(WorkspaceUserRow)
    revoker = aliased(WorkspaceUserRow)
    row = connection.execute(
        select(
            CustomerShareLinkRow.id,
            CustomerShareLinkRow.delivery_id,
            CustomerShareLinkRow.project_id,
            CustomerShareLinkRow.created_at,
            CustomerShareLinkRow.expires_at,
            CustomerShareLinkRow.revoked_at,
            CustomerDeliveryRow.version,
            creator.display_name.label("created_by"),
            revoker.display_name.label("revoked_by"),
        )
        .join(CustomerDeliveryRow, CustomerDeliveryRow.id == CustomerShareLinkRow.delivery_id)
        .join(creator, creator.id == CustomerShareLinkRow.created_by)
        .outerjoin(revoker, revoker.id == CustomerShareLinkRow.revoked_by)
        .where(CustomerShareLinkRow.id == link_id)
    ).one()
    counts: dict[str, Any] = {
        str(value.action): value
        for value in connection.execute(
            select(
                AuditEventRow.action,
                func.count(AuditEventRow.id).label("count"),
                func.max(AuditEventRow.created_at).label("last"),
            )
            .where(
                AuditEventRow.target_type == "customer_share_link",
                AuditEventRow.target_id == link_id,
                AuditEventRow.action.in_((_VIEWED, _DOWNLOADED)),
            )
            .group_by(AuditEventRow.action)
        )
    }
    lasts = [value.last for value in counts.values() if value.last is not None]
    status: ShareLinkStatus = (
        "revoked"
        if row.revoked_at is not None
        else "expired"
        if _aware(row.expires_at) <= now
        else "active"
    )
    return ShareLinkSnapshot(
        link_id=str(row.id),
        delivery_id=str(row.delivery_id),
        project_id=str(row.project_id),
        delivery_version=f"v{int(row.version):03d}",
        created_by=str(row.created_by),
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        revoked_by=str(row.revoked_by) if row.revoked_by is not None else None,
        status=status,
        view_count=int(counts[_VIEWED].count) if _VIEWED in counts else 0,
        download_count=int(counts[_DOWNLOADED].count) if _DOWNLOADED in counts else 0,
        last_accessed_at=_aware(max(lasts)) if lasts else None,
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _audit(
    connection: Connection,
    *,
    actor_user_id: str,
    action: str,
    link_id: str,
    project_id: str,
    after: dict[str, object],
    now: datetime,
) -> None:
    username = connection.scalar(
        select(WorkspaceUserRow.username).where(WorkspaceUserRow.id == actor_user_id)
    )
    connection.execute(
        insert(AuditEventRow).values(
            id=new_id(),
            actor_user_id=actor_user_id,
            actor_username=str(username) if username is not None else None,
            action=action,
            target_type="customer_share_link",
            target_id=link_id,
            project_id=project_id,
            before_json=None,
            after_json=after,
            correlation_id=None,
            created_at=now,
        )
    )


__all__ = ["SqlAlchemyShareLinkRepository"]
