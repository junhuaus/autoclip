from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from liveclip.application.offline_review import (
    OfflineReviewClipObservation,
    OfflineReviewFenceToken,
    OfflineReviewPackageConflict,
    OfflineReviewProxyLineage,
)
from liveclip.application.pipeline import ProjectSnapshot, load_persisted_pipeline_config
from liveclip.db.models import (
    AssetRow,
    CandidateClipRow,
    EditPlanRevisionRow,
    PipelineRunRow,
    ProjectRow,
    RenderJobRow,
    ReviewDecisionRow,
    SourceMediaRow,
    StageRunRow,
    TaskAttemptRow,
    TaskRow,
)
from liveclip.domain.state_transitions import (
    AssetStatus,
    PipelineStage,
    RenderStatus,
    ReviewStatus,
    TaskKind,
)
from liveclip.media.models import SourceMediaMetadata
from liveclip.renderer.contracts import is_clean_review_proxy


class SqlAlchemyOfflineReviewFenceRepository:
    """Prove an offline export maps to one coherent current database snapshot.

    The snapshot transaction is intentionally short. Large file copies and ZIP
    compression happen outside SQLite, with the captured token checked immediately
    before and after the atomic filesystem publication.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def capture(
        self,
        *,
        project: ProjectSnapshot,
        source: SourceMediaMetadata,
        clips: tuple[OfflineReviewClipObservation, ...],
    ) -> OfflineReviewFenceToken:
        with self._engine.connect() as connection:
            token = _load_current_token(connection, project.project_id, clips)
        if (
            token.project_name != project.name
            or token.pipeline_run_id != project.current_run_id
            or token.generation != project.generation
            or token.source_filename != source.filename
            or token.source_fingerprint != source.sha256
        ):
            raise OfflineReviewPackageConflict(
                "project changed while the offline review snapshot was being captured"
            )
        return token

    def assert_current(self, token: OfflineReviewFenceToken) -> None:
        observations = tuple(
            OfflineReviewClipObservation(
                clip_id=item.clip_id,
                edit_plan_revision=item.edit_plan_revision,
                review_status=item.review_status,
                proxy_asset_id=item.asset_id,
                proxy_sha256=item.asset_sha256,
                proxy_size_bytes=item.asset_size_bytes,
            )
            for item in token.clips
        )
        with self._engine.connect() as connection:
            current = _load_current_token(connection, token.project_id, observations)
        if current != token:
            raise OfflineReviewPackageConflict(
                "project review state changed while the offline package was being built"
            )


def _load_current_token(
    connection: Connection,
    project_id: str,
    observations: tuple[OfflineReviewClipObservation, ...],
) -> OfflineReviewFenceToken:
    if not observations:
        raise OfflineReviewPackageConflict("offline review snapshot has no clips")
    project = connection.execute(
        select(
            ProjectRow.name,
            ProjectRow.current_pipeline_run_id,
            ProjectRow.current_generation,
            ProjectRow.revision_epoch,
        ).where(ProjectRow.id == project_id)
    ).one_or_none()
    if project is None or project.current_pipeline_run_id is None:
        raise OfflineReviewPackageConflict("project does not have a current pipeline run")
    run_id = str(project.current_pipeline_run_id)
    generation = int(project.current_generation)
    run = connection.execute(
        select(PipelineRunRow.config_json, PipelineRunRow.config_fingerprint).where(
            PipelineRunRow.id == run_id,
            PipelineRunRow.project_id == project_id,
            PipelineRunRow.generation == generation,
        )
    ).one_or_none()
    if run is None:
        raise OfflineReviewPackageConflict("project pipeline generation is no longer current")
    try:
        pipeline_config = load_persisted_pipeline_config(
            run.config_json,
            str(run.config_fingerprint),
        ).model_dump(mode="json")
    except Exception as exc:
        raise OfflineReviewPackageConflict(
            "pipeline configuration cannot prove proxy lineage"
        ) from exc

    source = connection.execute(
        select(SourceMediaRow.filename, SourceMediaRow.sha256).where(
            SourceMediaRow.project_id == project_id
        )
    ).one_or_none()
    if source is None:
        raise OfflineReviewPackageConflict("project source media is missing")

    expected_ids = tuple(item.clip_id for item in observations)
    if len(expected_ids) != len(set(expected_ids)):
        raise OfflineReviewPackageConflict("offline review clip observations are not unique")
    current_ids = tuple(
        str(value)
        for value in connection.scalars(
            select(CandidateClipRow.id)
            .where(
                CandidateClipRow.project_id == project_id,
                CandidateClipRow.pipeline_run_id == run_id,
                CandidateClipRow.selected_for_review.is_(True),
            )
            .order_by(CandidateClipRow.rank, CandidateClipRow.id)
        )
    )
    if set(current_ids) != set(expected_ids) or len(current_ids) != len(expected_ids):
        raise OfflineReviewPackageConflict("current review clip set changed during export")

    lineages = tuple(
        _load_clip_lineage(
            connection,
            project_id=project_id,
            run_id=run_id,
            generation=generation,
            project_revision_epoch=int(project.revision_epoch),
            pipeline_config=pipeline_config,
            observed=observed,
        )
        for observed in observations
    )
    return OfflineReviewFenceToken(
        project_id=project_id,
        project_name=str(project.name),
        pipeline_run_id=run_id,
        generation=generation,
        revision_epoch=int(project.revision_epoch),
        source_filename=str(source.filename),
        source_fingerprint=str(source.sha256),
        clips=lineages,
    )


def _load_clip_lineage(
    connection: Connection,
    *,
    project_id: str,
    run_id: str,
    generation: int,
    project_revision_epoch: int,
    pipeline_config: dict[str, object],
    observed: OfflineReviewClipObservation,
) -> OfflineReviewProxyLineage:
    revision = connection.execute(
        select(
            CandidateClipRow.current_revision,
            EditPlanRevisionRow.id.label("revision_id"),
        )
        .join(
            EditPlanRevisionRow,
            (EditPlanRevisionRow.candidate_clip_id == CandidateClipRow.id)
            & (EditPlanRevisionRow.revision == CandidateClipRow.current_revision),
        )
        .where(
            CandidateClipRow.id == observed.clip_id,
            CandidateClipRow.project_id == project_id,
            CandidateClipRow.pipeline_run_id == run_id,
            CandidateClipRow.selected_for_review.is_(True),
        )
    ).one_or_none()
    if revision is None or int(revision.current_revision) != observed.edit_plan_revision:
        raise OfflineReviewPackageConflict(
            f"clip {observed.clip_id} edit plan changed during export"
        )
    revision_id = str(revision.revision_id)
    decision = connection.scalar(
        select(ReviewDecisionRow.status)
        .where(ReviewDecisionRow.edit_plan_revision_id == revision_id)
        .order_by(ReviewDecisionRow.decided_at.desc(), ReviewDecisionRow.id.desc())
        .limit(1)
    )
    review_status = (
        ReviewStatus(str(decision)) if decision is not None else ReviewStatus.PENDING_REVIEW
    )
    if review_status != observed.review_status:
        raise OfflineReviewPackageConflict(
            f"clip {observed.clip_id} review decision changed during export"
        )

    render = connection.execute(
        select(
            RenderJobRow.id,
            RenderJobRow.task_id,
            RenderJobRow.status,
            RenderJobRow.asset_id,
            RenderJobRow.edit_plan_revision,
            RenderJobRow.revision_epoch,
            RenderJobRow.spec_fingerprint,
            RenderJobRow.spec_json,
        )
        .where(
            RenderJobRow.candidate_clip_id == observed.clip_id,
            RenderJobRow.edit_plan_revision_id == revision_id,
            RenderJobRow.kind == "proxy",
        )
        .order_by(RenderJobRow.created_at.desc(), RenderJobRow.id.desc())
        .limit(1)
    ).one_or_none()
    if (
        render is None
        or str(render.status) != RenderStatus.SUCCEEDED.value
        or render.asset_id is None
        or str(render.asset_id) != observed.proxy_asset_id
        or int(render.edit_plan_revision) != observed.edit_plan_revision
        or not is_clean_review_proxy(spec=render.spec_json, pipeline_config=pipeline_config)
    ):
        raise OfflineReviewPackageConflict(
            f"clip {observed.clip_id} does not have the current clean review proxy"
        )

    asset = connection.execute(
        select(
            AssetRow.id,
            AssetRow.input_fingerprint,
            AssetRow.sha256,
            AssetRow.size_bytes,
            AssetRow.generation,
            AssetRow.edit_plan_revision,
            AssetRow.revision_epoch,
            AssetRow.producer_attempt_id,
        ).where(
            AssetRow.id == observed.proxy_asset_id,
            AssetRow.project_id == project_id,
            AssetRow.candidate_clip_id == observed.clip_id,
            AssetRow.kind == "review_proxy",
            AssetRow.status == AssetStatus.COMMITTED.value,
        )
    ).one_or_none()
    if (
        asset is None
        or asset.sha256 is None
        or asset.size_bytes is None
        or asset.generation is None
        or asset.edit_plan_revision is None
        or asset.revision_epoch is None
        or asset.producer_attempt_id is None
        or int(asset.generation) != generation
        or int(asset.edit_plan_revision) != observed.edit_plan_revision
        or int(asset.revision_epoch) != int(render.revision_epoch)
        or str(asset.sha256) != observed.proxy_sha256
        or int(asset.size_bytes) != observed.proxy_size_bytes
    ):
        raise OfflineReviewPackageConflict(
            f"clip {observed.clip_id} proxy asset lineage changed during export"
        )
    if int(render.revision_epoch) > project_revision_epoch:
        raise OfflineReviewPackageConflict("proxy render revision epoch is ahead of the project")

    producer = connection.execute(
        select(
            TaskRow.id.label("task_id"),
            TaskRow.kind,
            TaskRow.input_fingerprint,
            TaskRow.pipeline_run_id,
            TaskRow.status.label("task_status"),
            StageRunRow.stage,
            TaskAttemptRow.outcome,
        )
        .join(TaskAttemptRow, TaskAttemptRow.task_id == TaskRow.id)
        .outerjoin(StageRunRow, StageRunRow.id == TaskRow.stage_run_id)
        .where(TaskAttemptRow.id == asset.producer_attempt_id)
    ).one_or_none()
    if (
        producer is None
        or str(producer.task_id) != str(render.task_id)
        or str(producer.pipeline_run_id) != run_id
        or str(producer.input_fingerprint) != str(asset.input_fingerprint)
        or str(producer.task_status) != "succeeded"
        or str(producer.outcome) != "succeeded"
    ):
        raise OfflineReviewPackageConflict(
            f"clip {observed.clip_id} proxy producer lineage changed during export"
        )
    producer_kind = str(producer.kind)
    producer_stage = str(producer.stage) if producer.stage is not None else None
    if producer_kind == TaskKind.RENDER.value:
        if producer_stage is not None or str(producer.input_fingerprint) != str(
            render.spec_fingerprint
        ):
            raise OfflineReviewPackageConflict("manual proxy producer spec lineage is invalid")
    elif producer_kind == TaskKind.STAGE.value:
        if producer_stage != PipelineStage.PROXY_RENDER.value:
            raise OfflineReviewPackageConflict("pipeline proxy producer stage is invalid")
    else:
        raise OfflineReviewPackageConflict("proxy producer task kind is invalid")

    return OfflineReviewProxyLineage(
        clip_id=observed.clip_id,
        edit_plan_revision_id=revision_id,
        edit_plan_revision=observed.edit_plan_revision,
        review_status=review_status,
        render_job_id=str(render.id),
        render_spec_fingerprint=str(render.spec_fingerprint),
        render_revision_epoch=int(render.revision_epoch),
        producer_task_id=str(producer.task_id),
        producer_task_kind=producer_kind,
        producer_stage=producer_stage,
        asset_id=str(asset.id),
        asset_input_fingerprint=str(asset.input_fingerprint),
        asset_generation=int(asset.generation),
        asset_edit_plan_revision=int(asset.edit_plan_revision),
        asset_revision_epoch=int(asset.revision_epoch),
        asset_sha256=str(asset.sha256),
        asset_size_bytes=int(asset.size_bytes),
    )
