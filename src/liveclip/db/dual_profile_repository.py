"""SQLite persistence for imported dual-profile runs and reviewer decisions (Stage 19a)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from liveclip.application.dual_profile_imports import (
    DecisionRecord,
    DualProfileDecisionConflict,
    DualProfileImportDuplicate,
    DualProfileImportError,
    DualProfileImportResult,
    DualProfileReviewRecord,
    ImportedClipState,
    NewDualProfileImport,
    ReviewClipRecord,
    clip_decision_from_values,
)
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.models import (
    AssetRow,
    AuditEventRow,
    DualProfileClipDecisionRow,
    DualProfileImportClipRow,
    DualProfileImportRow,
    ProjectMemberRow,
    ProjectRow,
    WorkspaceUserRow,
)
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.customer_delivery import (
    ClipDecision,
    ClipDecisionAction,
    CustomerText,
    ImportedClipStatus,
    is_deliverable,
)
from liveclip.domain.project_lifecycle import ProjectLifecycle, ProjectPriority
from liveclip.domain.state_transitions import AssetStatus


class DualProfileClipNotFound(LookupError):
    """The imported clip does not exist in the requested project."""


class SqlAlchemyDualProfileImportRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def find_import(
        self,
        *,
        acting_user_id: str,
        snapshot_fingerprint: str,
    ) -> DualProfileImportResult | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(
                    DualProfileImportRow.id,
                    DualProfileImportRow.project_id,
                    DualProfileImportRow.snapshot_fingerprint,
                    DualProfileImportRow.clip_count,
                ).where(
                    DualProfileImportRow.imported_by == acting_user_id,
                    DualProfileImportRow.snapshot_fingerprint == snapshot_fingerprint,
                )
            ).one_or_none()
        if row is None:
            return None
        return DualProfileImportResult(
            project_id=str(row.project_id),
            import_id=str(row.id),
            snapshot_fingerprint=str(row.snapshot_fingerprint),
            clip_count=int(row.clip_count),
            created=False,
        )

    def insert_import(self, record: NewDualProfileImport) -> DualProfileImportResult:
        now = record.created_at
        try:
            with begin_immediate(self._engine) as connection:
                _require_active_user(connection, record.acting_user_id)
                _insert_project(connection, record, now=now)
                connection.execute(
                    insert(DualProfileImportRow).values(
                        id=record.import_id,
                        project_id=record.project_id,
                        schema_version="1",
                        source_hash=record.source_hash,
                        transcript_sha256=record.transcript_sha256,
                        final_result_sha256=record.final_result_sha256,
                        run_manifest_sha256=record.run_manifest_sha256,
                        render_manifest_sha256=record.render_manifest_sha256,
                        algorithm_version=record.algorithm_version,
                        routing_policy_version=record.routing_policy_version,
                        snapshot_fingerprint=record.snapshot_fingerprint,
                        source_filename=record.source_filename,
                        prompt_hashes_json=dict(sorted(record.prompt_hashes.items())),
                        clip_count=len(record.clips),
                        imported_by=record.acting_user_id,
                        created_at=now,
                    )
                )
                for clip in record.clips:
                    asset_ids = []
                    for asset in (clip.video, clip.subtitle):
                        asset_id = new_id()
                        connection.execute(
                            insert(AssetRow).values(
                                id=asset_id,
                                project_id=record.project_id,
                                status=AssetStatus.COMMITTED.value,
                                kind=asset.kind,
                                relative_path=asset.relative_path,
                                mime_type=asset.mime_type,
                                input_fingerprint=record.snapshot_fingerprint,
                                expected_sha256=asset.sha256,
                                sha256=asset.sha256,
                                size_bytes=asset.size_bytes,
                                validation_json={"source": "dual_profile_import"},
                                created_at=now,
                                committed_at=now,
                            )
                        )
                        asset_ids.append(asset_id)
                    connection.execute(
                        insert(DualProfileImportClipRow).values(
                            id=new_id(),
                            import_id=record.import_id,
                            project_id=record.project_id,
                            candidate_id=clip.candidate_id,
                            profile=clip.profile.value,
                            routed_status=clip.routed_status.value,
                            variant_group_id=clip.variant_group_id,
                            start_cue_id=clip.start_cue_id,
                            end_cue_id=clip.end_cue_id,
                            start_ms=clip.start_ms,
                            end_ms=clip.end_ms,
                            duration_ms=clip.duration_ms,
                            title=clip.title,
                            hook=clip.hook,
                            summary=clip.summary,
                            score=clip.score,
                            review_reason=clip.review_reason,
                            quality_flags_json=list(clip.quality_flags),
                            risk_tags_json=list(clip.risk_tags),
                            video_asset_id=asset_ids[0],
                            subtitle_asset_id=asset_ids[1],
                            created_at=now,
                        )
                    )
                _audit(
                    connection,
                    actor_user_id=record.acting_user_id,
                    action="dual_profile.imported",
                    project_id=record.project_id,
                    target_type="dual_profile_import",
                    target_id=record.import_id,
                    after={
                        "clip_count": len(record.clips),
                        "snapshot": record.snapshot_fingerprint[:20],
                        "algorithm_version": record.algorithm_version,
                        "routing_policy_version": record.routing_policy_version,
                    },
                    now=now,
                )
        except IntegrityError as exc:
            if _is_duplicate_snapshot(exc):
                raise DualProfileImportDuplicate("snapshot was imported concurrently") from exc
            raise
        return DualProfileImportResult(
            project_id=record.project_id,
            import_id=record.import_id,
            snapshot_fingerprint=record.snapshot_fingerprint,
            clip_count=len(record.clips),
            created=True,
        )

    def append_decision(
        self,
        *,
        project_id: str,
        import_clip_id: str,
        acting_user_id: str,
        action: ClipDecisionAction,
        title_override: str | None = None,
        hook_override: str | None = None,
        summary_override: str | None = None,
        require_deliverable: bool = False,
        acknowledge_warnings: bool = False,
        now: datetime,
    ) -> ClipDecision:
        """Append one decision with the next per-clip sequence number.

        Authorization belongs to the caller. With ``require_deliverable`` the
        clip's eligibility is re-evaluated inside the same write transaction, so
        a concurrent rejection cannot slip between the check and the append.
        """

        with begin_immediate(self._engine) as connection:
            _require_active_user(connection, acting_user_id)
            routed_status = connection.scalar(
                select(DualProfileImportClipRow.routed_status).where(
                    DualProfileImportClipRow.id == import_clip_id,
                    DualProfileImportClipRow.project_id == project_id,
                )
            )
            if routed_status is None:
                raise DualProfileClipNotFound("imported clip does not exist")
            if require_deliverable and not is_deliverable(
                ImportedClipStatus(str(routed_status)),
                _clip_decisions(connection, import_clip_id),
            ):
                raise DualProfileDecisionConflict(
                    "only an automatically selected or approved clip can be selected for delivery"
                )
            current = connection.scalar(
                select(func.max(DualProfileClipDecisionRow.sequence)).where(
                    DualProfileClipDecisionRow.import_clip_id == import_clip_id
                )
            )
            decision = ClipDecision(
                sequence=int(current or 0) + 1,
                action=action,
                title_override=title_override,
                hook_override=hook_override,
                summary_override=summary_override,
                acknowledge_warnings=acknowledge_warnings,
            )
            decision_id = new_id()
            connection.execute(
                insert(DualProfileClipDecisionRow).values(
                    id=decision_id,
                    import_clip_id=import_clip_id,
                    project_id=project_id,
                    sequence=decision.sequence,
                    action=decision.action.value,
                    title_override=decision.title_override,
                    hook_override=decision.hook_override,
                    summary_override=decision.summary_override,
                    actor_user_id=acting_user_id,
                    decided_at=now,
                    acknowledge_warnings=decision.acknowledge_warnings,
                )
            )
            _audit(
                connection,
                actor_user_id=acting_user_id,
                action=f"dual_profile.clip_{decision.action.value}",
                project_id=project_id,
                target_type="dual_profile_import_clip",
                target_id=import_clip_id,
                after={
                    "sequence": decision.sequence,
                    "override": decision.has_override,
                    "acknowledge_warnings": acknowledge_warnings,
                },
                now=now,
            )
        return decision

    def load_review(self, *, project_id: str) -> DualProfileReviewRecord | None:
        """The import, its immutable clips (internal fields) and decision history."""

        with self._engine.connect() as connection:
            imported = connection.execute(
                select(
                    DualProfileImportRow.id,
                    DualProfileImportRow.source_filename,
                    DualProfileImportRow.snapshot_fingerprint,
                    DualProfileImportRow.algorithm_version,
                    DualProfileImportRow.routing_policy_version,
                    DualProfileImportRow.clip_count,
                    DualProfileImportRow.created_at,
                    WorkspaceUserRow.username,
                )
                .join(WorkspaceUserRow, WorkspaceUserRow.id == DualProfileImportRow.imported_by)
                .where(DualProfileImportRow.project_id == project_id)
            ).one_or_none()
            if imported is None:
                return None
            clips = connection.execute(
                select(DualProfileImportClipRow).where(
                    DualProfileImportClipRow.project_id == project_id
                )
            ).all()
            decisions = connection.execute(
                select(
                    DualProfileClipDecisionRow.import_clip_id,
                    DualProfileClipDecisionRow.sequence,
                    DualProfileClipDecisionRow.action,
                    DualProfileClipDecisionRow.title_override,
                    DualProfileClipDecisionRow.hook_override,
                    DualProfileClipDecisionRow.summary_override,
                    DualProfileClipDecisionRow.decided_at,
                    DualProfileClipDecisionRow.acknowledge_warnings,
                    WorkspaceUserRow.username,
                    WorkspaceUserRow.display_name,
                )
                .join(
                    WorkspaceUserRow,
                    WorkspaceUserRow.id == DualProfileClipDecisionRow.actor_user_id,
                )
                .where(DualProfileClipDecisionRow.project_id == project_id)
                .order_by(
                    DualProfileClipDecisionRow.import_clip_id,
                    DualProfileClipDecisionRow.sequence,
                )
            ).all()
        history: dict[str, list[DecisionRecord]] = {}
        for row in decisions:
            history.setdefault(str(row.import_clip_id), []).append(
                DecisionRecord(
                    decision=clip_decision_from_values(
                        sequence=int(row.sequence),
                        action=str(row.action),
                        title_override=row.title_override,
                        hook_override=row.hook_override,
                        summary_override=row.summary_override,
                        acknowledge_warnings=bool(row.acknowledge_warnings),
                    ),
                    actor_username=str(row.username),
                    actor_display_name=str(row.display_name),
                    decided_at=row.decided_at,
                    acknowledge_warnings=bool(row.acknowledge_warnings),
                )
            )
        return DualProfileReviewRecord(
            import_id=str(imported.id),
            project_id=project_id,
            source_filename=str(imported.source_filename),
            snapshot_fingerprint=str(imported.snapshot_fingerprint),
            algorithm_version=str(imported.algorithm_version),
            routing_policy_version=str(imported.routing_policy_version),
            clip_count=int(imported.clip_count),
            imported_at=imported.created_at,
            imported_by=str(imported.username),
            clips=tuple(
                ReviewClipRecord(
                    import_clip_id=str(row.id),
                    candidate_id=str(row.candidate_id),
                    profile=ClipProfile(row.profile),
                    routed_status=ImportedClipStatus(row.routed_status),
                    variant_group_id=str(row.variant_group_id),
                    start_ms=int(row.start_ms),
                    end_ms=int(row.end_ms),
                    duration_ms=int(row.duration_ms),
                    original_text=CustomerText(
                        title=str(row.title), hook=str(row.hook), summary=str(row.summary)
                    ),
                    score=float(row.score),
                    review_reason=str(row.review_reason),
                    quality_flags=tuple(str(value) for value in row.quality_flags_json),
                    risk_tags=tuple(str(value) for value in row.risk_tags_json),
                    video_asset_id=str(row.video_asset_id),
                    subtitle_asset_id=str(row.subtitle_asset_id),
                    history=tuple(history.get(str(row.id), ())),
                )
                for row in clips
            ),
        )

    def list_clip_states(self, *, project_id: str) -> tuple[ImportedClipState, ...]:
        with self._engine.connect() as connection:
            clips = connection.execute(
                select(DualProfileImportClipRow)
                .where(DualProfileImportClipRow.project_id == project_id)
                .order_by(
                    DualProfileImportClipRow.profile.desc(),
                    DualProfileImportClipRow.start_ms,
                    DualProfileImportClipRow.candidate_id,
                )
            ).all()
            decisions = connection.execute(
                select(
                    DualProfileClipDecisionRow.import_clip_id,
                    DualProfileClipDecisionRow.sequence,
                    DualProfileClipDecisionRow.action,
                    DualProfileClipDecisionRow.title_override,
                    DualProfileClipDecisionRow.hook_override,
                    DualProfileClipDecisionRow.summary_override,
                    DualProfileClipDecisionRow.acknowledge_warnings,
                )
                .where(DualProfileClipDecisionRow.project_id == project_id)
                .order_by(
                    DualProfileClipDecisionRow.import_clip_id,
                    DualProfileClipDecisionRow.sequence,
                )
            ).all()
        by_clip: dict[str, list[ClipDecision]] = {}
        for row in decisions:
            by_clip.setdefault(str(row.import_clip_id), []).append(
                clip_decision_from_values(
                    sequence=int(row.sequence),
                    action=str(row.action),
                    title_override=row.title_override,
                    hook_override=row.hook_override,
                    summary_override=row.summary_override,
                    acknowledge_warnings=bool(row.acknowledge_warnings),
                )
            )
        return tuple(
            ImportedClipState(
                import_clip_id=str(row.id),
                project_id=str(row.project_id),
                candidate_id=str(row.candidate_id),
                profile=ClipProfile(row.profile),
                routed_status=ImportedClipStatus(row.routed_status),
                start_ms=int(row.start_ms),
                end_ms=int(row.end_ms),
                duration_ms=int(row.duration_ms),
                original_text=CustomerText(
                    title=str(row.title),
                    hook=str(row.hook),
                    summary=str(row.summary),
                ),
                video_asset_id=str(row.video_asset_id),
                subtitle_asset_id=str(row.subtitle_asset_id),
                decisions=tuple(by_clip.get(str(row.id), ())),
            )
            for row in clips
        )


def _clip_decisions(connection: Connection, import_clip_id: str) -> tuple[ClipDecision, ...]:
    rows = connection.execute(
        select(
            DualProfileClipDecisionRow.sequence,
            DualProfileClipDecisionRow.action,
            DualProfileClipDecisionRow.title_override,
            DualProfileClipDecisionRow.hook_override,
            DualProfileClipDecisionRow.summary_override,
            DualProfileClipDecisionRow.acknowledge_warnings,
        )
        .where(DualProfileClipDecisionRow.import_clip_id == import_clip_id)
        .order_by(DualProfileClipDecisionRow.sequence)
    ).all()
    return tuple(
        clip_decision_from_values(
            sequence=int(row.sequence),
            action=str(row.action),
            title_override=row.title_override,
            hook_override=row.hook_override,
            summary_override=row.summary_override,
            acknowledge_warnings=bool(row.acknowledge_warnings),
        )
        for row in rows
    )


def _require_active_user(connection: Connection, user_id: str) -> None:
    active = connection.scalar(
        select(WorkspaceUserRow.id).where(
            WorkspaceUserRow.id == user_id,
            WorkspaceUserRow.is_active.is_(True),
        )
    )
    if active is None:
        raise DualProfileImportError("acting workspace user does not exist or is inactive")


def _insert_project(connection: Connection, record: NewDualProfileImport, *, now: datetime) -> None:
    connection.execute(
        insert(ProjectRow).values(
            id=record.project_id,
            name=record.project_name,
            owner_id=record.acting_user_id,
            visibility="private",
            lifecycle=ProjectLifecycle.EDITORIAL_REVIEW.value,
            management_version=1,
            assignee_user_id=record.acting_user_id,
            priority=ProjectPriority.NORMAL.value,
            source_request_path=record.source_request_path,
            current_generation=0,
            current_pipeline_run_id=None,
            revision_epoch=0,
            created_at=now,
            updated_at=now,
        )
    )
    connection.execute(
        insert(ProjectMemberRow).values(
            id=new_id(),
            project_id=record.project_id,
            user_id=record.acting_user_id,
            role="owner",
            created_at=now,
        )
    )


def _audit(
    connection: Connection,
    *,
    actor_user_id: str,
    action: str,
    project_id: str,
    target_type: str,
    target_id: str,
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
            target_type=target_type,
            target_id=target_id,
            project_id=project_id,
            before_json=None,
            after_json=after,
            correlation_id=None,
            created_at=now,
        )
    )


def _is_duplicate_snapshot(exc: IntegrityError) -> bool:
    message = str(exc.orig)
    return "dual_profile_imports.imported_by" in message and "snapshot_fingerprint" in message


__all__ = ["DualProfileClipNotFound", "SqlAlchemyDualProfileImportRepository"]
