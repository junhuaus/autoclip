from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine

from liveclip.application.idempotency import build_idempotency_context
from liveclip.application.pipeline import PipelineRunConfig
from liveclip.application.rendering import RenderConflict, RenderProfile, RenderService
from liveclip.application.reviewing import (
    BatchReviewCommand,
    BatchReviewItem,
    ClipPatch,
    RenderRequest,
    ReviewCommand,
    ReviewConflict,
    ReviewService,
)
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import (
    CandidateClipRow,
    CaptionCueRow,
    DeliveryRow,
    EditPlanRevisionRow,
    PipelineRunRow,
    ProjectRow,
    RenderJobRow,
    ReviewDecisionRow,
    SourceMediaRow,
    TaskRow,
)
from liveclip.db.render_repository import SqlAlchemyRenderRepository
from liveclip.db.review_repository import SqlAlchemyReviewRepository
from liveclip.domain.edit_plan import CaptionTemplate, EditPlan, Effect, Layout
from liveclip.domain.state_transitions import (
    DeliveryStatus,
    FailureClass,
    PipelineRunStatus,
    RenderStatus,
    ResourceClass,
    ReviewStatus,
    TaskKind,
    TaskStatus,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def review_context(
    tmp_path: Path,
) -> Iterator[tuple[Engine, ReviewService, str, str, str]]:
    engine = create_sqlite_engine(tmp_path / "review-atomic.sqlite3")
    Base.metadata.create_all(engine)
    project_id = "project0000000000000000000000001"
    run_id = "run00000000000000000000000000001"
    clip_id = "clip0000000000000000000000000001"
    revision_id = "revision00000000000000000000001"
    task_id = "task0000000000000000000000000001"
    config = PipelineRunConfig(
        provider="mock",
        top_n=1,
        minimum_clip_ms=8_000,
        maximum_clip_ms=12_000,
        chunk_duration_ms=12_000,
        chunk_overlap_ms=2_000,
        max_chunk_bytes=24_000_000,
        transcription_model="mock-asr-v1",
        llm_model="mock-llm-v1",
        preview_width=270,
        preview_height=480,
        video_encoder="libx264",
    )
    plan = EditPlan(
        candidate_id=clip_id,
        source_start_ms=2_000,
        source_end_ms=10_000,
        score=88,
        title="初始高光标题",
        hook="这是一个完整开场",
        reason="表达完整且适合切片",
        layout=Layout.CENTER_CROP,
        caption_template=CaptionTemplate.CLEAN_ZH_V1,
        effect=Effect.NONE,
        risk_flags=(),
        prompt_version="editing_v1",
        model="mock-llm-v1",
        degraded=True,
    )
    with engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id=project_id,
                name="Atomic review project",
                source_request_path="/allowed/source.mp4",
                current_generation=1,
                current_pipeline_run_id=run_id,
                revision_epoch=0,
            )
        )
        connection.execute(
            insert(PipelineRunRow).values(
                id=run_id,
                project_id=project_id,
                generation=1,
                status=PipelineRunStatus.COMPLETED.value,
                config_json=config.model_dump(mode="json"),
                config_fingerprint=config.fingerprint,
                progress=100,
                manual_retry_count=0,
            )
        )
        connection.execute(
            insert(SourceMediaRow).values(
                id="source00000000000000000000000001",
                project_id=project_id,
                resolved_path="/allowed/source.mp4",
                filename="source.mp4",
                sha256="a" * 64,
                size_bytes=1_000_000,
                mtime_ns=1,
                device=1,
                inode=1,
                duration_ms=20_000,
                width=1_920,
                height=1_080,
                video_codec="h264",
                video_stream_index=0,
                video_rotation_degrees=0,
                audio_codec="aac",
                audio_stream_index=1,
                frame_rate="30",
                probe_json={"schema_version": "1"},
            )
        )
        connection.execute(
            insert(CandidateClipRow).values(
                id=clip_id,
                project_id=project_id,
                pipeline_run_id=run_id,
                candidate_key="candidate-1",
                source_start_ms=2_000,
                source_end_ms=10_000,
                allowed_start_ms=0,
                allowed_end_ms=15_000,
                transcript_text="这是一段用于原子审核测试的完整中文转写。",
                context_before="前文",
                context_after="后文",
                rule_score=88,
                reasons_json=["表达完整"],
                segment_ids_json=[],
                current_revision=1,
                rank=1,
                selected_for_review=True,
            )
        )
        connection.execute(
            insert(EditPlanRevisionRow).values(
                id=revision_id,
                candidate_clip_id=clip_id,
                revision=1,
                parent_revision=None,
                origin="deterministic",
                source_start_ms=plan.source_start_ms,
                source_end_ms=plan.source_end_ms,
                score=plan.score,
                title=plan.title,
                hook=plan.hook,
                reason=plan.reason,
                layout=plan.layout.value,
                caption_template=plan.caption_template.value,
                effect=plan.effect.value,
                risk_flags_json=[],
                prompt_version=plan.prompt_version,
                model=plan.model,
                degraded=plan.degraded,
                plan_json=plan.model_dump(mode="json"),
            )
        )
        connection.execute(
            insert(CaptionCueRow).values(
                id="caption0000000000000000000000001",
                edit_plan_revision_id=revision_id,
                cue_index=0,
                start_ms=0,
                end_ms=8_000,
                text="这是一段用于原子审核测试的完整中文转写。",
            )
        )
        connection.execute(
            insert(TaskRow).values(
                id=task_id,
                kind=TaskKind.RENDER.value,
                target_id=clip_id,
                operation_key=f"render:{clip_id}:r001",
                input_fingerprint="b" * 64,
                resource_class=ResourceClass.HEAVY.value,
                pipeline_run_id=run_id,
                status=TaskStatus.QUEUED.value,
                priority=800,
                expected_generation=1,
                expected_revision=1,
                expected_revision_epoch=0,
                attempt_count=0,
                retry_count=0,
                manual_retry_count=0,
                max_retries=1,
            )
        )
        connection.execute(
            insert(RenderJobRow).values(
                id="render0000000000000000000000001",
                candidate_clip_id=clip_id,
                edit_plan_revision_id=revision_id,
                task_id=task_id,
                kind="proxy",
                status=RenderStatus.QUEUED.value,
                edit_plan_revision=1,
                revision_epoch=0,
                width=270,
                height=480,
                spec_fingerprint="b" * 64,
                spec_json={"schema_version": "1"},
            )
        )
    try:
        yield (
            engine,
            ReviewService(SqlAlchemyReviewRepository(engine)),
            clip_id,
            revision_id,
            task_id,
        )
    finally:
        engine.dispose(close=True)


def test_revise_and_approve_commits_one_revision_decision_and_cancels_old_render(
    review_context: tuple[Engine, ReviewService, str, str, str],
) -> None:
    engine, service, clip_id, old_revision_id, task_id = review_context

    result = service.revise_and_review(
        clip_id,
        ClipPatch(expected_revision=1, title="人工确认后的标题"),
        ReviewCommand(expected_revision=1, status=ReviewStatus.APPROVED),
    )

    assert result.current_revision == 2
    assert result.plan.title == "人工确认后的标题"
    assert result.plan.layout is Layout.CENTER_CROP
    assert result.review.status == ReviewStatus.APPROVED
    assert {render.status for render in result.renders} == {RenderStatus.STALE}
    with engine.connect() as connection:
        revisions = connection.execute(
            select(
                EditPlanRevisionRow.id,
                EditPlanRevisionRow.revision,
                EditPlanRevisionRow.parent_revision,
                EditPlanRevisionRow.origin,
            ).order_by(EditPlanRevisionRow.revision)
        ).all()
        assert len(revisions) == 2
        assert revisions[0].id == old_revision_id
        new_revision_id = str(revisions[1].id)
        assert tuple(revisions[1][1:]) == (2, 1, "human")
        assert connection.scalar(select(ProjectRow.revision_epoch)) == 1
        assert connection.scalar(select(CandidateClipRow.current_revision)) == 2
        assert (
            connection.scalar(
                select(func.count())
                .select_from(CaptionCueRow)
                .where(CaptionCueRow.edit_plan_revision_id == new_revision_id)
            )
            == 1
        )
        decision = connection.execute(
            select(
                ReviewDecisionRow.edit_plan_revision_id,
                ReviewDecisionRow.status,
                ReviewDecisionRow.rejection_reason,
            )
        ).one()
        assert tuple(decision) == (new_revision_id, ReviewStatus.APPROVED.value, None)
        task = connection.execute(
            select(
                TaskRow.status,
                TaskRow.cancellation_requested_at,
                TaskRow.completed_at,
            ).where(TaskRow.id == task_id)
        ).one()
        assert task.status == TaskStatus.CANCELLED.value
        assert task.cancellation_requested_at is not None
        assert task.completed_at is not None


def test_legacy_blur_revision_cannot_be_approved_or_rendered_until_revised(
    review_context: tuple[Engine, ReviewService, str, str, str],
) -> None:
    engine, service, clip_id, revision_id, _ = review_context
    with engine.begin() as connection:
        payload = dict(
            connection.scalar(
                select(EditPlanRevisionRow.plan_json).where(EditPlanRevisionRow.id == revision_id)
            )
        )
        payload["layout"] = Layout.VERTICAL_BLUR_BACKGROUND.value
        connection.execute(
            update(EditPlanRevisionRow)
            .where(EditPlanRevisionRow.id == revision_id)
            .values(
                layout=Layout.VERTICAL_BLUR_BACKGROUND.value,
                plan_json=payload,
            )
        )

    legacy = service.get_clip(clip_id)
    assert legacy.plan.layout is Layout.VERTICAL_BLUR_BACKGROUND
    assert "approve" not in legacy.allowed_actions
    assert "render_proxy" not in legacy.allowed_actions

    with pytest.raises(ReviewConflict, match="center-crop layout"):
        service.review_clip(
            clip_id,
            ReviewCommand(expected_revision=1, status=ReviewStatus.APPROVED),
        )
    with pytest.raises(RenderConflict, match="center-crop layout"):
        RenderService(
            SqlAlchemyRenderRepository(engine),
            RenderProfile(
                preview_width=270,
                preview_height=480,
                final_width=1_080,
                final_height=1_920,
                encoder="libx264",
                max_retries=1,
            ),
        ).enqueue(
            clip_id,
            RenderRequest(expected_revision=1, kind="proxy"),
        )

    migrated = service.revise_clip(
        clip_id,
        ClipPatch(expected_revision=1, title="迁移为单层原视频画面"),
    )
    assert migrated.current_revision == 2
    assert migrated.plan.layout is Layout.CENTER_CROP
    assert "approve" in migrated.allowed_actions
    assert "render_proxy" in migrated.allowed_actions
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ReviewDecisionRow)) == 0


def test_stale_expected_revision_rolls_back_without_partial_revision_or_decision(
    review_context: tuple[Engine, ReviewService, str, str, str],
) -> None:
    engine, service, clip_id, _, _ = review_context
    service.revise_and_review(
        clip_id,
        ClipPatch(expected_revision=1, title="第一次有效修改"),
        ReviewCommand(expected_revision=1, status=ReviewStatus.APPROVED),
    )

    with pytest.raises(ReviewConflict, match="revision changed"):
        service.revise_and_review(
            clip_id,
            ClipPatch(expected_revision=1, title="过期写入不得生效"),
            ReviewCommand(
                expected_revision=1,
                status=ReviewStatus.REJECTED,
                reason="过期决定",
            ),
        )

    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(EditPlanRevisionRow)) == 2
        assert connection.scalar(select(func.count()).select_from(ReviewDecisionRow)) == 1
        assert connection.scalar(select(ProjectRow.revision_epoch)) == 1
        current = connection.execute(
            select(EditPlanRevisionRow.title)
            .join(CandidateClipRow, CandidateClipRow.id == EditPlanRevisionRow.candidate_clip_id)
            .where(EditPlanRevisionRow.revision == CandidateClipRow.current_revision)
        ).scalar_one()
        assert current == "第一次有效修改"


def test_batch_review_is_atomic_revision_fenced_and_idempotent(
    review_context: tuple[Engine, ReviewService, str, str, str],
) -> None:
    engine, service, clip_id, _, _ = review_context
    project_id = "project0000000000000000000000001"
    run_id = "run00000000000000000000000000001"
    second_clip_id = "clip0000000000000000000000000002"
    second_revision_id = "revision00000000000000000000002"
    second_plan = EditPlan(
        candidate_id=second_clip_id,
        source_start_ms=8_000,
        source_end_ms=16_000,
        score=82,
        title="第二个批量审核候选",
        hook="第二个完整开场",
        reason="用于验证批量审核整体事务",
        layout=Layout.CENTER_CROP,
        caption_template=CaptionTemplate.CLEAN_ZH_V1,
        effect=Effect.NONE,
        risk_flags=(),
        prompt_version="editing_v1",
        model="mock-llm-v1",
        degraded=True,
    )
    with engine.begin() as connection:
        connection.execute(
            insert(CandidateClipRow).values(
                id=second_clip_id,
                project_id=project_id,
                pipeline_run_id=run_id,
                candidate_key="candidate-2",
                source_start_ms=8_000,
                source_end_ms=16_000,
                allowed_start_ms=5_000,
                allowed_end_ms=19_000,
                transcript_text="第二个候选的完整中文转写。",
                context_before="前文",
                context_after="后文",
                rule_score=82,
                reasons_json=["表达完整"],
                segment_ids_json=[],
                current_revision=1,
                rank=2,
                selected_for_review=True,
            )
        )
        connection.execute(
            insert(EditPlanRevisionRow).values(
                id=second_revision_id,
                candidate_clip_id=second_clip_id,
                revision=1,
                parent_revision=None,
                origin="deterministic",
                source_start_ms=second_plan.source_start_ms,
                source_end_ms=second_plan.source_end_ms,
                score=second_plan.score,
                title=second_plan.title,
                hook=second_plan.hook,
                reason=second_plan.reason,
                layout=second_plan.layout.value,
                caption_template=second_plan.caption_template.value,
                effect=second_plan.effect.value,
                risk_flags_json=[],
                prompt_version=second_plan.prompt_version,
                model=second_plan.model,
                degraded=second_plan.degraded,
                plan_json=second_plan.model_dump(mode="json"),
            )
        )
        connection.execute(
            insert(CaptionCueRow).values(
                id="caption0000000000000000000000002",
                edit_plan_revision_id=second_revision_id,
                cue_index=0,
                start_ms=0,
                end_ms=8_000,
                text="第二个候选的完整中文转写。",
            )
        )

    stale_batch = BatchReviewCommand(
        items=(
            BatchReviewItem(
                clip_id=clip_id,
                expected_revision=1,
                status=ReviewStatus.APPROVED,
            ),
            BatchReviewItem(
                clip_id=second_clip_id,
                expected_revision=2,
                status=ReviewStatus.REJECTED,
                reason="待补充上下文",
            ),
        )
    )
    with pytest.raises(ReviewConflict, match="revision changed"):
        service.review_clips_batch(project_id, stale_batch)
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ReviewDecisionRow)) == 0

    valid_batch = BatchReviewCommand(
        items=(
            BatchReviewItem(
                clip_id=clip_id,
                expected_revision=1,
                status=ReviewStatus.APPROVED,
            ),
            BatchReviewItem(
                clip_id=second_clip_id,
                expected_revision=1,
                status=ReviewStatus.REJECTED,
                reason="待补充上下文",
            ),
        )
    )
    idempotency = build_idempotency_context(
        raw_key="batch-review-atomic-001",
        caller_scope="test",
        operation_scope="POST:/api/v1/projects/:project_id/reviews/batch",
        request_payload=valid_batch.model_dump(mode="json"),
    )
    first = service.review_clips_batch(project_id, valid_batch, idempotency=idempotency)
    replay = service.review_clips_batch(project_id, valid_batch, idempotency=idempotency)

    assert [detail.review.status for detail in first] == [
        ReviewStatus.APPROVED,
        ReviewStatus.REJECTED,
    ]
    assert [detail.review.status for detail in replay] == [
        ReviewStatus.APPROVED,
        ReviewStatus.REJECTED,
    ]
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ReviewDecisionRow)) == 2


def test_malicious_title_is_revalidated_and_all_mutations_roll_back(
    review_context: tuple[Engine, ReviewService, str, str, str],
) -> None:
    engine, service, clip_id, _, task_id = review_context

    with pytest.raises(ValidationError, match="executable"):
        service.revise_and_review(
            clip_id,
            ClipPatch(expected_revision=1, title="ffmpeg -i /tmp/source.mp4"),
            ReviewCommand(expected_revision=1, status=ReviewStatus.APPROVED),
        )

    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(EditPlanRevisionRow)) == 1
        assert connection.scalar(select(func.count()).select_from(ReviewDecisionRow)) == 0
        assert connection.scalar(select(CandidateClipRow.current_revision)) == 1
        assert connection.scalar(select(ProjectRow.revision_epoch)) == 0
        assert connection.scalar(select(RenderJobRow.status)) == RenderStatus.QUEUED.value
        assert connection.scalar(select(TaskRow.status).where(TaskRow.id == task_id)) == (
            TaskStatus.QUEUED.value
        )


def test_revision_epoch_cancels_other_clip_inflight_render(
    review_context: tuple[Engine, ReviewService, str, str, str],
) -> None:
    engine, service, clip_id, _, _ = review_context
    second_clip_id = "clip0000000000000000000000000002"
    second_revision_id = "revision00000000000000000000002"
    second_task_id = "task0000000000000000000000000002"
    second_render_id = "render0000000000000000000000002"
    plan = EditPlan(
        candidate_id=second_clip_id,
        source_start_ms=8_000,
        source_end_ms=16_000,
        score=82,
        title="第二个候选标题",
        hook="第二个完整开场",
        reason="第二个候选用于跨片段围栏测试",
        layout=Layout.CENTER_CROP,
        caption_template=CaptionTemplate.CLEAN_ZH_V1,
        effect=Effect.NONE,
        risk_flags=(),
        prompt_version="editing_v1",
        model="mock-llm-v1",
        degraded=True,
    )
    with engine.begin() as connection:
        run_id = connection.scalar(select(PipelineRunRow.id))
        project_id = connection.scalar(select(ProjectRow.id))
        connection.execute(
            insert(CandidateClipRow).values(
                id=second_clip_id,
                project_id=project_id,
                pipeline_run_id=run_id,
                candidate_key="candidate-2",
                source_start_ms=8_000,
                source_end_ms=16_000,
                allowed_start_ms=5_000,
                allowed_end_ms=19_000,
                transcript_text="第二段完整中文转写。",
                context_before="前文",
                context_after="后文",
                rule_score=82,
                reasons_json=["表达完整"],
                segment_ids_json=[],
                current_revision=1,
                rank=2,
                selected_for_review=True,
            )
        )
        connection.execute(
            insert(EditPlanRevisionRow).values(
                id=second_revision_id,
                candidate_clip_id=second_clip_id,
                revision=1,
                parent_revision=None,
                origin="deterministic",
                source_start_ms=plan.source_start_ms,
                source_end_ms=plan.source_end_ms,
                score=plan.score,
                title=plan.title,
                hook=plan.hook,
                reason=plan.reason,
                layout=plan.layout.value,
                caption_template=plan.caption_template.value,
                effect=plan.effect.value,
                risk_flags_json=[],
                prompt_version=plan.prompt_version,
                model=plan.model,
                degraded=plan.degraded,
                plan_json=plan.model_dump(mode="json"),
            )
        )
        connection.execute(
            insert(TaskRow).values(
                id=second_task_id,
                kind=TaskKind.RENDER.value,
                target_id=second_clip_id,
                operation_key=f"render:{second_clip_id}:r001",
                input_fingerprint="c" * 64,
                resource_class=ResourceClass.HEAVY.value,
                pipeline_run_id=run_id,
                status=TaskStatus.QUEUED.value,
                priority=800,
                expected_generation=1,
                expected_revision=1,
                expected_revision_epoch=0,
                attempt_count=0,
                retry_count=0,
                manual_retry_count=0,
                max_retries=1,
            )
        )
        connection.execute(
            insert(RenderJobRow).values(
                id=second_render_id,
                candidate_clip_id=second_clip_id,
                edit_plan_revision_id=second_revision_id,
                task_id=second_task_id,
                kind="final",
                status=RenderStatus.QUEUED.value,
                edit_plan_revision=1,
                revision_epoch=0,
                width=270,
                height=480,
                spec_fingerprint="c" * 64,
                spec_json={"schema_version": "1"},
            )
        )

    service.revise_clip(clip_id, ClipPatch(expected_revision=1, title="触发全局围栏更新"))

    with engine.connect() as connection:
        render_status = connection.scalar(
            select(RenderJobRow.status).where(RenderJobRow.id == second_render_id)
        )
        task = connection.execute(
            select(TaskRow.status, TaskRow.cancellation_requested_at).where(
                TaskRow.id == second_task_id
            )
        ).one()
    assert render_status == RenderStatus.STALE.value
    assert task.status == TaskStatus.CANCELLED.value
    assert task.cancellation_requested_at is not None

    queued = RenderService(
        SqlAlchemyRenderRepository(engine),
        RenderProfile(
            preview_width=270,
            preview_height=480,
            final_width=1_080,
            final_height=1_920,
            encoder="libx264",
            max_retries=1,
        ),
    ).enqueue(
        second_clip_id,
        RenderRequest(expected_revision=1, kind="proxy"),
    )

    assert queued.render_id != second_render_id
    assert queued.task_id != second_task_id
    assert queued.status == RenderStatus.QUEUED
    with engine.connect() as connection:
        replacement = connection.execute(
            select(
                RenderJobRow.revision_epoch,
                TaskRow.expected_revision_epoch,
                TaskRow.status,
            )
            .join(TaskRow, TaskRow.id == RenderJobRow.task_id)
            .where(RenderJobRow.id == queued.render_id)
        ).one()
    assert tuple(replacement) == (1, 1, TaskStatus.QUEUED.value)


def test_revision_change_fails_queued_delivery_snapshot_without_worker(
    review_context: tuple[Engine, ReviewService, str, str, str],
) -> None:
    engine, service, clip_id, _, _ = review_context
    delivery_id = "delivery000000000000000000000001"
    delivery_task_id = "deltask0000000000000000000000001"
    running_delivery_id = "delivery000000000000000000000002"
    running_task_id = "deltask0000000000000000000000002"
    heartbeat_at = datetime.now(UTC)
    with engine.begin() as connection:
        project_id = str(connection.scalar(select(ProjectRow.id)))
        run_id = str(connection.scalar(select(PipelineRunRow.id)))
        connection.execute(
            insert(TaskRow).values(
                id=delivery_task_id,
                kind=TaskKind.DELIVERY.value,
                target_id=delivery_id,
                operation_key=f"delivery:{project_id}:v001",
                input_fingerprint="d" * 64,
                resource_class=ResourceClass.HEAVY.value,
                pipeline_run_id=run_id,
                status=TaskStatus.QUEUED.value,
                priority=700,
                expected_generation=1,
                expected_revision_epoch=0,
                attempt_count=0,
                retry_count=0,
                manual_retry_count=0,
                max_retries=1,
            )
        )
        connection.execute(
            insert(DeliveryRow).values(
                id=delivery_id,
                project_id=project_id,
                task_id=delivery_task_id,
                version=1,
                status=DeliveryStatus.QUEUED.value,
                expected_revision_epoch=0,
                snapshot_fingerprint="e" * 64,
                directory_relative_path="deliveries/v001",
                include_zip=True,
                expected_generation=1,
            )
        )
        connection.execute(
            insert(TaskRow).values(
                id=running_task_id,
                kind=TaskKind.DELIVERY.value,
                target_id=running_delivery_id,
                operation_key=f"delivery:{project_id}:v002",
                input_fingerprint="f" * 64,
                resource_class=ResourceClass.HEAVY.value,
                pipeline_run_id=run_id,
                status=TaskStatus.RUNNING.value,
                priority=700,
                expected_generation=1,
                expected_revision_epoch=0,
                attempt_count=1,
                retry_count=0,
                manual_retry_count=0,
                max_retries=1,
                worker_id="delivery-worker",
                lease_token="active-delivery-lease-token",
                heartbeat_at=heartbeat_at,
                lease_expires_at=heartbeat_at + timedelta(seconds=30),
            )
        )
        connection.execute(
            insert(DeliveryRow).values(
                id=running_delivery_id,
                project_id=project_id,
                task_id=running_task_id,
                version=2,
                status=DeliveryStatus.CREATING.value,
                expected_revision_epoch=0,
                snapshot_fingerprint="f" * 64,
                directory_relative_path="deliveries/v002",
                include_zip=True,
                expected_generation=1,
            )
        )

    service.revise_clip(clip_id, ClipPatch(expected_revision=1, title="交付快照失效测试"))

    with engine.connect() as connection:
        delivery = connection.execute(
            select(
                DeliveryRow.status,
                DeliveryRow.error_code,
                DeliveryRow.safe_error_message,
                DeliveryRow.completed_at,
            ).where(DeliveryRow.id == delivery_id)
        ).one()
        task = connection.execute(
            select(
                TaskRow.status,
                TaskRow.cancellation_requested_at,
                TaskRow.failure_class,
                TaskRow.error_code,
                TaskRow.completed_at,
            ).where(TaskRow.id == delivery_task_id)
        ).one()
        running_delivery = connection.execute(
            select(DeliveryRow.status, DeliveryRow.error_code, DeliveryRow.completed_at).where(
                DeliveryRow.id == running_delivery_id
            )
        ).one()
        running_task = connection.execute(
            select(
                TaskRow.status,
                TaskRow.cancellation_requested_at,
                TaskRow.worker_id,
                TaskRow.lease_token,
                TaskRow.failure_class,
                TaskRow.error_code,
            ).where(TaskRow.id == running_task_id)
        ).one()
    assert delivery.status == DeliveryStatus.FAILED.value
    assert delivery.error_code == "DELIVERY_SNAPSHOT_STALE"
    assert delivery.safe_error_message is not None
    assert delivery.completed_at is not None
    assert task.status == TaskStatus.CANCELLED.value
    assert task.cancellation_requested_at is not None
    assert task.failure_class == FailureClass.DETERMINISTIC.value
    assert task.error_code == "DELIVERY_SNAPSHOT_STALE"
    assert task.completed_at is not None
    assert tuple(running_delivery)[:2] == (
        DeliveryStatus.FAILED.value,
        "DELIVERY_SNAPSHOT_STALE",
    )
    assert running_delivery.completed_at is not None
    assert running_task.status == TaskStatus.RUNNING.value
    assert running_task.cancellation_requested_at is not None
    assert running_task.worker_id == "delivery-worker"
    assert running_task.lease_token == "active-delivery-lease-token"
    assert running_task.failure_class == FailureClass.DETERMINISTIC.value
    assert running_task.error_code == "DELIVERY_SNAPSHOT_STALE"


def test_review_decision_change_invalidates_only_active_delivery_snapshots(
    review_context: tuple[Engine, ReviewService, str, str, str],
) -> None:
    engine, service, clip_id, _, _ = review_context
    service.review_clip(
        clip_id,
        ReviewCommand(expected_revision=1, status=ReviewStatus.APPROVED),
    )
    delivery_id = "delivery000000000000000000000003"
    delivery_task_id = "deltask0000000000000000000000003"
    succeeded_delivery_id = "delivery000000000000000000000004"
    with engine.begin() as connection:
        project_id = str(connection.scalar(select(ProjectRow.id)))
        run_id = str(connection.scalar(select(PipelineRunRow.id)))
        connection.execute(
            insert(TaskRow).values(
                id=delivery_task_id,
                kind=TaskKind.DELIVERY.value,
                target_id=delivery_id,
                operation_key=f"delivery:{project_id}:decision:v001",
                input_fingerprint="1" * 64,
                resource_class=ResourceClass.HEAVY.value,
                pipeline_run_id=run_id,
                status=TaskStatus.QUEUED.value,
                priority=700,
                expected_generation=1,
                expected_revision_epoch=0,
                attempt_count=0,
                retry_count=0,
                manual_retry_count=0,
                max_retries=1,
            )
        )
        connection.execute(
            insert(DeliveryRow).values(
                id=delivery_id,
                project_id=project_id,
                task_id=delivery_task_id,
                version=1,
                status=DeliveryStatus.QUEUED.value,
                expected_revision_epoch=0,
                snapshot_fingerprint="2" * 64,
                directory_relative_path="deliveries/v001",
                include_zip=True,
                expected_generation=1,
            )
        )
        connection.execute(
            insert(DeliveryRow).values(
                id=succeeded_delivery_id,
                project_id=project_id,
                version=2,
                status=DeliveryStatus.SUCCEEDED.value,
                expected_revision_epoch=0,
                snapshot_fingerprint="3" * 64,
                directory_relative_path="deliveries/v002",
                include_zip=False,
                expected_generation=1,
                completed_at=datetime.now(UTC),
            )
        )

    service.review_clip(
        clip_id,
        ReviewCommand(
            expected_revision=1,
            status=ReviewStatus.REJECTED,
            reason="该片段不再进入交付",
        ),
    )

    with engine.connect() as connection:
        active = connection.execute(
            select(DeliveryRow.status, DeliveryRow.error_code, DeliveryRow.completed_at).where(
                DeliveryRow.id == delivery_id
            )
        ).one()
        succeeded = connection.scalar(
            select(DeliveryRow.status).where(DeliveryRow.id == succeeded_delivery_id)
        )
        task = connection.execute(
            select(TaskRow.status, TaskRow.cancellation_requested_at).where(
                TaskRow.id == delivery_task_id
            )
        ).one()
    assert active.status == DeliveryStatus.FAILED.value
    assert active.error_code == "DELIVERY_SNAPSHOT_STALE"
    assert active.completed_at is not None
    assert succeeded == DeliveryStatus.SUCCEEDED.value
    assert task.status == TaskStatus.CANCELLED.value
    assert task.cancellation_requested_at is not None
