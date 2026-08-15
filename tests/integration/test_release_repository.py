# ruff: noqa: RUF001
from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection, Engine

from liveclip.application.idempotency import build_idempotency_context
from liveclip.application.pipeline import (
    LeaseIdentity,
    PipelineRunConfig,
    load_persisted_pipeline_config,
)
from liveclip.application.releases import (
    ReleaseApprovalCommand,
    ReleaseConflict,
    ReleaseItemCreate,
    ReleaseItemUpdate,
    ReleaseMetricCreate,
    ReleasePackagePersistence,
    ReleasePackageRequest,
    ReleaseStatusCommand,
)
from liveclip.application.reviewing import ClipPatch, ReviewCommand
from liveclip.db import release_repository as release_repository_module
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import (
    AssetRow,
    AuditEventRow,
    CandidateClipRow,
    CaptionCueRow,
    EditPlanRevisionRow,
    PipelineRunRow,
    ProjectMemberRow,
    ProjectRow,
    ReleaseItemRow,
    ReleasePackageRow,
    RenderJobRow,
    ReviewDecisionRow,
    SourceMediaRow,
    TaskAttemptRow,
    TaskRow,
    WorkspaceUserRow,
)
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.release_repository import SqlAlchemyReleaseRepository
from liveclip.db.review_repository import SqlAlchemyReviewRepository
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.delivery.release_package import release_archive_name
from liveclip.domain.edit_plan import CaptionTemplate, EditPlan, Effect, Layout
from liveclip.domain.project_lifecycle import ProjectLifecycle
from liveclip.domain.releases import (
    ReleaseApprovalStatus,
    ReleaseCaptionMode,
    ReleaseChecklist,
    ReleaseItemStatus,
    ReleasePackageStatus,
    ReleasePlatform,
)
from liveclip.domain.state_transitions import (
    AssetStatus,
    AttemptOutcome,
    PipelineRunStatus,
    RenderStatus,
    ResourceClass,
    ReviewStatus,
    TaskKind,
    TaskStatus,
)
from liveclip.media.secure_files import PinnedRegularFile
from liveclip.renderer.contracts import (
    FFMPEG_RENDERER_CONTRACT_VERSION,
    RENDER_SPEC_SCHEMA_VERSION,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 15, 8, 0, tzinfo=UTC)
PROJECT_ID = "1" * 32
RUN_ID = "2" * 32
CLIP_ID = "3" * 32
REVISION_ID = "4" * 32
RENDER_ID = "5" * 32
ASSET_ID = "6" * 32
QUALITY_ASSET_ID = "9" * 32
CONTACT_ASSET_ID = "a" * 32
SUBTITLE_ASSET_ID = "f" * 32
TASK_ID = "7" * 32
ATTEMPT_ID = "8" * 32
OWNER_ID = "owner-release"
EDITOR_ID = "editor-release"
REVIEWER_ID = "reviewer-release"
SPEC_FINGERPRINT = "b" * 64


@dataclass(frozen=True)
class ReleaseFixture:
    engine: Engine
    repository: SqlAlchemyReleaseRepository
    data_dir: Path


@pytest.fixture
def release_fixture(tmp_path: Path) -> ReleaseFixture:
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source-media")
    config = PipelineRunConfig(
        provider="mock",
        top_n=1,
        minimum_clip_ms=5_000,
        maximum_clip_ms=90_000,
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
        source_end_ms=62_000,
        score=93,
        title="真实发布高光",
        hook="这是一句可以展示在屏幕上的高光语句",
        reason="内容完整，适合作为短视频发布。",
        layout=Layout.CENTER_CROP,
        caption_template=CaptionTemplate.CLEAN_ZH_V1,
        effect=Effect.NONE,
        risk_flags=(),
        prompt_version="editing_v1",
        model="mock-llm-v1",
        degraded=False,
    )
    engine = create_sqlite_engine(tmp_path / "release.sqlite3")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for user_id, username in (
            (OWNER_ID, "owner"),
            (EDITOR_ID, "editor"),
            (REVIEWER_ID, "reviewer"),
        ):
            connection.execute(
                insert(WorkspaceUserRow).values(
                    id=user_id,
                    username=username,
                    display_name=username.title(),
                    is_active=True,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        connection.execute(
            insert(ProjectRow).values(
                id=PROJECT_ID,
                name="发布计划测试",
                owner_id=OWNER_ID,
                visibility="private",
                lifecycle=ProjectLifecycle.READY_TO_PUBLISH.value,
                management_version=1,
                source_request_path=str(source_path),
                current_generation=1,
                current_pipeline_run_id=RUN_ID,
                revision_epoch=0,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        for index, (user_id, role) in enumerate(
            ((OWNER_ID, "owner"), (EDITOR_ID, "editor"), (REVIEWER_ID, "reviewer"))
        ):
            connection.execute(
                insert(ProjectMemberRow).values(
                    id=f"release-member-{index}",
                    project_id=PROJECT_ID,
                    user_id=user_id,
                    role=role,
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
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            insert(SourceMediaRow).values(
                id="source-release",
                project_id=PROJECT_ID,
                resolved_path=str(source_path),
                filename=source_path.name,
                sha256="a" * 64,
                size_bytes=source_path.stat().st_size,
                mtime_ns=source_path.stat().st_mtime_ns,
                device=source_path.stat().st_dev,
                inode=source_path.stat().st_ino,
                duration_ms=120_000,
                width=1080,
                height=1920,
                video_stream_index=0,
                audio_stream_index=1,
                video_rotation_degrees=0,
                video_codec="h264",
                audio_codec="aac",
                frame_rate="30/1",
                probe_json={"format": {"format_name": "mp4"}},
                created_at=NOW,
            )
        )
        connection.execute(
            insert(CandidateClipRow).values(
                id=CLIP_ID,
                project_id=PROJECT_ID,
                pipeline_run_id=RUN_ID,
                candidate_key="release-candidate",
                source_start_ms=2_000,
                source_end_ms=62_000,
                allowed_start_ms=0,
                allowed_end_ms=65_000,
                transcript_text="这是一句可以展示在屏幕上的高光语句。",
                context_before="",
                context_after="",
                rule_score=93,
                reasons_json=["内容完整"],
                segment_ids_json=[],
                current_revision=1,
                rank=1,
                selected_for_review=True,
                created_at=NOW,
            )
        )
        connection.execute(
            insert(EditPlanRevisionRow).values(
                id=REVISION_ID,
                candidate_clip_id=CLIP_ID,
                revision=1,
                parent_revision=None,
                origin="ai",
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
                created_at=NOW,
            )
        )
        connection.execute(
            insert(CaptionCueRow).values(
                id="caption-release",
                edit_plan_revision_id=REVISION_ID,
                cue_index=0,
                start_ms=0,
                end_ms=3_000,
                text="这是一句高光语句。",
            )
        )
        connection.execute(
            insert(ReviewDecisionRow).values(
                id="review-release",
                candidate_clip_id=CLIP_ID,
                edit_plan_revision_id=REVISION_ID,
                status=ReviewStatus.APPROVED.value,
                decided_at=NOW,
            )
        )
        connection.execute(
            insert(TaskRow).values(
                id=TASK_ID,
                kind=TaskKind.RENDER.value,
                target_id=CLIP_ID,
                operation_key="render:release-fixture",
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
                created_at=NOW,
                updated_at=NOW,
                completed_at=NOW,
            )
        )
        connection.execute(
            insert(TaskAttemptRow).values(
                id=ATTEMPT_ID,
                task_id=TASK_ID,
                attempt_number=1,
                worker_id="release-worker",
                lease_token="release-lease-token",
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
                relative_path="renders/release/review.mp4",
                mime_type="video/mp4",
                input_fingerprint=SPEC_FINGERPRINT,
                sha256="c" * 64,
                size_bytes=1_000_000,
                validation_json={"full_decode": "passed", "width": 540, "height": 960},
                generation=1,
                edit_plan_revision=1,
                revision_epoch=0,
                created_at=NOW,
                committed_at=NOW,
            )
        )
        connection.execute(
            insert(AssetRow).values(
                id=SUBTITLE_ASSET_ID,
                project_id=PROJECT_ID,
                candidate_clip_id=CLIP_ID,
                producer_attempt_id=ATTEMPT_ID,
                status=AssetStatus.COMMITTED.value,
                kind="clip_subtitle_srt",
                relative_path="renders/release/review.srt",
                mime_type="application/x-subrip",
                input_fingerprint=SPEC_FINGERPRINT,
                sha256="1" * 64,
                size_bytes=500,
                validation_json={"timeline": "clip_relative_ms", "cue_count": 1},
                generation=1,
                edit_plan_revision=1,
                revision_epoch=0,
                created_at=NOW,
                committed_at=NOW,
            )
        )
        connection.execute(
            insert(AssetRow).values(
                id=QUALITY_ASSET_ID,
                project_id=PROJECT_ID,
                candidate_clip_id=CLIP_ID,
                producer_attempt_id=ATTEMPT_ID,
                status=AssetStatus.COMMITTED.value,
                kind="render_quality_report",
                relative_path="renders/release/quality-report.json",
                mime_type="application/json",
                input_fingerprint=SPEC_FINGERPRINT,
                sha256="d" * 64,
                size_bytes=2_000,
                validation_json={"automatic_status": "passed"},
                generation=1,
                edit_plan_revision=1,
                revision_epoch=0,
                created_at=NOW,
                committed_at=NOW,
            )
        )
        connection.execute(
            insert(AssetRow).values(
                id=CONTACT_ASSET_ID,
                project_id=PROJECT_ID,
                candidate_clip_id=CLIP_ID,
                producer_attempt_id=ATTEMPT_ID,
                status=AssetStatus.COMMITTED.value,
                kind="render_contact_sheet",
                relative_path="renders/release/contact-sheet.png",
                mime_type="image/png",
                input_fingerprint=SPEC_FINGERPRINT,
                sha256="e" * 64,
                size_bytes=20_000,
                validation_json={"frames": 3},
                generation=1,
                edit_plan_revision=1,
                revision_epoch=0,
                created_at=NOW,
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
                spec_json={
                    "schema_version": RENDER_SPEC_SCHEMA_VERSION,
                    "renderer": FFMPEG_RENDERER_CONTRACT_VERSION,
                    "text_mode": "none",
                },
                asset_id=ASSET_ID,
                subtitle_asset_id=SUBTITLE_ASSET_ID,
                quality_report_asset_id=QUALITY_ASSET_ID,
                contact_sheet_asset_id=CONTACT_ASSET_ID,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    fixture = ReleaseFixture(
        engine=engine,
        repository=SqlAlchemyReleaseRepository(engine, data_dir=tmp_path),
        data_dir=tmp_path,
    )
    try:
        yield fixture
    finally:
        engine.dispose(close=True)


def _create(
    fixture: ReleaseFixture,
    *,
    idempotency_key: str | None = None,
    account_label: str = "主账号",
    platform: ReleasePlatform = ReleasePlatform.DOUYIN,
):  # type: ignore[no-untyped-def]
    command = ReleaseItemCreate(
        clip_id=CLIP_ID,
        expected_revision=1,
        platform=platform,
        account_label=account_label,
        caption_mode=ReleaseCaptionMode.CLEAN_SEPARATE,
        assignee_user_id=EDITOR_ID,
        planned_publish_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
    )
    context = (
        build_idempotency_context(
            raw_key=idempotency_key,
            caller_scope=f"user:{OWNER_ID}",
            operation_scope=f"project:{PROJECT_ID}:release-items",
            request_payload=command.model_dump(mode="json"),
        )
        if idempotency_key
        else None
    )
    return fixture.repository.create_item(
        project_id=PROJECT_ID,
        acting_user_id=OWNER_ID,
        command=command,
        idempotency=context,
    )


def _complete_update(version: int, *, title: str = "发布标题") -> ReleaseItemUpdate:
    return ReleaseItemUpdate(
        expected_management_version=version,
        edit_plan_revision=1,
        title=title,
        title_variants=("标题方案二",),
        description="发布文案",
        hashtags=("直播高光", "视频剪辑"),
        cta="欢迎关注",
        caption_mode=ReleaseCaptionMode.CLEAN_SEPARATE,
        cover_time_ms=1_000,
        assignee_user_id=EDITOR_ID,
        planned_publish_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        checklist=ReleaseChecklist(
            hook_confirmed=True,
            first_frame_confirmed=True,
            subtitles_confirmed=True,
            music_rights_confirmed=True,
            likeness_confirmed=True,
            personal_data_confirmed=True,
            claims_confirmed=True,
            sponsorship_confirmed=True,
            platform_policy_confirmed=True,
        ),
    )


def _current_pipeline_config(fixture: ReleaseFixture) -> PipelineRunConfig:
    with fixture.engine.connect() as connection:
        row = connection.execute(
            select(
                PipelineRunRow.config_json,
                PipelineRunRow.config_fingerprint,
            ).where(PipelineRunRow.id == RUN_ID)
        ).one()
    return load_persisted_pipeline_config(
        row.config_json,
        str(row.config_fingerprint),
    )


def _ready_item(
    fixture: ReleaseFixture,
    *,
    account_label: str = "主账号",
):  # type: ignore[no-untyped-def]
    repository = fixture.repository
    created = _create(fixture, account_label=account_label)
    updated = repository.update_item(
        created.release_item_id,
        acting_user_id=EDITOR_ID,
        command=_complete_update(created.management_version),
    )
    pending = repository.transition_approval(
        created.release_item_id,
        acting_user_id=EDITOR_ID,
        command=ReleaseApprovalCommand(
            expected_management_version=updated.management_version,
            target=ReleaseApprovalStatus.PENDING_REVIEW,
            reason="提交发布审核",
        ),
    )
    approved = repository.transition_approval(
        created.release_item_id,
        acting_user_id=REVIEWER_ID,
        command=ReleaseApprovalCommand(
            expected_management_version=pending.management_version,
            target=ReleaseApprovalStatus.APPROVED,
            reason="版权与发布文案均已核验",
        ),
    )
    return repository.transition_status(
        created.release_item_id,
        acting_user_id=EDITOR_ID,
        command=ReleaseStatusCommand(
            expected_management_version=approved.management_version,
            target=ReleaseItemStatus.READY,
        ),
    )


def _complete_test_package(
    fixture: ReleaseFixture,
    release_item_id: str,
    release_item_version: int,
):  # type: ignore[no-untyped-def]
    queued = fixture.repository.enqueue_package(
        release_item_id,
        requested_by_user_id=EDITOR_ID,
        request=ReleasePackageRequest(
            expected_release_item_version=release_item_version,
            include_zip=True,
        ),
        max_retries=2,
    )
    queue = SQLiteTaskQueue(fixture.engine, lease_seconds=60)
    claimed = queue.claim(worker_id="publication-package-worker", task_kind=TaskKind.DELIVERY)
    assert claimed is not None and claimed.task_id == queued.task_id
    lease = LeaseIdentity(
        task_id=claimed.task_id,
        worker_id=claimed.worker_id,
        lease_token=claimed.lease_token,
    )
    work = fixture.repository.start_release_package(lease)
    item_key = release_item_id[:8]
    manifest_asset_id = f"publication-manifest-{item_key}-{work.version}"
    zip_asset_id = f"publication-zip-{item_key}-{work.version}"
    base = f"release-packages/{release_item_id}/v{work.version:03d}"
    artifact_values = (
        (
            manifest_asset_id,
            "release_package_manifest",
            f"{base}/manifest.json",
            b'{"schema_version":"liveclip.release-package.v1"}\n',
        ),
        (
            zip_asset_id,
            "release_package_zip",
            f"{base}/{release_archive_name(work)}",
            b"PK\x03\x04release-package-test-bytes",
        ),
    )
    artifact_hashes: dict[str, str] = {}
    for asset_id, _kind, relative_path, value in artifact_values:
        path = fixture.data_dir / PROJECT_ID / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        artifact_hashes[asset_id] = hashlib.sha256(value).hexdigest()
    with fixture.engine.begin() as connection:
        attempt_id = connection.scalar(
            select(TaskAttemptRow.id).where(
                TaskAttemptRow.task_id == lease.task_id,
                TaskAttemptRow.lease_token == lease.lease_token,
            )
        )
        assert attempt_id is not None
        for asset_id, kind, relative_path, value in artifact_values:
            digest = artifact_hashes[asset_id]
            connection.execute(
                insert(AssetRow).values(
                    id=asset_id,
                    project_id=PROJECT_ID,
                    producer_attempt_id=str(attempt_id),
                    status=AssetStatus.COMMITTED.value,
                    kind=kind,
                    relative_path=relative_path,
                    mime_type=("application/zip" if kind.endswith("zip") else "application/json"),
                    input_fingerprint=work.package_fingerprint,
                    sha256=digest,
                    size_bytes=len(value),
                    validation_json={
                        "schema_version": "liveclip.release-package.v1",
                        "release_package_id": work.release_package_id,
                        "snapshot_fingerprint": work.snapshot_fingerprint,
                    },
                    generation=1,
                    revision_epoch=0,
                    created_at=NOW,
                    committed_at=NOW,
                )
            )
    assert fixture.repository.complete_release_package(
        lease,
        work,
        ReleasePackagePersistence(
            manifest_asset_id=manifest_asset_id,
            zip_asset_id=zip_asset_id,
            manifest_sha256=artifact_hashes[manifest_asset_id],
            zip_sha256=artifact_hashes[zip_asset_id],
        ),
    )
    return fixture.repository.get_package(work.release_package_id)


def test_release_item_full_transaction_flow_and_project_publication(
    release_fixture: ReleaseFixture,
) -> None:
    repository = release_fixture.repository
    created = _create(release_fixture)
    assert created.status is ReleaseItemStatus.DRAFT
    assert created.approval_status is ReleaseApprovalStatus.DRAFT
    assert created.preflight.passed is False
    assert created.assignee is not None
    assert created.assignee.username == "editor"

    updated = repository.update_item(
        created.release_item_id,
        acting_user_id=EDITOR_ID,
        command=_complete_update(created.management_version),
    )
    pending = repository.transition_approval(
        created.release_item_id,
        acting_user_id=EDITOR_ID,
        command=ReleaseApprovalCommand(
            expected_management_version=updated.management_version,
            target=ReleaseApprovalStatus.PENDING_REVIEW,
            reason="提交发布审核",
        ),
    )
    approved = repository.transition_approval(
        created.release_item_id,
        acting_user_id=REVIEWER_ID,
        command=ReleaseApprovalCommand(
            expected_management_version=pending.management_version,
            target=ReleaseApprovalStatus.APPROVED,
            reason="版权与发布文案均已核验",
        ),
    )
    assert approved.preflight.passed is True
    ready = repository.transition_status(
        created.release_item_id,
        acting_user_id=EDITOR_ID,
        command=ReleaseStatusCommand(
            expected_management_version=approved.management_version,
            target=ReleaseItemStatus.READY,
        ),
    )
    package = _complete_test_package(
        release_fixture,
        ready.release_item_id,
        ready.management_version,
    )
    assert package.current is True
    scheduled = repository.transition_status(
        created.release_item_id,
        acting_user_id=EDITOR_ID,
        command=ReleaseStatusCommand(
            expected_management_version=ready.management_version,
            target=ReleaseItemStatus.SCHEDULED_EXTERNAL,
        ),
    )
    assert scheduled.packages[0].release_package_id == package.release_package_id
    assert scheduled.packages[0].current is True
    published_at = NOW + timedelta(minutes=5)
    published = repository.transition_status(
        created.release_item_id,
        acting_user_id=EDITOR_ID,
        command=ReleaseStatusCommand(
            expected_management_version=scheduled.management_version,
            target=ReleaseItemStatus.PUBLISHED,
            release_package_id=package.release_package_id,
            external_url="https://example.com/video/123",
            published_at=published_at,
        ),
    )
    measured = repository.add_metric(
        created.release_item_id,
        acting_user_id=OWNER_ID,
        command=ReleaseMetricCreate(
            captured_at=published_at + timedelta(minutes=1),
            views=10_000,
            likes=800,
            comments=32,
            shares=50,
            saves=90,
            followers_gained=25,
        ),
    )
    assert published.status is ReleaseItemStatus.PUBLISHED
    assert published.publication_evidence is not None
    assert published.publication_evidence.release_package_id == package.release_package_id
    assert published.publication_evidence.video_sha256 == "c" * 64
    assert published.publication_evidence.artifact_sha256 == package.zip_sha256
    assert published.packages[0].published_artifact is True
    assert published.packages[0].current is True
    assert measured.metrics[0].views == 10_000
    with release_fixture.engine.connect() as connection:
        lifecycle = connection.scalar(
            select(ProjectRow.lifecycle).where(ProjectRow.id == PROJECT_ID)
        )
        actions = tuple(
            connection.scalars(
                select(AuditEventRow.action)
                .where(AuditEventRow.project_id == PROJECT_ID)
                .order_by(AuditEventRow.created_at, AuditEventRow.id)
            )
        )
    assert lifecycle == ProjectLifecycle.PUBLISHED.value
    assert "project.published" in actions
    assert "release_metric.recorded" in actions


def test_publication_rejects_a_queued_package_for_the_same_item(
    release_fixture: ReleaseFixture,
) -> None:
    ready = _ready_item(release_fixture)
    queued = release_fixture.repository.enqueue_package(
        ready.release_item_id,
        requested_by_user_id=EDITOR_ID,
        request=ReleasePackageRequest(
            expected_release_item_version=ready.management_version,
        ),
        max_retries=1,
    )

    with pytest.raises(ReleaseConflict, match="not a successful package"):
        release_fixture.repository.transition_status(
            ready.release_item_id,
            acting_user_id=EDITOR_ID,
            command=ReleaseStatusCommand(
                expected_management_version=ready.management_version,
                target=ReleaseItemStatus.PUBLISHED,
                release_package_id=queued.release_package_id,
                external_id="queued-package-must-not-publish",
                published_at=NOW,
            ),
        )


def test_publication_rejects_a_package_created_for_another_release_item(
    release_fixture: ReleaseFixture,
) -> None:
    first = _ready_item(release_fixture, account_label="主账号")
    first_package = _complete_test_package(
        release_fixture,
        first.release_item_id,
        first.management_version,
    )
    second = _ready_item(release_fixture, account_label="副账号")

    with pytest.raises(ReleaseConflict, match="not a successful package for this item"):
        release_fixture.repository.transition_status(
            second.release_item_id,
            acting_user_id=EDITOR_ID,
            command=ReleaseStatusCommand(
                expected_management_version=second.management_version,
                target=ReleaseItemStatus.PUBLISHED,
                release_package_id=first_package.release_package_id,
                external_id="wrong-release-item",
                published_at=NOW,
            ),
        )


def test_publication_rejects_a_successful_package_after_material_content_change(
    release_fixture: ReleaseFixture,
) -> None:
    repository = release_fixture.repository
    ready = _ready_item(release_fixture)
    package = _complete_test_package(
        release_fixture,
        ready.release_item_id,
        ready.management_version,
    )
    changed = repository.update_item(
        ready.release_item_id,
        acting_user_id=EDITOR_ID,
        command=_complete_update(
            ready.management_version,
            title="发布内容已经改变",
        ),
    )
    pending = repository.transition_approval(
        ready.release_item_id,
        acting_user_id=EDITOR_ID,
        command=ReleaseApprovalCommand(
            expected_management_version=changed.management_version,
            target=ReleaseApprovalStatus.PENDING_REVIEW,
            reason="重新提交发布审核",
        ),
    )
    approved = repository.transition_approval(
        ready.release_item_id,
        acting_user_id=REVIEWER_ID,
        command=ReleaseApprovalCommand(
            expected_management_version=pending.management_version,
            target=ReleaseApprovalStatus.APPROVED,
            reason="重新核验发布内容",
        ),
    )
    current = repository.transition_status(
        ready.release_item_id,
        acting_user_id=EDITOR_ID,
        command=ReleaseStatusCommand(
            expected_management_version=approved.management_version,
            target=ReleaseItemStatus.READY,
        ),
    )

    with pytest.raises(ReleaseConflict, match="does not match current release content"):
        repository.transition_status(
            ready.release_item_id,
            acting_user_id=EDITOR_ID,
            command=ReleaseStatusCommand(
                expected_management_version=current.management_version,
                target=ReleaseItemStatus.PUBLISHED,
                release_package_id=package.release_package_id,
                external_id="stale-package-must-not-publish",
                published_at=NOW,
            ),
        )


@pytest.mark.parametrize(
    "changed_values",
    [
        {"status": AssetStatus.PENDING.value},
        {"kind": "release_package_manifest"},
        {"sha256": "0" * 64},
    ],
)
def test_publication_rejects_changed_committed_zip_evidence(
    release_fixture: ReleaseFixture,
    changed_values: dict[str, str],
) -> None:
    ready = _ready_item(release_fixture)
    package = _complete_test_package(
        release_fixture,
        ready.release_item_id,
        ready.management_version,
    )
    assert package.zip_asset_id is not None
    with release_fixture.engine.begin() as connection:
        connection.execute(
            update(AssetRow).where(AssetRow.id == package.zip_asset_id).values(**changed_values)
        )

    with pytest.raises(ReleaseConflict, match=r"artifact (?:evidence|bytes)"):
        release_fixture.repository.transition_status(
            ready.release_item_id,
            acting_user_id=EDITOR_ID,
            command=ReleaseStatusCommand(
                expected_management_version=ready.management_version,
                target=ReleaseItemStatus.PUBLISHED,
                release_package_id=package.release_package_id,
                external_id="mutated-artifact-must-not-publish",
                published_at=NOW,
            ),
        )


@pytest.mark.parametrize("asset_field", ["manifest_asset_id", "zip_asset_id"])
def test_publication_rehashes_current_package_bytes_and_rejects_tampering(
    release_fixture: ReleaseFixture,
    asset_field: str,
) -> None:
    ready = _ready_item(release_fixture)
    package = _complete_test_package(
        release_fixture,
        ready.release_item_id,
        ready.management_version,
    )
    asset_id = getattr(package, asset_field)
    assert isinstance(asset_id, str)
    with release_fixture.engine.connect() as connection:
        relative_path = connection.scalar(
            select(AssetRow.relative_path).where(AssetRow.id == asset_id)
        )
    assert relative_path is not None
    artifact_path = release_fixture.data_dir / PROJECT_ID / str(relative_path)
    original = artifact_path.read_bytes()
    artifact_path.write_bytes(bytes(byte ^ 0x01 for byte in original))

    with pytest.raises(ReleaseConflict, match="artifact bytes changed"):
        release_fixture.repository.transition_status(
            ready.release_item_id,
            acting_user_id=EDITOR_ID,
            command=ReleaseStatusCommand(
                expected_management_version=ready.management_version,
                target=ReleaseItemStatus.PUBLISHED,
                release_package_id=package.release_package_id,
                external_id="tampered-local-package",
                published_at=NOW,
            ),
        )

    unchanged = release_fixture.repository.get_item(ready.release_item_id)
    assert unchanged.status is ReleaseItemStatus.READY
    assert unchanged.publication_evidence is None


def test_publication_pins_bytes_outside_writer_and_rolls_back_interleaved_mutation(
    release_fixture: ReleaseFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_item(release_fixture)
    package = _complete_test_package(
        release_fixture,
        ready.release_item_id,
        ready.management_version,
    )
    assert package.manifest_asset_id is not None
    with release_fixture.engine.connect() as connection:
        manifest_relative_path = connection.scalar(
            select(AssetRow.relative_path).where(AssetRow.id == package.manifest_asset_id)
        )
        before_project = connection.execute(
            select(ProjectRow.lifecycle, ProjectRow.management_version).where(
                ProjectRow.id == PROJECT_ID
            )
        ).one()
        before_audit_count = connection.scalar(select(func.count()).select_from(AuditEventRow))
    assert manifest_relative_path is not None
    assert before_audit_count is not None
    manifest_path = release_fixture.data_dir / PROJECT_ID / str(manifest_relative_path)

    real_begin_immediate = release_repository_module.begin_immediate
    real_sha256 = PinnedRegularFile.sha256
    writer_active = False
    mutation_performed = False

    @contextmanager
    def tracked_begin_immediate(engine: Engine) -> Iterator[Connection]:
        nonlocal writer_active
        with real_begin_immediate(engine) as connection:
            writer_active = True
            try:
                yield connection
            finally:
                writer_active = False

    def mutate_after_hash(
        pinned: PinnedRegularFile,
        *,
        block_size: int = 1024 * 1024,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> str:
        nonlocal mutation_performed
        assert writer_active is False
        digest = real_sha256(
            pinned,
            block_size=block_size,
            cancel_requested=cancel_requested,
        )
        if pinned.path == manifest_path and not mutation_performed:
            original = manifest_path.read_bytes()
            manifest_path.write_bytes(bytes(value ^ 0x01 for value in original))
            mutation_performed = True
        return digest

    monkeypatch.setattr(
        release_repository_module,
        "begin_immediate",
        tracked_begin_immediate,
    )
    monkeypatch.setattr(PinnedRegularFile, "sha256", mutate_after_hash)

    with pytest.raises(ReleaseConflict, match="before publication committed"):
        release_fixture.repository.transition_status(
            ready.release_item_id,
            acting_user_id=EDITOR_ID,
            command=ReleaseStatusCommand(
                expected_management_version=ready.management_version,
                target=ReleaseItemStatus.PUBLISHED,
                release_package_id=package.release_package_id,
                external_id="interleaved-mutation-must-roll-back",
                published_at=NOW,
            ),
        )

    assert mutation_performed is True
    unchanged = release_fixture.repository.get_item(ready.release_item_id)
    assert unchanged.status is ReleaseItemStatus.READY
    assert unchanged.management_version == ready.management_version
    assert unchanged.publication_evidence is None
    with release_fixture.engine.connect() as connection:
        after_project = connection.execute(
            select(ProjectRow.lifecycle, ProjectRow.management_version).where(
                ProjectRow.id == PROJECT_ID
            )
        ).one()
        after_audit_count = connection.scalar(select(func.count()).select_from(AuditEventRow))
    assert after_project == before_project
    assert after_audit_count == before_audit_count


def test_publication_rehash_rejects_unsafe_or_linked_artifact_paths(
    release_fixture: ReleaseFixture,
) -> None:
    first = _ready_item(release_fixture)
    first_package = _complete_test_package(
        release_fixture,
        first.release_item_id,
        first.management_version,
    )
    assert first_package.zip_asset_id is not None
    with release_fixture.engine.begin() as connection:
        connection.execute(
            update(AssetRow)
            .where(AssetRow.id == first_package.zip_asset_id)
            .values(relative_path="../escaped.zip")
        )
    with pytest.raises(ReleaseConflict, match="artifact path is invalid"):
        release_fixture.repository.transition_status(
            first.release_item_id,
            acting_user_id=EDITOR_ID,
            command=ReleaseStatusCommand(
                expected_management_version=first.management_version,
                target=ReleaseItemStatus.PUBLISHED,
                release_package_id=first_package.release_package_id,
                external_id="unsafe-path",
                published_at=NOW,
            ),
        )

    second = _ready_item(release_fixture, account_label="副账号")
    second_package = _complete_test_package(
        release_fixture,
        second.release_item_id,
        second.management_version,
    )
    assert second_package.zip_asset_id is not None
    with release_fixture.engine.connect() as connection:
        relative_path = connection.scalar(
            select(AssetRow.relative_path).where(AssetRow.id == second_package.zip_asset_id)
        )
    assert relative_path is not None
    artifact_path = release_fixture.data_dir / PROJECT_ID / str(relative_path)
    outside = release_fixture.data_dir / "outside-release.zip"
    outside.write_bytes(artifact_path.read_bytes())
    artifact_path.unlink()
    artifact_path.symlink_to(outside)
    with pytest.raises(ReleaseConflict, match="artifact bytes are missing or unsafe"):
        release_fixture.repository.transition_status(
            second.release_item_id,
            acting_user_id=EDITOR_ID,
            command=ReleaseStatusCommand(
                expected_management_version=second.management_version,
                target=ReleaseItemStatus.PUBLISHED,
                release_package_id=second_package.release_package_id,
                external_id="linked-artifact",
                published_at=NOW,
            ),
        )


def test_metric_capture_cannot_precede_recorded_publication(
    release_fixture: ReleaseFixture,
) -> None:
    ready = _ready_item(release_fixture)
    package = _complete_test_package(
        release_fixture,
        ready.release_item_id,
        ready.management_version,
    )
    published_at = NOW + timedelta(minutes=5)
    published = release_fixture.repository.transition_status(
        ready.release_item_id,
        acting_user_id=EDITOR_ID,
        command=ReleaseStatusCommand(
            expected_management_version=ready.management_version,
            target=ReleaseItemStatus.PUBLISHED,
            release_package_id=package.release_package_id,
            external_id="chronology-test",
            published_at=published_at,
        ),
    )

    with pytest.raises(ReleaseConflict, match="cannot precede publication"):
        release_fixture.repository.add_metric(
            ready.release_item_id,
            acting_user_id=OWNER_ID,
            command=ReleaseMetricCreate(
                captured_at=published_at - timedelta(milliseconds=1),
                views=1,
            ),
        )

    assert published.metrics == ()
    assert release_fixture.repository.get_item(ready.release_item_id).metrics == ()


def test_release_idempotency_permissions_and_optimistic_version(
    release_fixture: ReleaseFixture,
) -> None:
    first = _create(release_fixture, idempotency_key="release-create-001")
    replay = _create(release_fixture, idempotency_key="release-create-001")
    assert replay.release_item_id == first.release_item_id
    with pytest.raises(ReleaseConflict, match="version changed"):
        release_fixture.repository.update_item(
            first.release_item_id,
            acting_user_id=EDITOR_ID,
            command=_complete_update(999),
        )
    with pytest.raises(ReleaseConflict, match="permission"):
        release_fixture.repository.update_item(
            first.release_item_id,
            acting_user_id=REVIEWER_ID,
            command=_complete_update(first.management_version),
        )
    pending = release_fixture.repository.transition_approval(
        first.release_item_id,
        acting_user_id=EDITOR_ID,
        command=ReleaseApprovalCommand(
            expected_management_version=first.management_version,
            target=ReleaseApprovalStatus.PENDING_REVIEW,
            reason="编辑提交发布审核",
        ),
    )
    with pytest.raises(ReleaseConflict, match="permission"):
        release_fixture.repository.transition_approval(
            first.release_item_id,
            acting_user_id=EDITOR_ID,
            command=ReleaseApprovalCommand(
                expected_management_version=pending.management_version,
                target=ReleaseApprovalStatus.APPROVED,
                reason="编辑不能批准自己的发布项",
            ),
        )


def test_release_assignee_must_be_project_owner_or_editor(
    release_fixture: ReleaseFixture,
) -> None:
    with pytest.raises(ReleaseConflict, match="owner or editor"):
        release_fixture.repository.create_item(
            project_id=PROJECT_ID,
            acting_user_id=OWNER_ID,
            command=ReleaseItemCreate(
                clip_id=CLIP_ID,
                expected_revision=1,
                platform=ReleasePlatform.DOUYIN,
                account_label="审核员不能执行发布",
                assignee_user_id=REVIEWER_ID,
                planned_publish_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
            ),
        )


def test_scheduled_release_cannot_clear_planned_publish_time(
    release_fixture: ReleaseFixture,
) -> None:
    ready = _ready_item(release_fixture)
    scheduled = release_fixture.repository.transition_status(
        ready.release_item_id,
        acting_user_id=EDITOR_ID,
        command=ReleaseStatusCommand(
            expected_management_version=ready.management_version,
            target=ReleaseItemStatus.SCHEDULED_EXTERNAL,
        ),
    )

    with pytest.raises(ReleaseConflict, match="requires a planned publish time"):
        release_fixture.repository.update_item(
            scheduled.release_item_id,
            acting_user_id=EDITOR_ID,
            command=_complete_update(scheduled.management_version).model_copy(
                update={"planned_publish_at": None}
            ),
        )


def test_release_preflight_recomputes_from_trusted_current_evidence(
    release_fixture: ReleaseFixture,
) -> None:
    created = _create(release_fixture)
    with release_fixture.engine.begin() as connection:
        connection.execute(
            update(AssetRow).where(AssetRow.id == ASSET_ID).values(status=AssetStatus.PENDING.value)
        )
    refreshed = release_fixture.repository.get_item(created.release_item_id)
    trusted = next(check for check in refreshed.preflight.checks if check.code == "trusted_media")
    assert trusted.outcome == "blocked"
    assert refreshed.preflight.passed is False


def test_release_checklist_change_invalidates_prior_approval(
    release_fixture: ReleaseFixture,
) -> None:
    ready = _ready_item(release_fixture)
    package = _complete_test_package(
        release_fixture,
        ready.release_item_id,
        ready.management_version,
    )
    changed_checklist = ready.checklist.model_copy(update={"music_rights_confirmed": False})

    changed = release_fixture.repository.update_item(
        ready.release_item_id,
        acting_user_id=EDITOR_ID,
        command=_complete_update(ready.management_version).model_copy(
            update={"checklist": changed_checklist}
        ),
    )

    assert changed.approval_status is ReleaseApprovalStatus.DRAFT
    assert changed.status is ReleaseItemStatus.DRAFT
    assert changed.packages[0].release_package_id == package.release_package_id
    assert changed.packages[0].current is False
    assert changed.packages[0].published_artifact is False
    human_checklist = next(
        check for check in changed.preflight.checks if check.code == "human_checklist"
    )
    assert human_checklist.outcome == "blocked"


def test_exported_cross_platform_duplicate_is_a_warning_not_a_block(
    release_fixture: ReleaseFixture,
) -> None:
    first = _ready_item(release_fixture, account_label="抖音主账号")
    first_package = _complete_test_package(
        release_fixture,
        first.release_item_id,
        first.management_version,
    )
    second = _create(
        release_fixture,
        account_label="小红书主账号",
        platform=ReleasePlatform.XIAOHONGSHU,
    )
    updated = release_fixture.repository.update_item(
        second.release_item_id,
        acting_user_id=EDITOR_ID,
        command=_complete_update(second.management_version),
    )
    pending = release_fixture.repository.transition_approval(
        second.release_item_id,
        acting_user_id=EDITOR_ID,
        command=ReleaseApprovalCommand(
            expected_management_version=updated.management_version,
            target=ReleaseApprovalStatus.PENDING_REVIEW,
            reason="跨平台复用仍需独立审核",
        ),
    )
    approved = release_fixture.repository.transition_approval(
        second.release_item_id,
        acting_user_id=REVIEWER_ID,
        command=ReleaseApprovalCommand(
            expected_management_version=pending.management_version,
            target=ReleaseApprovalStatus.APPROVED,
            reason="确认跨平台复用计划",
        ),
    )

    duplicate = next(
        check for check in approved.preflight.checks if check.code == "duplicate_content"
    )
    assert duplicate.outcome == "warning"
    assert f"v{first_package.version:03d}" in duplicate.message
    assert "源区间重叠 100%" in duplicate.message
    assert approved.preflight.passed is True
    second_ready = release_fixture.repository.transition_status(
        second.release_item_id,
        acting_user_id=EDITOR_ID,
        command=ReleaseStatusCommand(
            expected_management_version=approved.management_version,
            target=ReleaseItemStatus.READY,
        ),
    )
    _complete_test_package(
        release_fixture,
        second_ready.release_item_id,
        second_ready.management_version,
    )
    assert release_fixture.repository.get_package(first_package.release_package_id).current is True
    published = release_fixture.repository.transition_status(
        first.release_item_id,
        acting_user_id=EDITOR_ID,
        command=ReleaseStatusCommand(
            expected_management_version=first.management_version,
            target=ReleaseItemStatus.PUBLISHED,
            release_package_id=first_package.release_package_id,
            external_id="cross-platform-source-remains-current",
            published_at=NOW,
        ),
    )
    assert published.status is ReleaseItemStatus.PUBLISHED


def test_duplicate_active_release_package_is_rejected_transactionally(
    release_fixture: ReleaseFixture,
) -> None:
    ready = _ready_item(release_fixture)
    first = release_fixture.repository.enqueue_package(
        ready.release_item_id,
        requested_by_user_id=EDITOR_ID,
        request=ReleasePackageRequest(
            expected_release_item_version=ready.management_version,
        ),
        max_retries=1,
    )

    with pytest.raises(ReleaseConflict, match="already queued or creating"):
        release_fixture.repository.enqueue_package(
            ready.release_item_id,
            requested_by_user_id=EDITOR_ID,
            request=ReleasePackageRequest(
                expected_release_item_version=ready.management_version,
            ),
            max_retries=1,
        )
    assert release_fixture.repository.get_package(first.release_package_id).status is (
        ReleasePackageStatus.QUEUED
    )


def test_assignee_only_update_immediately_invalidates_offline_package(
    release_fixture: ReleaseFixture,
) -> None:
    ready = _ready_item(release_fixture)
    queued = release_fixture.repository.enqueue_package(
        ready.release_item_id,
        requested_by_user_id=EDITOR_ID,
        request=ReleasePackageRequest(
            expected_release_item_version=ready.management_version,
        ),
        max_retries=1,
    )

    updated = release_fixture.repository.update_item(
        ready.release_item_id,
        acting_user_id=EDITOR_ID,
        command=_complete_update(ready.management_version).model_copy(
            update={"assignee_user_id": OWNER_ID}
        ),
    )

    package = release_fixture.repository.get_package(queued.release_package_id)
    assert updated.status is ReleaseItemStatus.READY
    assert package.status is ReleasePackageStatus.FAILED
    assert package.error_code == "RELEASE_PACKAGE_STALE"
    with release_fixture.engine.connect() as connection:
        task = connection.execute(
            select(TaskRow.status, TaskRow.cancellation_requested_at).where(
                TaskRow.id == queued.task_id
            )
        ).one()
    assert task.status == TaskStatus.CANCELLED.value
    assert task.cancellation_requested_at is not None


def test_scheduling_immediately_invalidates_package_from_prior_item_version(
    release_fixture: ReleaseFixture,
) -> None:
    ready = _ready_item(release_fixture)
    queued = release_fixture.repository.enqueue_package(
        ready.release_item_id,
        requested_by_user_id=EDITOR_ID,
        request=ReleasePackageRequest(
            expected_release_item_version=ready.management_version,
        ),
        max_retries=1,
    )

    scheduled = release_fixture.repository.transition_status(
        ready.release_item_id,
        acting_user_id=EDITOR_ID,
        command=ReleaseStatusCommand(
            expected_management_version=ready.management_version,
            target=ReleaseItemStatus.SCHEDULED_EXTERNAL,
        ),
    )

    assert scheduled.status is ReleaseItemStatus.SCHEDULED_EXTERNAL
    assert release_fixture.repository.get_package(queued.release_package_id).status is (
        ReleasePackageStatus.FAILED
    )


def test_revoking_release_approval_returns_to_draft_and_invalidates_active_package(
    release_fixture: ReleaseFixture,
) -> None:
    ready = _ready_item(release_fixture)
    queued = release_fixture.repository.enqueue_package(
        ready.release_item_id,
        requested_by_user_id=EDITOR_ID,
        request=ReleasePackageRequest(
            expected_release_item_version=ready.management_version,
        ),
        max_retries=1,
    )

    returned = release_fixture.repository.transition_approval(
        ready.release_item_id,
        acting_user_id=REVIEWER_ID,
        command=ReleaseApprovalCommand(
            expected_management_version=ready.management_version,
            target=ReleaseApprovalStatus.CHANGES_REQUESTED,
            reason="封面和文案需要重新检查",
        ),
    )

    assert returned.status is ReleaseItemStatus.DRAFT
    assert returned.approval_status is ReleaseApprovalStatus.CHANGES_REQUESTED
    assert release_fixture.repository.get_package(queued.release_package_id).status is (
        ReleasePackageStatus.FAILED
    )


def test_editor_cannot_revoke_an_approved_release_to_draft(
    release_fixture: ReleaseFixture,
) -> None:
    ready = _ready_item(release_fixture)

    with pytest.raises(ReleaseConflict, match="no longer has release permission"):
        release_fixture.repository.transition_approval(
            ready.release_item_id,
            acting_user_id=EDITOR_ID,
            command=ReleaseApprovalCommand(
                expected_management_version=ready.management_version,
                target=ReleaseApprovalStatus.DRAFT,
                reason="编辑者不能绕过发布审核人撤销批准",
            ),
        )

    unchanged = release_fixture.repository.get_item(ready.release_item_id)
    assert unchanged.status is ReleaseItemStatus.READY
    assert unchanged.approval_status is ReleaseApprovalStatus.APPROVED
    assert unchanged.management_version == ready.management_version


@pytest.mark.parametrize("running", [False, True])
def test_content_review_change_invalidates_queued_or_running_release_package(
    release_fixture: ReleaseFixture,
    running: bool,
) -> None:
    ready = _ready_item(release_fixture)
    queued = release_fixture.repository.enqueue_package(
        ready.release_item_id,
        requested_by_user_id=EDITOR_ID,
        request=ReleasePackageRequest(
            expected_release_item_version=ready.management_version,
        ),
        max_retries=1,
    )
    if running:
        claimed = SQLiteTaskQueue(release_fixture.engine, lease_seconds=60).claim(
            worker_id="review-invalidation-worker",
            task_kind=TaskKind.DELIVERY,
        )
        assert claimed is not None and claimed.task_id == queued.task_id
        release_fixture.repository.start_release_package(
            LeaseIdentity(
                task_id=claimed.task_id,
                worker_id=claimed.worker_id,
                lease_token=claimed.lease_token,
            )
        )

    SqlAlchemyReviewRepository(release_fixture.engine).review_clip(
        CLIP_ID,
        ReviewCommand(
            expected_revision=1,
            status=ReviewStatus.REJECTED,
            reason="内容审核撤回，平台包必须立即失效",
        ),
    )

    package = release_fixture.repository.get_package(queued.release_package_id)
    assert package.status is ReleasePackageStatus.FAILED
    with release_fixture.engine.connect() as connection:
        task = connection.execute(
            select(TaskRow.status, TaskRow.cancellation_requested_at).where(
                TaskRow.id == queued.task_id
            )
        ).one()
    assert task.status == (TaskStatus.RUNNING.value if running else TaskStatus.CANCELLED.value)
    assert task.cancellation_requested_at is not None


def test_revising_one_clip_invalidates_active_packages_for_other_project_clips(
    release_fixture: ReleaseFixture,
) -> None:
    ready = _ready_item(release_fixture)
    first_package = release_fixture.repository.enqueue_package(
        ready.release_item_id,
        requested_by_user_id=EDITOR_ID,
        request=ReleasePackageRequest(
            expected_release_item_version=ready.management_version,
        ),
        max_retries=1,
    )
    other_clip_id = "d" * 32
    other_revision_id = "e" * 32
    other_item_id = "release-item-other-clip"
    other_package_id = "release-package-other-clip"
    other_task_id = "release-task-other-clip"
    with release_fixture.engine.begin() as connection:
        source_revision = (
            connection.execute(
                select(EditPlanRevisionRow.__table__).where(EditPlanRevisionRow.id == REVISION_ID)
            )
            .mappings()
            .one()
        )
        source_item = (
            connection.execute(
                select(ReleaseItemRow.__table__).where(ReleaseItemRow.id == ready.release_item_id)
            )
            .mappings()
            .one()
        )
        source_task = (
            connection.execute(select(TaskRow.__table__).where(TaskRow.id == first_package.task_id))
            .mappings()
            .one()
        )
        source_package = (
            connection.execute(
                select(ReleasePackageRow.__table__).where(
                    ReleasePackageRow.id == first_package.release_package_id
                )
            )
            .mappings()
            .one()
        )
        connection.execute(
            insert(CandidateClipRow).values(
                id=other_clip_id,
                project_id=PROJECT_ID,
                pipeline_run_id=RUN_ID,
                candidate_key="release-candidate-other",
                source_start_ms=65_000,
                source_end_ms=115_000,
                allowed_start_ms=64_000,
                allowed_end_ms=118_000,
                transcript_text="另一段彼此独立的高光内容。",
                context_before="",
                context_after="",
                rule_score=88,
                reasons_json=["内容完整"],
                segment_ids_json=[],
                current_revision=1,
                rank=2,
                selected_for_review=True,
                created_at=NOW,
            )
        )
        revision_values = dict(source_revision)
        revision_values.update(id=other_revision_id, candidate_clip_id=other_clip_id)
        connection.execute(insert(EditPlanRevisionRow).values(**revision_values))
        item_values = dict(source_item)
        item_values.update(
            id=other_item_id,
            candidate_clip_id=other_clip_id,
            edit_plan_revision_id=other_revision_id,
            account_label="另一个高光账号",
        )
        connection.execute(insert(ReleaseItemRow).values(**item_values))
        task_values = dict(source_task)
        task_values.update(
            id=other_task_id,
            target_id=other_package_id,
            operation_key="release-package:other-clip:v001",
        )
        connection.execute(insert(TaskRow).values(**task_values))
        package_values = dict(source_package)
        package_values.update(
            id=other_package_id,
            release_item_id=other_item_id,
            task_id=other_task_id,
            directory_relative_path=f"release-packages/{other_item_id}/v001",
        )
        connection.execute(insert(ReleasePackageRow).values(**package_values))

    SqlAlchemyReviewRepository(release_fixture.engine).revise_clip(
        CLIP_ID,
        ClipPatch(expected_revision=1, title="修改第一个高光"),
    )

    assert release_fixture.repository.get_package(first_package.release_package_id).status is (
        ReleasePackageStatus.FAILED
    )
    assert release_fixture.repository.get_package(other_package_id).status is (
        ReleasePackageStatus.FAILED
    )
    with release_fixture.engine.connect() as connection:
        other_task = connection.execute(
            select(TaskRow.status, TaskRow.cancellation_requested_at).where(
                TaskRow.id == other_task_id
            )
        ).one()
    assert other_task.status == TaskStatus.CANCELLED.value
    assert other_task.cancellation_requested_at is not None


def test_new_pipeline_run_invalidates_release_package_and_marks_item_run_stale(
    release_fixture: ReleaseFixture,
) -> None:
    ready = _ready_item(release_fixture)
    queued = release_fixture.repository.enqueue_package(
        ready.release_item_id,
        requested_by_user_id=EDITOR_ID,
        request=ReleasePackageRequest(
            expected_release_item_version=ready.management_version,
        ),
        max_retries=1,
    )

    created = SqlAlchemyPipelineRepository(release_fixture.engine).create_run(
        project_id=PROJECT_ID,
        config=_current_pipeline_config(release_fixture),
        max_stage_retries=1,
    )
    stale = release_fixture.repository.get_item(ready.release_item_id)

    assert created.run_id != RUN_ID
    assert stale.stale is True
    assert stale.stale_reason == "project_run_changed"
    assert release_fixture.repository.get_package(queued.release_package_id).status is (
        ReleasePackageStatus.FAILED
    )


def test_revision_stale_item_can_sync_to_current_clip_and_resets_approval(
    release_fixture: ReleaseFixture,
) -> None:
    created = _create(release_fixture)
    SqlAlchemyReviewRepository(release_fixture.engine).revise_clip(
        CLIP_ID,
        ClipPatch(expected_revision=1, title="新版真实发布高光"),
    )
    stale = release_fixture.repository.get_item(created.release_item_id)

    assert stale.stale_reason == "revision_changed"
    synced = release_fixture.repository.update_item(
        created.release_item_id,
        acting_user_id=EDITOR_ID,
        command=_complete_update(stale.management_version, title="新版发布标题").model_copy(
            update={"edit_plan_revision": 2}
        ),
    )
    assert synced.edit_plan_revision == 2
    assert synced.current_edit_plan_revision == 2
    assert synced.stale is False
    assert synced.approval_status is ReleaseApprovalStatus.DRAFT


def test_release_package_pins_all_evidence_and_completes_under_lease(
    release_fixture: ReleaseFixture,
) -> None:
    ready = _ready_item(release_fixture)
    request = ReleasePackageRequest(
        expected_release_item_version=ready.management_version,
        include_zip=True,
    )
    queued = release_fixture.repository.enqueue_package(
        ready.release_item_id,
        requested_by_user_id=EDITOR_ID,
        request=request,
        max_retries=2,
    )
    queue = SQLiteTaskQueue(release_fixture.engine, lease_seconds=60)
    claimed = queue.claim(worker_id="release-package-worker", task_kind=TaskKind.DELIVERY)
    assert claimed is not None
    assert claimed.task_id == queued.task_id
    lease = LeaseIdentity(
        task_id=claimed.task_id,
        worker_id=claimed.worker_id,
        lease_token=claimed.lease_token,
    )
    work = release_fixture.repository.start_release_package(lease)
    render_snapshot = work.snapshot["render"]
    assert isinstance(render_snapshot, dict)
    assert render_snapshot["video_asset_id"] == ASSET_ID
    assert render_snapshot["subtitle_asset_id"] == SUBTITLE_ASSET_ID
    assert render_snapshot["quality_asset_id"] == QUALITY_ASSET_ID
    assert render_snapshot["contact_sheet_asset_id"] == CONTACT_ASSET_ID

    with release_fixture.engine.begin() as connection:
        attempt_id = connection.scalar(
            select(TaskAttemptRow.id).where(
                TaskAttemptRow.task_id == lease.task_id,
                TaskAttemptRow.lease_token == lease.lease_token,
            )
        )
        assert attempt_id is not None
        base = f"release-packages/{ready.release_item_id}/v001"
        connection.execute(
            insert(AssetRow).values(
                id="release-manifest-asset",
                project_id=PROJECT_ID,
                producer_attempt_id=str(attempt_id),
                status=AssetStatus.COMMITTED.value,
                kind="release_package_manifest",
                relative_path=f"{base}/manifest.json",
                mime_type="application/json",
                input_fingerprint=work.package_fingerprint,
                sha256="2" * 64,
                size_bytes=2_000,
                validation_json={
                    "schema_version": "liveclip.release-package.v1",
                    "release_package_id": work.release_package_id,
                    "snapshot_fingerprint": work.snapshot_fingerprint,
                },
                generation=1,
                revision_epoch=0,
                created_at=NOW,
                committed_at=NOW,
            )
        )
        connection.execute(
            insert(AssetRow).values(
                id="release-zip-asset",
                project_id=PROJECT_ID,
                producer_attempt_id=str(attempt_id),
                status=AssetStatus.COMMITTED.value,
                kind="release_package_zip",
                relative_path=f"{base}/{release_archive_name(work)}",
                mime_type="application/zip",
                input_fingerprint=work.package_fingerprint,
                sha256="3" * 64,
                size_bytes=20_000,
                validation_json={
                    "schema_version": "liveclip.release-package.v1",
                    "release_package_id": work.release_package_id,
                    "snapshot_fingerprint": work.snapshot_fingerprint,
                },
                generation=1,
                revision_epoch=0,
                created_at=NOW,
                committed_at=NOW,
            )
        )
    assert release_fixture.repository.complete_release_package(
        lease,
        work,
        ReleasePackagePersistence(
            manifest_asset_id="release-manifest-asset",
            zip_asset_id="release-zip-asset",
            manifest_sha256="2" * 64,
            zip_sha256="3" * 64,
        ),
    )
    completed = release_fixture.repository.get_package(work.release_package_id)
    assert completed.status.value == "succeeded"
    assert completed.package_version == "v001"


def test_release_package_publication_fence_rejects_asset_lineage_change(
    release_fixture: ReleaseFixture,
) -> None:
    ready = _ready_item(release_fixture)
    queued = release_fixture.repository.enqueue_package(
        ready.release_item_id,
        requested_by_user_id=OWNER_ID,
        request=ReleasePackageRequest(
            expected_release_item_version=ready.management_version,
        ),
        max_retries=1,
    )
    queue = SQLiteTaskQueue(release_fixture.engine, lease_seconds=60)
    claimed = queue.claim(worker_id="release-fence-worker", task_kind=TaskKind.DELIVERY)
    assert claimed is not None and claimed.task_id == queued.task_id
    lease = LeaseIdentity(
        task_id=claimed.task_id,
        worker_id=claimed.worker_id,
        lease_token=claimed.lease_token,
    )
    work = release_fixture.repository.start_release_package(lease)
    with release_fixture.engine.begin() as connection:
        connection.execute(
            update(AssetRow).where(AssetRow.id == QUALITY_ASSET_ID).values(sha256="0" * 64)
        )
    with pytest.raises(ReleaseConflict, match=r"source evidence changed|snapshot changed"):
        release_fixture.repository.assert_release_package_current(lease, work)


def test_release_package_publication_fence_observes_real_member_removal(
    release_fixture: ReleaseFixture,
) -> None:
    ready = _ready_item(release_fixture)
    queued = release_fixture.repository.enqueue_package(
        ready.release_item_id,
        requested_by_user_id=EDITOR_ID,
        request=ReleasePackageRequest(
            expected_release_item_version=ready.management_version,
        ),
        max_retries=1,
    )
    claimed = SQLiteTaskQueue(release_fixture.engine, lease_seconds=60).claim(
        worker_id="release-permission-fence-worker",
        task_kind=TaskKind.DELIVERY,
    )
    assert claimed is not None and claimed.task_id == queued.task_id
    lease = LeaseIdentity(
        task_id=claimed.task_id,
        worker_id=claimed.worker_id,
        lease_token=claimed.lease_token,
    )
    work = release_fixture.repository.start_release_package(lease)
    with release_fixture.engine.begin() as connection:
        connection.execute(
            delete(ProjectMemberRow).where(
                ProjectMemberRow.project_id == PROJECT_ID,
                ProjectMemberRow.user_id == EDITOR_ID,
            )
        )

    with pytest.raises(ReleaseConflict, match="no longer has release permission"):
        release_fixture.repository.assert_release_package_current(lease, work)


def test_release_package_retry_reuses_frozen_artifact_context_after_duplicate_change(
    release_fixture: ReleaseFixture,
) -> None:
    primary = _ready_item(release_fixture, account_label="主账号")
    queued = release_fixture.repository.enqueue_package(
        primary.release_item_id,
        requested_by_user_id=EDITOR_ID,
        request=ReleasePackageRequest(
            expected_release_item_version=primary.management_version,
        ),
        max_retries=2,
    )
    queue = SQLiteTaskQueue(release_fixture.engine, lease_seconds=10)
    first_claim_at = queued.created_at + timedelta(seconds=1)
    first = queue.claim(
        worker_id="release-crash-before-db-completion",
        task_kind=TaskKind.DELIVERY,
        now=first_claim_at,
    )
    assert first is not None and first.task_id == queued.task_id
    first_work = release_fixture.repository.start_release_package(
        LeaseIdentity(
            task_id=first.task_id,
            worker_id=first.worker_id,
            lease_token=first.lease_token,
        )
    )
    recovered_at = first_claim_at + timedelta(seconds=10)
    assert queue.recover_expired(now=recovered_at).requeued == 1

    duplicate = _ready_item(release_fixture, account_label="副账号")
    duplicate_package = release_fixture.repository.enqueue_package(
        duplicate.release_item_id,
        requested_by_user_id=EDITOR_ID,
        request=ReleasePackageRequest(
            expected_release_item_version=duplicate.management_version,
        ),
        max_retries=1,
    )
    with release_fixture.engine.begin() as connection:
        # Simulate another worker completing a cross-platform/content-equivalent
        # package while the first worker is down after publishing its directory.
        connection.execute(
            update(ReleasePackageRow)
            .where(ReleasePackageRow.id == duplicate_package.release_package_id)
            .values(
                status=ReleasePackageStatus.SUCCEEDED.value,
                completed_at=recovered_at,
            )
        )
        connection.execute(
            update(TaskRow)
            .where(TaskRow.id == duplicate_package.task_id)
            .values(
                status=TaskStatus.SUCCEEDED.value,
                completed_at=recovered_at,
                updated_at=recovered_at,
            )
        )
        # These names are artifact-facing display values, not authority data.
        connection.execute(
            update(ProjectRow).where(ProjectRow.id == PROJECT_ID).values(name="队列等待期间改名")
        )
        connection.execute(
            update(WorkspaceUserRow)
            .where(WorkspaceUserRow.id == EDITOR_ID)
            .values(username="editor-renamed")
        )

    second = queue.claim(
        worker_id="release-recovery-after-directory-publish",
        task_kind=TaskKind.DELIVERY,
        now=recovered_at + timedelta(seconds=1),
    )
    assert second is not None and second.task_id == queued.task_id
    recovered_work = release_fixture.repository.start_release_package(
        LeaseIdentity(
            task_id=second.task_id,
            worker_id=second.worker_id,
            lease_token=second.lease_token,
        )
    )

    assert recovered_work.snapshot == first_work.snapshot
    assert recovered_work.snapshot_fingerprint == first_work.snapshot_fingerprint
    assert recovered_work.preflight == first_work.preflight
    assert recovered_work.project_name == first_work.project_name == "发布计划测试"
    assert recovered_work.requested_by_username == first_work.requested_by_username == "editor"
    duplicate_check = next(
        check for check in recovered_work.preflight.checks if check.code == "duplicate_content"
    )
    assert duplicate_check.outcome == "passed"


def test_release_package_lease_recovery_and_cancel_keep_resource_in_sync(
    release_fixture: ReleaseFixture,
) -> None:
    ready = _ready_item(release_fixture)
    queued = release_fixture.repository.enqueue_package(
        ready.release_item_id,
        requested_by_user_id=EDITOR_ID,
        request=ReleasePackageRequest(
            expected_release_item_version=ready.management_version,
        ),
        max_retries=1,
    )
    queue = SQLiteTaskQueue(release_fixture.engine, lease_seconds=10)
    claim_time = queued.created_at + timedelta(seconds=1)
    first = queue.claim(
        worker_id="release-recovery-a",
        task_kind=TaskKind.DELIVERY,
        now=claim_time,
    )
    assert first is not None and first.task_id == queued.task_id
    release_fixture.repository.start_release_package(
        LeaseIdentity(
            task_id=first.task_id,
            worker_id=first.worker_id,
            lease_token=first.lease_token,
        )
    )

    recovered = queue.recover_expired(now=claim_time + timedelta(seconds=10))
    assert recovered.requeued == 1
    assert release_fixture.repository.get_package(queued.release_package_id).status is (
        ReleasePackageStatus.QUEUED
    )

    second = queue.claim(
        worker_id="release-recovery-b",
        task_kind=TaskKind.DELIVERY,
        now=claim_time + timedelta(seconds=10),
    )
    assert second is not None and second.task_id == queued.task_id
    release_fixture.repository.start_release_package(
        LeaseIdentity(
            task_id=second.task_id,
            worker_id=second.worker_id,
            lease_token=second.lease_token,
        )
    )
    exhausted = queue.recover_expired(now=claim_time + timedelta(seconds=20))
    assert exhausted.failed == 1
    assert release_fixture.repository.get_package(queued.release_package_id).status is (
        ReleasePackageStatus.FAILED
    )

    cancelled = release_fixture.repository.enqueue_package(
        ready.release_item_id,
        requested_by_user_id=EDITOR_ID,
        request=ReleasePackageRequest(
            expected_release_item_version=ready.management_version,
        ),
        max_retries=1,
    )
    assert queue.request_cancel(
        cancelled.task_id,
        now=claim_time + timedelta(seconds=21),
    ) is (TaskStatus.CANCELLED)
    with release_fixture.engine.connect() as connection:
        status = connection.scalar(
            select(ReleasePackageRow.status).where(
                ReleasePackageRow.id == cancelled.release_package_id
            )
        )
    assert status == ReleasePackageStatus.FAILED.value
