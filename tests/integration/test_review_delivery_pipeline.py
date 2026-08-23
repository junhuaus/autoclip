from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select, update

from liveclip.application.deliveries import DeliveryConflict, DeliveryRequest, DeliveryService
from liveclip.application.delivery_runner import DeliveryTaskRunner
from liveclip.application.idempotency import build_idempotency_context
from liveclip.application.pipeline import LeaseIdentity, PipelineRunConfig, PipelineService
from liveclip.application.render_runner import RenderTaskRunner
from liveclip.application.rendering import (
    RenderConflict,
    RenderProfile,
    RenderService,
    render_asset_paths,
)
from liveclip.application.reviewing import ClipPatch, RenderRequest, ReviewCommand, ReviewService
from liveclip.application.stage_runner import StageTaskRunner
from liveclip.db.assets import SqlAlchemyAssetStore
from liveclip.db.base import Base
from liveclip.db.delivery_repository import SqlAlchemyDeliveryRepository
from liveclip.db.delivery_snapshot import load_eligible_delivery_set
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import AssetRow, DeliveryRow, RenderJobRow, TaskAttemptRow, TaskRow
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.render_repository import SqlAlchemyRenderRepository
from liveclip.db.review_repository import SqlAlchemyReviewRepository
from liveclip.db.stage_store import SqlAlchemyStageStateStore
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.delivery.task_handler import DeliveryTaskHandler
from liveclip.domain.state_transitions import (
    AssetStatus,
    DeliveryStatus,
    FailureClass,
    ProjectStatus,
    RenderStatus,
    ReviewStatus,
    TaskKind,
    TaskStatus,
)
from liveclip.pipeline.stage_handlers import PipelineStageHandlers
from liveclip.renderer.quality import probe_media
from liveclip.renderer.task_handler import RenderTaskHandler
from liveclip.services.demo_media import create_demo_source


@pytest.mark.integration
def test_persistent_preapproval_master_and_delivery_reuse_flow(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    source_path = media_root / "source.mp4"
    data_dir = tmp_path / "projects"
    create_demo_source(output_path=source_path, duration_ms=16_000)
    engine = create_sqlite_engine(tmp_path / "liveclip.sqlite3")
    Base.metadata.create_all(engine)
    pipeline_repository = SqlAlchemyPipelineRepository(engine)
    pipeline_service = PipelineService(pipeline_repository)
    queue = SQLiteTaskQueue(engine, lease_seconds=30)
    assets = SqlAlchemyAssetStore(engine)
    stage_runner = StageTaskRunner(
        queue=queue,
        repository=pipeline_repository,
        pipeline_service=pipeline_service,
        handler=PipelineStageHandlers(
            data_dir=data_dir,
            allowed_media_roots=(media_root,),
            assets=assets,
            state=SqlAlchemyStageStateStore(engine),
        ),
        heartbeat_seconds=5,
    )
    render_repository = SqlAlchemyRenderRepository(engine)
    render_service = RenderService(
        render_repository,
        RenderProfile(
            preview_width=270,
            preview_height=480,
            final_width=270,
            final_height=480,
            encoder="libx264",
            max_retries=1,
        ),
    )
    render_handler = RenderTaskHandler(data_dir=data_dir, assets=assets)
    render_runner = RenderTaskRunner(
        queue=queue,
        repository=render_repository,
        handler=render_handler,
        heartbeat_seconds=5,
    )
    delivery_repository = SqlAlchemyDeliveryRepository(engine)
    delivery_service = DeliveryService(delivery_repository, max_retries=1)
    delivery_runner = DeliveryTaskRunner(
        queue=queue,
        repository=delivery_repository,
        handler=DeliveryTaskHandler(data_dir=data_dir, assets=assets),
        heartbeat_seconds=5,
    )
    review_service = ReviewService(SqlAlchemyReviewRepository(engine))
    try:
        created = pipeline_service.create_project_and_run(
            source_path=source_path.resolve(),
            config=PipelineRunConfig(
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
            ),
            max_stage_retries=1,
        )
        stage_runner.run_until_terminal(created.run_id, worker_id="pipeline-worker")
        clip_id = pipeline_service.get_project(created.project_id).project_id
        with engine.connect() as connection:
            clip_id = str(
                connection.scalar(
                    select(RenderJobRow.candidate_clip_id).where(RenderJobRow.kind == "proxy")
                )
            )
        initial = review_service.get_clip(clip_id)
        assert initial.current_revision == 1
        assert any(render.status == RenderStatus.SUCCEEDED for render in initial.renders)

        with engine.begin() as connection:
            pipeline_master = connection.execute(
                select(
                    RenderJobRow.id,
                    RenderJobRow.task_id,
                    RenderJobRow.spec_fingerprint,
                    RenderJobRow.asset_id,
                    RenderJobRow.subtitle_asset_id,
                    RenderJobRow.quality_report_asset_id,
                    RenderJobRow.contact_sheet_asset_id,
                ).where(
                    RenderJobRow.candidate_clip_id == clip_id,
                    RenderJobRow.kind == "proxy",
                    RenderJobRow.status == RenderStatus.SUCCEEDED.value,
                )
            ).one()
            pipeline_asset_ids = tuple(
                str(asset_id)
                for asset_id in (
                    pipeline_master.asset_id,
                    pipeline_master.subtitle_asset_id,
                    pipeline_master.quality_report_asset_id,
                    pipeline_master.contact_sheet_asset_id,
                )
            )
            pipeline_asset_fingerprints = tuple(
                connection.scalars(
                    select(AssetRow.input_fingerprint).where(AssetRow.id.in_(pipeline_asset_ids))
                )
            )
            assert set(pipeline_asset_fingerprints) == {pipeline_master.spec_fingerprint}
            historical_task_fingerprint = connection.scalar(
                select(TaskRow.input_fingerprint).where(TaskRow.id == pipeline_master.task_id)
            )
            assert historical_task_fingerprint is not None
            assert historical_task_fingerprint != pipeline_master.spec_fingerprint
            connection.execute(
                update(AssetRow)
                .where(AssetRow.id.in_(pipeline_asset_ids))
                .values(input_fingerprint=historical_task_fingerprint)
            )
        review_service.review_clip(
            clip_id,
            ReviewCommand(expected_revision=1, status=ReviewStatus.APPROVED),
        )
        with engine.connect() as connection:
            historical_pipeline_snapshot = load_eligible_delivery_set(
                connection,
                created.project_id,
            )
        assert len(historical_pipeline_snapshot.clips) == 1
        assert historical_pipeline_snapshot.clips[0].render_job_id == pipeline_master.id

        revised = review_service.revise_clip(
            clip_id,
            ClipPatch(expected_revision=1, title="人工确认后的高光标题"),
        )
        assert revised.current_revision == 2
        assert revised.review.status == ReviewStatus.PENDING_REVIEW
        assert {render.status for render in revised.renders} == {RenderStatus.STALE}
        queued_render = render_service.enqueue(
            clip_id,
            RenderRequest(expected_revision=2, kind="proxy"),
            idempotency=build_idempotency_context(
                raw_key="integration-delivery-master-render",
                caller_scope="local-test",
                operation_scope="POST:/api/v1/clips/render",
                request_payload={
                    "clip_id": clip_id,
                    "expected_revision": 2,
                    "kind": "proxy",
                },
            ),
        )
        replayed_render = render_service.enqueue(
            clip_id,
            RenderRequest(expected_revision=2, kind="proxy"),
            idempotency=build_idempotency_context(
                raw_key="integration-delivery-master-render",
                caller_scope="local-test",
                operation_scope="POST:/api/v1/clips/render",
                request_payload={
                    "clip_id": clip_id,
                    "expected_revision": 2,
                    "kind": "proxy",
                },
            ),
        )
        assert replayed_render.render_id == queued_render.render_id
        master_render = render_runner.run_until_terminal(
            queued_render.render_id,
            worker_id="render-worker",
        )
        assert master_render.status == RenderStatus.SUCCEEDED
        detail = review_service.get_clip(clip_id)
        current_master = next(
            render
            for render in detail.renders
            if render.kind == "proxy" and render.edit_plan_revision == 2
        )
        assert current_master.video_asset_id is not None
        assert current_master.subtitle_asset_id is not None
        assert not any(
            render.kind == "final" and render.edit_plan_revision == 2 for render in detail.renders
        )
        approved = review_service.review_clip(
            clip_id,
            ReviewCommand(expected_revision=2, status=ReviewStatus.APPROVED),
        )
        assert approved.review.status == ReviewStatus.APPROVED

        delivery_context = build_idempotency_context(
            raw_key="integration-delivery",
            caller_scope="local-test",
            operation_scope="POST:/api/v1/projects/deliveries",
            request_payload={"project_id": created.project_id, "include_zip": True},
        )
        queued_delivery = delivery_service.enqueue(
            created.project_id,
            DeliveryRequest(include_zip=True),
            idempotency=delivery_context,
        )
        replayed_delivery = delivery_service.enqueue(
            created.project_id,
            DeliveryRequest(include_zip=True),
            idempotency=delivery_context,
        )
        assert replayed_delivery.delivery_id == queued_delivery.delivery_id
        assert replayed_delivery.version == 1
        delivery = delivery_runner.run_until_terminal(
            queued_delivery.delivery_id,
            worker_id="delivery-worker",
        )
        assert delivery.status == DeliveryStatus.SUCCEEDED
        assert delivery.delivery_version == "v001"
        project_dir = data_dir / created.project_id
        manifest_path = project_dir / "deliveries" / "v001" / "manifest.json"
        zip_path = project_dir / "deliveries" / "v001" / "delivery.zip"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["delivery_id"] == delivery.delivery_id
        assert manifest["delivery_version"] == "v001"
        assert manifest["snapshot_fingerprint"]
        assert len(manifest["clips"]) == 1
        assert manifest["clips"][0]["hook"]
        assert manifest["clips"][0]["reason"]
        assert manifest["clips"][0]["keywords"]
        index_html = (project_dir / "deliveries" / "v001" / "index.html").read_text(
            encoding="utf-8"
        )
        assert "高光语句" in index_html
        assert "编辑关键词" in index_html
        assert zip_path.is_file()
        with zipfile.ZipFile(zip_path) as archive:
            assert archive.testzip() is None
        video_path = project_dir / "deliveries" / "v001" / manifest["clips"][0]["video_filename"]
        video_stream = next(
            stream
            for stream in probe_media(video_path)["streams"]
            if stream.get("codec_type") == "video"
        )
        assert (video_stream["width"], video_stream["height"]) == (270, 480)
        master_relative_path = None
        with engine.connect() as connection:
            master_relative_path = connection.scalar(
                select(AssetRow.relative_path).where(AssetRow.id == current_master.video_asset_id)
            )
        assert isinstance(master_relative_path, str)
        assert video_path.stat().st_ino != (project_dir / master_relative_path).stat().st_ino
        assert pipeline_service.get_project(created.project_id).status == ProjectStatus.DELIVERED

        second_delivery = delivery_service.enqueue(
            created.project_id,
            DeliveryRequest(include_zip=True),
            idempotency=build_idempotency_context(
                raw_key="integration-delivery-v002",
                caller_scope="local-test",
                operation_scope="POST:/api/v1/projects/deliveries",
                request_payload={
                    "project_id": created.project_id,
                    "include_zip": True,
                    "request": 2,
                },
            ),
        )
        completed_second = delivery_runner.run_until_terminal(
            second_delivery.delivery_id,
            worker_id="delivery-worker-v2",
        )
        assert completed_second.status == DeliveryStatus.SUCCEEDED
        assert completed_second.delivery_version == "v002"
        with engine.connect() as connection:
            delivery_fingerprints = connection.execute(
                select(DeliveryRow.snapshot_fingerprint, TaskRow.input_fingerprint)
                .join(TaskRow, TaskRow.id == DeliveryRow.task_id)
                .where(DeliveryRow.project_id == created.project_id)
                .order_by(DeliveryRow.version)
            ).all()
        assert delivery_fingerprints[0][0] == delivery_fingerprints[1][0]
        assert delivery_fingerprints[0][1] != delivery_fingerprints[1][1]
        assert pipeline_service.get_project(created.project_id).status == ProjectStatus.DELIVERED

        failed_third = delivery_service.enqueue(
            created.project_id,
            DeliveryRequest(include_zip=True),
        )
        failed_lease = queue.claim(worker_id="delivery-failure", task_kind=TaskKind.DELIVERY)
        assert failed_lease is not None and failed_lease.task_id == failed_third.task_id
        assert (
            queue.fail(
                failed_lease,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="INJECTED_DELIVERY_FAILURE",
                safe_message="Injected deterministic package failure",
            )
            == TaskStatus.FAILED
        )
        assert delivery_service.get(failed_third.delivery_id).status == DeliveryStatus.FAILED
        assert pipeline_service.get_project(created.project_id).status == ProjectStatus.DELIVERED

        review_service.review_clip(
            clip_id,
            ReviewCommand(
                expected_revision=2,
                status=ReviewStatus.REJECTED,
                reason="复核后不采用",
            ),
        )
        assert (
            pipeline_service.get_project(created.project_id).status == ProjectStatus.PENDING_REVIEW
        )
        with pytest.raises(DeliveryConflict, match="at least one approved clip"):
            delivery_service.enqueue(
                created.project_id,
                DeliveryRequest(include_zip=True),
            )
        with engine.connect() as connection:
            assert set(connection.scalars(select(AssetRow.status))) == {AssetStatus.COMMITTED.value}

        revised_again = review_service.revise_clip(
            clip_id,
            ClipPatch(expected_revision=2, title="完整性检查 revision"),
        )
        assert revised_again.current_revision == 3
        integrity_render = render_service.enqueue(
            clip_id,
            RenderRequest(expected_revision=3, kind="proxy"),
        )
        integrity_lease = queue.claim(worker_id="render-integrity", task_kind=TaskKind.RENDER)
        assert integrity_lease is not None
        assert integrity_lease.task_id == integrity_render.task_id
        integrity_identity = LeaseIdentity(
            task_id=integrity_lease.task_id,
            worker_id=integrity_lease.worker_id,
            lease_token=integrity_lease.lease_token,
        )
        integrity_work = render_repository.start_render(integrity_identity)
        integrity_persistence = render_handler.execute(
            integrity_work,
            integrity_identity,
            cancel_requested=lambda: False,
        )
        paths = render_asset_paths(integrity_work)
        with engine.connect() as connection:
            current_attempt_id = str(
                connection.scalar(
                    select(TaskAttemptRow.id).where(
                        TaskAttemptRow.task_id == integrity_lease.task_id
                    )
                )
            )
            other_attempt_id = str(
                connection.scalar(
                    select(TaskAttemptRow.id)
                    .where(TaskAttemptRow.task_id != integrity_lease.task_id)
                    .limit(1)
                )
            )
        with engine.begin() as connection:
            connection.execute(
                update(AssetRow)
                .where(AssetRow.id == integrity_persistence.video_asset_id)
                .values(producer_attempt_id=other_attempt_id)
            )
        with pytest.raises(RenderConflict, match="another task"):
            render_repository.complete_render(
                integrity_identity,
                integrity_work,
                integrity_persistence,
            )
        with engine.begin() as connection:
            connection.execute(
                update(AssetRow)
                .where(AssetRow.id == integrity_persistence.video_asset_id)
                .values(producer_attempt_id=current_attempt_id)
            )
            connection.execute(
                update(AssetRow)
                .where(AssetRow.id == integrity_persistence.subtitle_asset_id)
                .values(relative_path=f"{paths.subtitle}.tampered")
            )
        with pytest.raises(RenderConflict, match="paths are invalid"):
            render_repository.complete_render(
                integrity_identity,
                integrity_work,
                integrity_persistence,
            )
        with engine.begin() as connection:
            connection.execute(
                update(AssetRow)
                .where(AssetRow.id == integrity_persistence.subtitle_asset_id)
                .values(relative_path=paths.subtitle)
            )
        source_stat = source_path.stat()
        os.utime(
            source_path,
            ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns + 1_000_000),
        )
        with pytest.raises(RenderConflict, match="source media changed"):
            render_repository.complete_render(
                integrity_identity,
                integrity_work,
                integrity_persistence,
            )
        os.utime(source_path, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
        assert render_repository.complete_render(
            integrity_identity,
            integrity_work,
            integrity_persistence,
        )
    finally:
        engine.dispose(close=True)
