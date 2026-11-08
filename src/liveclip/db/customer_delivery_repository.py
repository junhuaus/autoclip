"""SQLite persistence for immutable customer deliveries (Stage 19c)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, insert, select, update
from sqlalchemy.engine import Connection, Engine

from liveclip.application.customer_deliveries import (
    CUSTOMER_DELIVERY_MANIFEST_KIND,
    CUSTOMER_DELIVERY_ZIP_KIND,
    CustomerDeliveryConflict,
    CustomerDeliveryCreate,
    CustomerDeliveryNotFound,
    CustomerDeliveryPersistence,
    CustomerDeliverySnapshot,
    CustomerDeliveryWork,
    CustomerDeliveryWorkClip,
)
from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import LeaseIdentity
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.idempotency import load_idempotent_resource, record_idempotent_resource
from liveclip.db.models import (
    AssetRow,
    AuditEventRow,
    CustomerDeliveryClipRow,
    CustomerDeliveryRow,
    DualProfileClipDecisionRow,
    DualProfileImportClipRow,
    DualProfileImportRow,
    TaskAttemptRow,
    TaskRow,
    WorkspaceUserRow,
)
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.customer_delivery import (
    ClipDecision,
    ClipDecisionAction,
    CustomerText,
    ImportedClipStatus,
    effective_customer_text,
    is_deliverable,
    is_selected_for_delivery,
    latest_approval,
)
from liveclip.domain.state_transitions import (
    AssetStatus,
    AttemptOutcome,
    DeliveryStatus,
    ResourceClass,
    TaskKind,
    TaskStatus,
    transition_delivery,
    transition_task,
)

_PROFILE_ORDER = {ClipProfile.SHORT_HIGHLIGHT: 0, ClipProfile.MINI_LESSON: 1}
_SNAPSHOT_SCHEMA = "liveclip.customer-delivery-snapshot.v1"


class SqlAlchemyCustomerDeliveryRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def enqueue_customer_delivery(
        self,
        project_id: str,
        *,
        acting_user_id: str,
        request: CustomerDeliveryCreate,
        max_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> CustomerDeliverySnapshot:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            replay_id = load_idempotent_resource(
                connection, idempotency, resource_type="customer_delivery"
            )
            if replay_id is not None:
                return _snapshot(connection, replay_id)
            import_id = connection.scalar(
                select(DualProfileImportRow.id).where(DualProfileImportRow.project_id == project_id)
            )
            if import_id is None:
                raise CustomerDeliveryNotFound("project has no dual-profile import")
            username = _active_username(connection, acting_user_id)
            selected = _selected_clips(connection, project_id)
            if request.expected_clip_ids is not None:
                expected = set(request.expected_clip_ids)
                eligible = {
                    clip["id"]
                    for clip in _clip_states(connection, project_id)
                    if clip["deliverable"]
                }
                if not expected <= eligible:
                    raise CustomerDeliveryConflict("a requested clip is not deliverable")
                if expected != {clip["id"] for clip in selected}:
                    raise CustomerDeliveryConflict(
                        "the delivery selection changed; reload and try again"
                    )
            if not selected:
                raise CustomerDeliveryConflict("no deliverable clip is selected for delivery")
            version = (
                int(
                    connection.scalar(
                        select(func.max(CustomerDeliveryRow.version)).where(
                            CustomerDeliveryRow.project_id == project_id
                        )
                    )
                    or 0
                )
                + 1
            )
            if version > 999:
                raise CustomerDeliveryConflict("customer delivery version space is exhausted")
            delivery_id = new_id()
            task_id = new_id()
            fingerprint = _snapshot_fingerprint(
                project_id=project_id,
                import_id=str(import_id),
                version=version,
                title=request.title,
                created_at=now,
                clips=selected,
            )
            connection.execute(
                insert(TaskRow).values(
                    id=task_id,
                    kind=TaskKind.DELIVERY.value,
                    target_id=delivery_id,
                    operation_key=f"customer-delivery:{delivery_id}",
                    input_fingerprint=fingerprint,
                    resource_class=ResourceClass.HEAVY.value,
                    pipeline_run_id=None,
                    status=TaskStatus.QUEUED.value,
                    priority=650,
                    not_before=now,
                    attempt_count=0,
                    retry_count=0,
                    manual_retry_count=0,
                    max_retries=max_retries,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(CustomerDeliveryRow).values(
                    id=delivery_id,
                    project_id=project_id,
                    import_id=str(import_id),
                    task_id=task_id,
                    version=version,
                    title=request.title,
                    status=DeliveryStatus.QUEUED.value,
                    snapshot_fingerprint=fingerprint,
                    directory_relative_path=f"customer-deliveries/v{version:03d}",
                    created_by=acting_user_id,
                    created_at=now,
                )
            )
            for ordinal, clip in enumerate(selected, start=1):
                connection.execute(
                    insert(CustomerDeliveryClipRow).values(
                        id=new_id(),
                        delivery_id=delivery_id,
                        import_clip_id=clip["id"],
                        approval_decision_id=clip["approval_decision_id"],
                        ordinal=ordinal,
                        profile=clip["profile"].value,
                        title=clip["text"].title,
                        hook=clip["text"].hook,
                        summary=clip["text"].summary,
                        duration_ms=clip["duration_ms"],
                        video_asset_id=clip["video_asset_id"],
                        subtitle_asset_id=clip["subtitle_asset_id"],
                        video_sha256=clip["video_sha256"],
                        subtitle_sha256=clip["subtitle_sha256"],
                    )
                )
            record_idempotent_resource(
                connection,
                idempotency,
                resource_type="customer_delivery",
                resource_id=delivery_id,
            )
            _audit(
                connection,
                actor_user_id=acting_user_id,
                actor_username=username,
                action="customer_delivery.queued",
                delivery_id=delivery_id,
                project_id=project_id,
                after={"version": f"v{version:03d}", "clip_count": len(selected)},
                now=now,
            )
            return _snapshot(connection, delivery_id)

    def list_customer_deliveries(self, project_id: str) -> tuple[CustomerDeliverySnapshot, ...]:
        with self._engine.connect() as connection:
            ids = connection.scalars(
                select(CustomerDeliveryRow.id)
                .where(CustomerDeliveryRow.project_id == project_id)
                .order_by(CustomerDeliveryRow.version.desc())
            ).all()
            return tuple(_snapshot(connection, str(value)) for value in ids)

    def get_customer_delivery(self, delivery_id: str) -> CustomerDeliverySnapshot:
        with self._engine.connect() as connection:
            return _snapshot(connection, delivery_id)

    def is_customer_delivery_task(self, task_id: str, target_id: str) -> bool:
        with self._engine.connect() as connection:
            return (
                connection.scalar(
                    select(CustomerDeliveryRow.id).where(
                        CustomerDeliveryRow.id == target_id,
                        CustomerDeliveryRow.task_id == task_id,
                    )
                )
                is not None
            )

    def start_customer_delivery(self, lease: LeaseIdentity) -> CustomerDeliveryWork:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            row = _leased_row(connection, lease, now=now)
            if row is None:
                raise CustomerDeliveryConflict("customer delivery task lost its lease")
            current = DeliveryStatus(str(row.status))
            if current is DeliveryStatus.QUEUED:
                transition_delivery(current, DeliveryStatus.CREATING)
                connection.execute(
                    update(CustomerDeliveryRow)
                    .where(
                        CustomerDeliveryRow.id == row.delivery_id,
                        CustomerDeliveryRow.status == DeliveryStatus.QUEUED.value,
                    )
                    .values(
                        status=DeliveryStatus.CREATING.value,
                        error_code=None,
                        safe_error_message=None,
                    )
                )
            elif current is not DeliveryStatus.CREATING:
                raise CustomerDeliveryConflict("customer delivery is not buildable")
            return _work(connection, row)

    def assert_customer_delivery_current(
        self, lease: LeaseIdentity, work: CustomerDeliveryWork
    ) -> None:
        with self._engine.connect() as connection:
            row = _leased_row(connection, lease, now=datetime.now(UTC))
        if (
            row is None
            or str(row.delivery_id) != work.delivery_id
            or str(row.input_fingerprint) != work.snapshot_fingerprint
        ):
            raise CustomerDeliveryConflict("customer delivery task is no longer publishable")

    def complete_customer_delivery(
        self,
        lease: LeaseIdentity,
        work: CustomerDeliveryWork,
        persistence: CustomerDeliveryPersistence,
    ) -> bool:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            row = _leased_row(connection, lease, now=now)
            if (
                row is None
                or str(row.delivery_id) != work.delivery_id
                or str(row.input_fingerprint) != work.snapshot_fingerprint
            ):
                return False
            transition_delivery(DeliveryStatus(str(row.status)), DeliveryStatus.SUCCEEDED)
            attempt_id = connection.scalar(
                select(TaskAttemptRow.id).where(
                    TaskAttemptRow.task_id == lease.task_id,
                    TaskAttemptRow.lease_token == lease.lease_token,
                    TaskAttemptRow.outcome == AttemptOutcome.RUNNING.value,
                )
            )
            if attempt_id is None:
                return False
            asset_ids: dict[str, str] = {}
            for kind, relative_path, mime, sha256, size in (
                (
                    CUSTOMER_DELIVERY_MANIFEST_KIND,
                    persistence.manifest_relative_path,
                    "application/json",
                    persistence.manifest_sha256,
                    persistence.manifest_size_bytes,
                ),
                (
                    CUSTOMER_DELIVERY_ZIP_KIND,
                    persistence.zip_relative_path,
                    "application/zip",
                    persistence.zip_sha256,
                    persistence.zip_size_bytes,
                ),
            ):
                asset_id = new_id()
                connection.execute(
                    insert(AssetRow).values(
                        id=asset_id,
                        project_id=work.project_id,
                        producer_attempt_id=str(attempt_id),
                        status=AssetStatus.COMMITTED.value,
                        kind=kind,
                        relative_path=relative_path,
                        mime_type=mime,
                        input_fingerprint=work.snapshot_fingerprint,
                        expected_sha256=sha256,
                        sha256=sha256,
                        size_bytes=size,
                        validation_json={
                            "schema_version": "liveclip.customer-delivery.v1",
                            "delivery_version": work.delivery_version,
                            "clip_count": len(work.clips),
                        },
                        created_at=now,
                        committed_at=now,
                    )
                )
                asset_ids[kind] = asset_id
            connection.execute(
                update(CustomerDeliveryRow)
                .where(
                    CustomerDeliveryRow.id == work.delivery_id,
                    CustomerDeliveryRow.status == DeliveryStatus.CREATING.value,
                )
                .values(
                    status=DeliveryStatus.SUCCEEDED.value,
                    directory_relative_path=persistence.directory_relative_path,
                    manifest_asset_id=asset_ids[CUSTOMER_DELIVERY_MANIFEST_KIND],
                    zip_asset_id=asset_ids[CUSTOMER_DELIVERY_ZIP_KIND],
                    error_code=None,
                    safe_error_message=None,
                    completed_at=now,
                )
            )
            transition_task(TaskStatus.RUNNING, TaskStatus.SUCCEEDED)
            connection.execute(
                update(TaskRow)
                .where(
                    TaskRow.id == lease.task_id,
                    TaskRow.status == TaskStatus.RUNNING.value,
                    TaskRow.worker_id == lease.worker_id,
                    TaskRow.lease_token == lease.lease_token,
                )
                .values(
                    status=TaskStatus.SUCCEEDED.value,
                    worker_id=None,
                    lease_token=None,
                    heartbeat_at=None,
                    lease_expires_at=None,
                    completed_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                update(TaskAttemptRow)
                .where(TaskAttemptRow.id == str(attempt_id))
                .values(outcome=AttemptOutcome.SUCCEEDED.value, finished_at=now)
            )
            _audit(
                connection,
                actor_user_id=str(row.created_by),
                actor_username=None,
                action="customer_delivery.succeeded",
                delivery_id=work.delivery_id,
                project_id=work.project_id,
                after={"version": work.delivery_version, "clip_count": len(work.clips)},
                now=now,
            )
            return True


def _active_username(connection: Connection, user_id: str) -> str:
    username = connection.scalar(
        select(WorkspaceUserRow.username).where(
            WorkspaceUserRow.id == user_id, WorkspaceUserRow.is_active.is_(True)
        )
    )
    if username is None:
        raise CustomerDeliveryConflict("acting workspace user does not exist or is inactive")
    return str(username)


def _clip_states(connection: Connection, project_id: str) -> list[dict[str, Any]]:
    video = AssetRow.__table__.alias("video_asset")
    subtitle = AssetRow.__table__.alias("subtitle_asset")
    rows = connection.execute(
        select(
            DualProfileImportClipRow.id,
            DualProfileImportClipRow.candidate_id,
            DualProfileImportClipRow.profile,
            DualProfileImportClipRow.routed_status,
            DualProfileImportClipRow.start_ms,
            DualProfileImportClipRow.duration_ms,
            DualProfileImportClipRow.title,
            DualProfileImportClipRow.hook,
            DualProfileImportClipRow.summary,
            DualProfileImportClipRow.video_asset_id,
            DualProfileImportClipRow.subtitle_asset_id,
            video.c.sha256.label("video_sha256"),
            subtitle.c.sha256.label("subtitle_sha256"),
        )
        .join(video, video.c.id == DualProfileImportClipRow.video_asset_id)
        .join(subtitle, subtitle.c.id == DualProfileImportClipRow.subtitle_asset_id)
        .where(
            DualProfileImportClipRow.project_id == project_id,
            video.c.status == AssetStatus.COMMITTED.value,
            subtitle.c.status == AssetStatus.COMMITTED.value,
        )
    ).all()
    decisions = connection.execute(
        select(
            DualProfileClipDecisionRow.id,
            DualProfileClipDecisionRow.import_clip_id,
            DualProfileClipDecisionRow.sequence,
            DualProfileClipDecisionRow.action,
            DualProfileClipDecisionRow.title_override,
            DualProfileClipDecisionRow.hook_override,
            DualProfileClipDecisionRow.summary_override,
        )
        .where(DualProfileClipDecisionRow.project_id == project_id)
        .order_by(DualProfileClipDecisionRow.sequence)
    ).all()
    by_clip: dict[str, list[tuple[str, ClipDecision]]] = {}
    for value in decisions:
        by_clip.setdefault(str(value.import_clip_id), []).append(
            (
                str(value.id),
                ClipDecision(
                    sequence=int(value.sequence),
                    action=ClipDecisionAction(str(value.action)),
                    title_override=value.title_override,
                    hook_override=value.hook_override,
                    summary_override=value.summary_override,
                ),
            )
        )
    states: list[dict[str, Any]] = []
    for row in rows:
        history = by_clip.get(str(row.id), [])
        clip_decisions = tuple(decision for _, decision in history)
        status = ImportedClipStatus(str(row.routed_status))
        approval = latest_approval(clip_decisions)
        approval_id = next(
            (
                decision_id
                for decision_id, decision in history
                if approval is not None and decision.sequence == approval.sequence
            ),
            None,
        )
        states.append(
            {
                "id": str(row.id),
                "candidate_id": str(row.candidate_id),
                "profile": ClipProfile(str(row.profile)),
                "start_ms": int(row.start_ms),
                "duration_ms": int(row.duration_ms),
                "text": effective_customer_text(
                    CustomerText(
                        title=str(row.title), hook=str(row.hook), summary=str(row.summary)
                    ),
                    clip_decisions,
                ),
                "video_asset_id": str(row.video_asset_id),
                "subtitle_asset_id": str(row.subtitle_asset_id),
                "video_sha256": str(row.video_sha256),
                "subtitle_sha256": str(row.subtitle_sha256),
                "approval_decision_id": approval_id,
                "deliverable": is_deliverable(status, clip_decisions),
                "selected": is_selected_for_delivery(status, clip_decisions),
            }
        )
    return states


def _selected_clips(connection: Connection, project_id: str) -> list[dict[str, Any]]:
    return sorted(
        (clip for clip in _clip_states(connection, project_id) if clip["selected"]),
        key=lambda clip: (_PROFILE_ORDER[clip["profile"]], clip["start_ms"], clip["candidate_id"]),
    )


def _snapshot_fingerprint(
    *,
    project_id: str,
    import_id: str,
    version: int,
    title: str,
    created_at: datetime,
    clips: list[dict[str, Any]],
) -> str:
    payload = {
        "schema_version": _SNAPSHOT_SCHEMA,
        "project_id": project_id,
        "import_id": import_id,
        "version": version,
        "title": title,
        "created_at": created_at.isoformat(),
        "clips": [
            {
                "ordinal": ordinal,
                "import_clip_id": clip["id"],
                "profile": clip["profile"].value,
                "title": clip["text"].title,
                "hook": clip["text"].hook,
                "summary": clip["text"].summary,
                "duration_ms": clip["duration_ms"],
                "video_sha256": clip["video_sha256"],
                "subtitle_sha256": clip["subtitle_sha256"],
            }
            for ordinal, clip in enumerate(clips, start=1)
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _snapshot(connection: Connection, delivery_id: str) -> CustomerDeliverySnapshot:
    row = connection.execute(
        select(
            CustomerDeliveryRow.id,
            CustomerDeliveryRow.project_id,
            CustomerDeliveryRow.task_id,
            CustomerDeliveryRow.version,
            CustomerDeliveryRow.title,
            CustomerDeliveryRow.status,
            CustomerDeliveryRow.created_at,
            CustomerDeliveryRow.completed_at,
            CustomerDeliveryRow.zip_asset_id,
            CustomerDeliveryRow.error_code,
            CustomerDeliveryRow.safe_error_message,
            WorkspaceUserRow.display_name,
        )
        .join(WorkspaceUserRow, WorkspaceUserRow.id == CustomerDeliveryRow.created_by)
        .where(CustomerDeliveryRow.id == delivery_id)
    ).one_or_none()
    if row is None:
        raise CustomerDeliveryNotFound("customer delivery does not exist")
    counts = connection.execute(
        select(
            func.count(CustomerDeliveryClipRow.id),
            func.coalesce(
                func.sum(case((CustomerDeliveryClipRow.profile == "short_highlight", 1), else_=0)),
                0,
            ),
        ).where(CustomerDeliveryClipRow.delivery_id == delivery_id)
    ).one()
    total, short = int(counts[0]), int(counts[1])
    return CustomerDeliverySnapshot(
        delivery_id=str(row.id),
        project_id=str(row.project_id),
        task_id=str(row.task_id) if row.task_id is not None else None,
        version=int(row.version),
        delivery_version=f"v{int(row.version):03d}",
        title=str(row.title),
        status=DeliveryStatus(str(row.status)),
        clip_count=total,
        short_count=short,
        lesson_count=total - short,
        created_by=str(row.display_name),
        created_at=row.created_at,
        completed_at=row.completed_at,
        zip_asset_id=str(row.zip_asset_id) if row.zip_asset_id is not None else None,
        error_code=str(row.error_code) if row.error_code else None,
        safe_error_message=str(row.safe_error_message) if row.safe_error_message else None,
    )


def _leased_row(connection: Connection, lease: LeaseIdentity, *, now: datetime) -> Any | None:
    return connection.execute(
        select(
            TaskRow.id.label("task_id"),
            TaskRow.input_fingerprint,
            CustomerDeliveryRow.id.label("delivery_id"),
            CustomerDeliveryRow.project_id,
            CustomerDeliveryRow.version,
            CustomerDeliveryRow.title,
            CustomerDeliveryRow.status,
            CustomerDeliveryRow.created_at,
            CustomerDeliveryRow.created_by,
            CustomerDeliveryRow.snapshot_fingerprint,
        )
        .join(CustomerDeliveryRow, CustomerDeliveryRow.task_id == TaskRow.id)
        .where(
            TaskRow.id == lease.task_id,
            TaskRow.kind == TaskKind.DELIVERY.value,
            TaskRow.status == TaskStatus.RUNNING.value,
            TaskRow.worker_id == lease.worker_id,
            TaskRow.lease_token == lease.lease_token,
            TaskRow.lease_expires_at > now,
            TaskRow.cancellation_requested_at.is_(None),
        )
    ).one_or_none()


def _work(connection: Connection, row: Any) -> CustomerDeliveryWork:
    video = AssetRow.__table__.alias("video_asset")
    subtitle = AssetRow.__table__.alias("subtitle_asset")
    clips = connection.execute(
        select(
            CustomerDeliveryClipRow.ordinal,
            CustomerDeliveryClipRow.profile,
            CustomerDeliveryClipRow.title,
            CustomerDeliveryClipRow.hook,
            CustomerDeliveryClipRow.summary,
            CustomerDeliveryClipRow.duration_ms,
            CustomerDeliveryClipRow.video_sha256,
            CustomerDeliveryClipRow.subtitle_sha256,
            video.c.relative_path.label("video_path"),
            video.c.size_bytes.label("video_size"),
            video.c.sha256.label("video_asset_sha256"),
            subtitle.c.relative_path.label("subtitle_path"),
            subtitle.c.size_bytes.label("subtitle_size"),
            subtitle.c.sha256.label("subtitle_asset_sha256"),
        )
        .join(video, video.c.id == CustomerDeliveryClipRow.video_asset_id)
        .join(subtitle, subtitle.c.id == CustomerDeliveryClipRow.subtitle_asset_id)
        .where(CustomerDeliveryClipRow.delivery_id == row.delivery_id)
        .order_by(CustomerDeliveryClipRow.ordinal)
    ).all()
    if not clips:
        raise CustomerDeliveryConflict("customer delivery has no clips")
    work_clips: list[CustomerDeliveryWorkClip] = []
    for clip in clips:
        if (
            clip.video_sha256 != clip.video_asset_sha256
            or clip.subtitle_sha256 != clip.subtitle_asset_sha256
        ):
            raise CustomerDeliveryConflict("customer delivery media changed after the snapshot")
        work_clips.append(
            CustomerDeliveryWorkClip(
                ordinal=int(clip.ordinal),
                profile=ClipProfile(str(clip.profile)),
                title=str(clip.title),
                hook=str(clip.hook),
                summary=str(clip.summary),
                duration_ms=int(clip.duration_ms),
                video_relative_path=str(clip.video_path),
                video_sha256=str(clip.video_sha256),
                video_size_bytes=int(clip.video_size),
                subtitle_relative_path=str(clip.subtitle_path),
                subtitle_sha256=str(clip.subtitle_sha256),
                subtitle_size_bytes=int(clip.subtitle_size),
            )
        )
    return CustomerDeliveryWork(
        task_id=str(row.task_id),
        delivery_id=str(row.delivery_id),
        project_id=str(row.project_id),
        version=int(row.version),
        title=str(row.title),
        created_at=row.created_at,
        snapshot_fingerprint=str(row.snapshot_fingerprint),
        clips=tuple(work_clips),
    )


def _audit(
    connection: Connection,
    *,
    actor_user_id: str,
    actor_username: str | None,
    action: str,
    delivery_id: str,
    project_id: str,
    after: dict[str, object],
    now: datetime,
) -> None:
    if actor_username is None:
        actor_username = connection.scalar(
            select(WorkspaceUserRow.username).where(WorkspaceUserRow.id == actor_user_id)
        )
    connection.execute(
        insert(AuditEventRow).values(
            id=new_id(),
            actor_user_id=actor_user_id,
            actor_username=actor_username,
            action=action,
            target_type="customer_delivery",
            target_id=delivery_id,
            project_id=project_id,
            before_json=None,
            after_json=after,
            correlation_id=None,
            created_at=now,
        )
    )


__all__ = ["SqlAlchemyCustomerDeliveryRepository"]
