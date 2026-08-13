# ruff: noqa: RUF001
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine

from liveclip.application.clips import ClipQueryService
from liveclip.application.media_assets import MediaAssetService
from liveclip.application.offline_review import (
    OfflineReviewClipObservation,
    OfflineReviewPackageConflict,
    OfflineReviewPackageService,
)
from liveclip.application.pipeline import (
    PipelineRunConfig,
    PipelineService,
    ProjectSnapshot,
    WorkspaceMember,
)
from liveclip.db.base import Base
from liveclip.db.clip_repository import SqlAlchemyClipQueryRepository
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.media_repository import SqlAlchemyMediaAssetRepository
from liveclip.db.models import (
    ApiUsageRow,
    AssetRow,
    CandidateClipRow,
    CaptionCueRow,
    DeliveryRow,
    EditPlanRevisionRow,
    PipelineRunRow,
    ProjectMemberRow,
    ProjectRow,
    RenderJobRow,
    ReviewDecisionRow,
    SourceMediaRow,
    TaskAttemptRow,
    TaskRow,
    WorkspaceUserRow,
)
from liveclip.db.offline_review_repository import SqlAlchemyOfflineReviewFenceRepository
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.domain.edit_plan import CaptionTemplate, EditPlan, Effect, Layout
from liveclip.domain.state_transitions import (
    AssetStatus,
    AttemptOutcome,
    PipelineRunStatus,
    ProjectStatus,
    RenderStatus,
    ResourceClass,
    ReviewStatus,
    TaskKind,
    TaskStatus,
)
from liveclip.media.fingerprint import stream_sha256
from liveclip.media.models import SourceMediaMetadata
from liveclip.renderer.contracts import (
    FFMPEG_RENDERER_CONTRACT_VERSION,
    RENDER_SPEC_SCHEMA_VERSION,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
PROJECT_ID = "1" * 32
RUN_ID = "2" * 32
CLIP_ID = "3" * 32
REVISION_ID = "4" * 32
RENDER_ID = "5" * 32
ASSET_ID = "6" * 32
TASK_ID = "7" * 32
ATTEMPT_ID = "8" * 32
SPEC_FINGERPRINT = "b" * 64


@dataclass(frozen=True)
class OfflineReviewFixture:
    engine: Engine
    data_dir: Path
    source: SourceMediaMetadata
    proxy_path: Path

    @property
    def project(self) -> ProjectSnapshot:
        owner = WorkspaceMember(
            user_id="local-admin",
            username="local-admin",
            display_name="本机管理员",
            role="owner",
        )
        return ProjectSnapshot(
            project_id=PROJECT_ID,
            name="离线审核测试",
            source_filename=self.source.filename,
            status=ProjectStatus.PENDING_REVIEW,
            current_run_id=RUN_ID,
            generation=1,
            owner=owner,
            members=(owner,),
            current_user_role="owner",
        )

    @property
    def observation(self) -> OfflineReviewClipObservation:
        return OfflineReviewClipObservation(
            clip_id=CLIP_ID,
            edit_plan_revision=1,
            review_status=ReviewStatus.PENDING_REVIEW,
            proxy_asset_id=ASSET_ID,
            proxy_sha256=stream_sha256(self.proxy_path),
            proxy_size_bytes=self.proxy_path.stat().st_size,
        )


@pytest.fixture
def offline_review_fixture(tmp_path: Path) -> OfflineReviewFixture:
    data_dir = tmp_path / "projects"
    project_dir = data_dir / PROJECT_ID
    proxy_path = project_dir / "generations/g001/renders/proxies/clip/r001/review.mp4"
    proxy_path.parent.mkdir(parents=True)
    proxy_path.write_bytes(b"verified-clean-review-proxy" * 2_000)
    source_path = tmp_path / "media/source.mp4"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"source")
    source = SourceMediaMetadata(
        resolved_path=source_path.resolve(),
        filename="source.mp4",
        size_bytes=source_path.stat().st_size,
        sha256="a" * 64,
        duration_ms=20_000,
        format_name="mov,mp4",
        video_stream_index=0,
        video_codec="h264",
        video_width=1_920,
        video_height=1_080,
        video_frame_rate=30.0,
        video_rotation_degrees=0,
        audio_stream_index=1,
        audio_codec="aac",
        audio_sample_rate_hz=48_000,
        audio_channels=2,
        mtime_ns=source_path.stat().st_mtime_ns,
        inode=source_path.stat().st_ino,
        device=source_path.stat().st_dev,
    )
    config = PipelineRunConfig(
        provider="mock",
        top_n=1,
        minimum_clip_ms=5_000,
        maximum_clip_ms=10_000,
        chunk_duration_ms=12_000,
        chunk_overlap_ms=2_000,
        max_chunk_bytes=24_000_000,
        transcription_model="mock-asr-v1",
        llm_model="mock-llm-v1",
        preview_width=540,
        preview_height=960,
        video_encoder="libx264",
    )
    plan = EditPlan(
        candidate_id=CLIP_ID,
        source_start_ms=2_000,
        source_end_ms=10_000,
        score=91,
        title="可信离线高光",
        hook="这是可用于屏幕的关键语句",
        reason="内容完整并且适合交给编辑继续处理",
        layout=Layout.CENTER_CROP,
        caption_template=CaptionTemplate.CLEAN_ZH_V1,
        effect=Effect.NONE,
        risk_flags=(),
        prompt_version="editing_v1",
        model="mock-llm-v1",
        degraded=True,
    )
    render_spec = {
        "schema_version": RENDER_SPEC_SCHEMA_VERSION,
        "renderer": FFMPEG_RENDERER_CONTRACT_VERSION,
        "text_mode": "none",
    }
    engine = create_sqlite_engine(tmp_path / "liveclip.sqlite3")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(WorkspaceUserRow).values(
                id="local-admin",
                username="local-admin",
                display_name="本机管理员",
                is_active=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            insert(ProjectRow).values(
                id=PROJECT_ID,
                name="离线审核测试",
                owner_id="local-admin",
                source_request_path=str(source_path),
                current_generation=1,
                current_pipeline_run_id=RUN_ID,
                revision_epoch=0,
            )
        )
        connection.execute(
            insert(ProjectMemberRow).values(
                id="membership-offline-owner",
                project_id=PROJECT_ID,
                user_id="local-admin",
                role="owner",
                created_at=NOW,
            )
        )
        connection.execute(
            insert(PipelineRunRow).values(
                id=RUN_ID,
                project_id=PROJECT_ID,
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
                id="source_offline_review_1",
                project_id=PROJECT_ID,
                resolved_path=str(source.resolved_path),
                filename=source.filename,
                sha256=source.sha256,
                size_bytes=source.size_bytes,
                mtime_ns=source.mtime_ns,
                device=source.device,
                inode=source.inode,
                duration_ms=source.duration_ms,
                width=source.video_width,
                height=source.video_height,
                video_stream_index=source.video_stream_index,
                audio_stream_index=source.audio_stream_index,
                video_rotation_degrees=source.video_rotation_degrees,
                video_codec=source.video_codec,
                audio_codec=source.audio_codec,
                frame_rate=str(source.video_frame_rate),
                probe_json=source.model_dump(mode="json"),
            )
        )
        connection.execute(
            insert(CandidateClipRow).values(
                id=CLIP_ID,
                project_id=PROJECT_ID,
                pipeline_run_id=RUN_ID,
                candidate_key="candidate-offline-review-1",
                source_start_ms=2_000,
                source_end_ms=10_000,
                allowed_start_ms=0,
                allowed_end_ms=12_000,
                transcript_text="这是可用于屏幕的关键语句，内容完整。",
                context_before="",
                context_after="",
                rule_score=91,
                reasons_json=["内容完整"],
                segment_ids_json=[],
                current_revision=1,
                rank=1,
                selected_for_review=True,
            )
        )
        connection.execute(
            insert(EditPlanRevisionRow).values(
                id=REVISION_ID,
                candidate_clip_id=CLIP_ID,
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
                id="caption_offline_review_1",
                edit_plan_revision_id=REVISION_ID,
                cue_index=0,
                start_ms=0,
                end_ms=8_000,
                text="这是可用于屏幕的关键语句，内容完整。",
            )
        )
        connection.execute(
            insert(TaskRow).values(
                id=TASK_ID,
                kind=TaskKind.RENDER.value,
                target_id=CLIP_ID,
                operation_key="render:offline-review-fixture",
                input_fingerprint=SPEC_FINGERPRINT,
                resource_class=ResourceClass.HEAVY.value,
                pipeline_run_id=RUN_ID,
                status=TaskStatus.SUCCEEDED.value,
                priority=800,
                expected_generation=1,
                expected_revision=1,
                expected_revision_epoch=0,
                attempt_count=1,
                retry_count=0,
                manual_retry_count=0,
                max_retries=1,
                completed_at=NOW,
            )
        )
        connection.execute(
            insert(TaskAttemptRow).values(
                id=ATTEMPT_ID,
                task_id=TASK_ID,
                attempt_number=1,
                worker_id="offline-review-worker",
                lease_token="offline-review-lease-token",
                outcome=AttemptOutcome.SUCCEEDED.value,
                started_at=NOW - timedelta(seconds=5),
                heartbeat_at=NOW - timedelta(seconds=1),
                lease_expires_at=NOW + timedelta(seconds=30),
                finished_at=NOW,
            )
        )
        connection.execute(
            insert(AssetRow).values(
                id=ASSET_ID,
                project_id=PROJECT_ID,
                candidate_clip_id=CLIP_ID,
                producer_attempt_id=ATTEMPT_ID,
                status=AssetStatus.COMMITTED.value,
                kind="review_proxy",
                relative_path=proxy_path.relative_to(project_dir).as_posix(),
                mime_type="video/mp4",
                input_fingerprint=SPEC_FINGERPRINT,
                sha256=stream_sha256(proxy_path),
                size_bytes=proxy_path.stat().st_size,
                validation_json={"full_decode": "passed", "width": 540, "height": 960},
                generation=1,
                edit_plan_revision=1,
                revision_epoch=0,
                committed_at=NOW,
            )
        )
        connection.execute(
            insert(RenderJobRow).values(
                id=RENDER_ID,
                candidate_clip_id=CLIP_ID,
                edit_plan_revision_id=REVISION_ID,
                task_id=TASK_ID,
                kind="proxy",
                status=RenderStatus.SUCCEEDED.value,
                edit_plan_revision=1,
                revision_epoch=0,
                width=540,
                height=960,
                spec_fingerprint=SPEC_FINGERPRINT,
                spec_json=render_spec,
                asset_id=ASSET_ID,
            )
        )
    fixture = OfflineReviewFixture(
        engine=engine,
        data_dir=data_dir,
        source=source,
        proxy_path=proxy_path,
    )
    try:
        yield fixture
    finally:
        engine.dispose(close=True)


@pytest.mark.parametrize(
    "mutation",
    ("run", "generation", "epoch", "revision", "review", "render", "asset", "producer"),
)
def test_offline_review_fence_rejects_every_current_lineage_change(
    offline_review_fixture: OfflineReviewFixture,
    mutation: str,
) -> None:
    fixture = offline_review_fixture
    repository = SqlAlchemyOfflineReviewFenceRepository(fixture.engine)
    token = repository.capture(
        project=fixture.project,
        source=fixture.source,
        clips=(fixture.observation,),
    )
    with fixture.engine.begin() as connection:
        if mutation == "run":
            connection.execute(
                update(ProjectRow)
                .where(ProjectRow.id == PROJECT_ID)
                .values(current_pipeline_run_id="missing_run")
            )
        elif mutation == "generation":
            connection.execute(
                update(ProjectRow).where(ProjectRow.id == PROJECT_ID).values(current_generation=2)
            )
        elif mutation == "epoch":
            connection.execute(
                update(ProjectRow).where(ProjectRow.id == PROJECT_ID).values(revision_epoch=1)
            )
        elif mutation == "revision":
            connection.execute(
                update(CandidateClipRow)
                .where(CandidateClipRow.id == CLIP_ID)
                .values(current_revision=2)
            )
        elif mutation == "review":
            connection.execute(
                insert(ReviewDecisionRow).values(
                    id="review_offline_review_1",
                    candidate_clip_id=CLIP_ID,
                    edit_plan_revision_id=REVISION_ID,
                    status=ReviewStatus.APPROVED.value,
                    decided_at=NOW + timedelta(seconds=1),
                )
            )
        elif mutation == "render":
            connection.execute(
                update(RenderJobRow)
                .where(RenderJobRow.id == RENDER_ID)
                .values(spec_fingerprint="c" * 64)
            )
        elif mutation == "asset":
            connection.execute(
                update(AssetRow).where(AssetRow.id == ASSET_ID).values(sha256="d" * 64)
            )
        else:
            connection.execute(
                update(TaskRow).where(TaskRow.id == TASK_ID).values(input_fingerprint="e" * 64)
            )

    with pytest.raises(OfflineReviewPackageConflict):
        repository.assert_current(token)


def test_offline_review_service_exports_without_mutating_domain_or_usage_state(
    offline_review_fixture: OfflineReviewFixture,
) -> None:
    fixture = offline_review_fixture
    pipeline = PipelineService(SqlAlchemyPipelineRepository(fixture.engine))
    service = OfflineReviewPackageService(
        pipeline=pipeline,
        clips=ClipQueryService(SqlAlchemyClipQueryRepository(fixture.engine)),
        source_media=_SourceReader(fixture.source),
        media_assets=MediaAssetService(
            SqlAlchemyMediaAssetRepository(fixture.engine),
            data_dir=fixture.data_dir,
        ),
        fence_repository=SqlAlchemyOfflineReviewFenceRepository(fixture.engine),
        data_dir=fixture.data_dir,
    )
    before_project = pipeline.get_project(PROJECT_ID)
    before_counts = _domain_counts(fixture.engine)

    result = service.create(PROJECT_ID, include_zip=False)

    assert result.package_version == "v001"
    assert result.project_revision_epoch == 0
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "liveclip.offline-review-package.v2"
    assert manifest["clips"][0]["proxy_lineage"]["render_job_id"] == RENDER_ID
    assert pipeline.get_project(PROJECT_ID) == before_project
    assert _domain_counts(fixture.engine) == before_counts == (0, 0, 0)


@dataclass(frozen=True)
class _SourceReader:
    source: SourceMediaMetadata

    def load_source(self, *, project_id: str) -> SourceMediaMetadata:
        assert project_id == PROJECT_ID
        return self.source


def _domain_counts(engine: Engine) -> tuple[int, int, int]:
    with engine.connect() as connection:
        values = tuple(
            int(connection.scalar(select(func.count()).select_from(table)) or 0)
            for table in (ReviewDecisionRow, DeliveryRow, ApiUsageRow)
        )
    return values
