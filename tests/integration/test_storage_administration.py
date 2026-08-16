from __future__ import annotations

import os
import threading
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select

import liveclip.db.storage_repository as storage_repository_module
from liveclip.api.app import create_app
from liveclip.application.identity import AdministrationDenied
from liveclip.application.storage import ProjectPurgeCommand, StorageConflict
from liveclip.application.workspace import WorkspaceUser
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings
from liveclip.db.models import (
    AuditEventRow,
    CandidateClipRow,
    ClipCommentRow,
    ClipCommentThreadRow,
    EditPlanRevisionRow,
    IdempotencyRecordRow,
    PipelineRunRow,
    ProjectMemberRow,
    ProjectRow,
    SourceMediaRow,
    TaskRow,
    WorkspaceUserRow,
)
from liveclip.db.task_queue import TaskSpec
from liveclip.domain.project_lifecycle import ProjectLifecycle
from liveclip.domain.state_transitions import (
    PipelineRunStatus,
    ResourceClass,
    TaskKind,
    TaskStatus,
)
from liveclip.media.secure_files import (
    SecureFileError,
    interrupted_tree_cleanup_path,
    publish_directory_no_replace_no_follow,
)
from liveclip.services.database_backup import inspect_database

pytestmark = pytest.mark.integration


def test_storage_reads_recheck_administrator_after_long_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    runtime = LiveClipRuntime.open(
        Settings(
            data_dir=tmp_path / "projects",
            allowed_media_roots_raw=str(tmp_path),
            ai_provider="mock",
            bootstrap_admin_password="administrator password 2026",
            _env_file=None,
        ),
        project_root=project_root,
    )
    project_id = "0" * 32
    now = datetime(2026, 8, 15, tzinfo=UTC)
    try:
        stale_admin = runtime.workspace_service.get_user_by_username("local-admin")
        second_admin = runtime.user_administration_service.create_user(
            actor=stale_admin,
            username="storage-fence-admin",
            display_name="存储复核管理员",
            system_role="administrator",
            password="storage fence administrator 2026",
        ).user.as_workspace_user()
        with runtime.engine.begin() as connection:
            connection.execute(
                insert(ProjectRow).values(
                    id=project_id,
                    name="私有存储项目",
                    owner_id=stale_admin.user_id,
                    visibility="private",
                    lifecycle=ProjectLifecycle.ARCHIVED.value,
                    lifecycle_before_archive=ProjectLifecycle.DRAFT.value,
                    management_version=1,
                    priority="normal",
                    archived_at=now,
                    source_request_path=str(tmp_path / "external-source.ts"),
                    current_generation=0,
                    current_pipeline_run_id=None,
                    revision_epoch=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(ProjectMemberRow).values(
                    id="1" * 32,
                    project_id=project_id,
                    user_id=stale_admin.user_id,
                    role="owner",
                    created_at=now,
                )
            )

        real_report = storage_repository_module._storage_report

        def revoke_after_report_scan(*args: object, **kwargs: object) -> object:
            report = real_report(*args, **kwargs)  # type: ignore[arg-type]
            runtime.user_administration_service.update_user(
                actor=second_admin,
                user_id=stale_admin.user_id,
                system_role="member",
            )
            return report

        monkeypatch.setattr(
            storage_repository_module,
            "_storage_report",
            revoke_after_report_scan,
        )
        with pytest.raises(AdministrationDenied):
            runtime.storage_administration_service.report(stale_admin)

        runtime.user_administration_service.update_user(
            actor=second_admin,
            user_id=stale_admin.user_id,
            system_role="administrator",
        )
        monkeypatch.setattr(storage_repository_module, "_storage_report", real_report)
        real_snapshot = storage_repository_module._project_purge_snapshot

        def revoke_after_plan_scan(*args: object, **kwargs: object) -> object:
            snapshot = real_snapshot(*args, **kwargs)  # type: ignore[arg-type]
            runtime.user_administration_service.update_user(
                actor=second_admin,
                user_id=stale_admin.user_id,
                system_role="member",
            )
            return snapshot

        monkeypatch.setattr(
            storage_repository_module,
            "_project_purge_snapshot",
            revoke_after_plan_scan,
        )
        with pytest.raises(AdministrationDenied):
            runtime.storage_administration_service.project_purge_plan(
                stale_admin,
                project_id,
            )
    finally:
        runtime.close()


def test_storage_inventory_and_confirmed_archived_project_purge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    data_dir = tmp_path / "projects"
    source = tmp_path / "source.ts"
    source.write_bytes(b"source-media-must-survive")
    runtime = LiveClipRuntime.open(
        Settings(
            data_dir=data_dir,
            allowed_media_roots_raw=str(tmp_path),
            ai_provider="mock",
            bootstrap_admin_password="administrator password 2026",
            _env_file=None,
        ),
        project_root=project_root,
    )
    project_id = "a" * 32
    run_id = "b" * 32
    task_id = "c" * 32
    clip_id = "6" * 32
    revision_id = "7" * 32
    comment_thread_id = "8" * 32
    comment_id = "9" * 32
    now = datetime(2026, 8, 15, tzinfo=UTC)
    try:
        with runtime.engine.begin() as connection:
            admin_row = connection.execute(
                select(
                    WorkspaceUserRow.id,
                    WorkspaceUserRow.username,
                    WorkspaceUserRow.display_name,
                    WorkspaceUserRow.system_role,
                ).where(WorkspaceUserRow.username == "local-admin")
            ).one()
            connection.execute(
                insert(ProjectRow).values(
                    id=project_id,
                    name="待清除项目",
                    owner_id=admin_row.id,
                    visibility="private",
                    lifecycle=ProjectLifecycle.ARCHIVED.value,
                    lifecycle_before_archive=ProjectLifecycle.EDITORIAL_REVIEW.value,
                    management_version=4,
                    assignee_user_id=None,
                    priority="normal",
                    due_at=None,
                    archived_at=now,
                    source_request_path=str(source),
                    current_generation=1,
                    current_pipeline_run_id=run_id,
                    revision_epoch=2,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(ProjectMemberRow).values(
                    id="d" * 32,
                    project_id=project_id,
                    user_id=admin_row.id,
                    role="owner",
                    created_at=now,
                )
            )
            connection.execute(
                insert(SourceMediaRow).values(
                    id="e" * 32,
                    project_id=project_id,
                    resolved_path=str(source),
                    filename=source.name,
                    sha256="f" * 64,
                    size_bytes=source.stat().st_size,
                    mtime_ns=source.stat().st_mtime_ns,
                    device=source.stat().st_dev,
                    inode=source.stat().st_ino,
                    duration_ms=1_000,
                    width=1920,
                    height=1080,
                    video_stream_index=0,
                    audio_stream_index=1,
                    video_rotation_degrees=0,
                    video_codec="h264",
                    audio_codec="aac",
                    frame_rate="25/1",
                    probe_json={"format": {}},
                    created_at=now,
                )
            )
            connection.execute(
                insert(PipelineRunRow).values(
                    id=run_id,
                    project_id=project_id,
                    generation=1,
                    status=PipelineRunStatus.COMPLETED.value,
                    config_json={"top_n": 1},
                    config_fingerprint="1" * 64,
                    progress=100,
                    manual_retry_count=0,
                    created_at=now,
                    updated_at=now,
                    finished_at=now,
                )
            )
            connection.execute(
                insert(TaskRow).values(
                    id=task_id,
                    kind=TaskKind.DELIVERY.value,
                    target_id="2" * 32,
                    operation_key="storage-purge-terminal-task",
                    input_fingerprint="3" * 64,
                    resource_class=ResourceClass.CHEAP.value,
                    pipeline_run_id=run_id,
                    status=TaskStatus.SUCCEEDED.value,
                    priority=100,
                    not_before=now,
                    attempt_count=0,
                    retry_count=0,
                    manual_retry_count=0,
                    max_retries=0,
                    created_at=now,
                    updated_at=now,
                    completed_at=now,
                )
            )
            connection.execute(
                insert(CandidateClipRow).values(
                    id=clip_id,
                    project_id=project_id,
                    pipeline_run_id=run_id,
                    candidate_key="purge-comment-candidate",
                    source_start_ms=0,
                    source_end_ms=1_000,
                    allowed_start_ms=0,
                    allowed_end_ms=1_000,
                    transcript_text="待清除批注",
                    context_before="",
                    context_after="",
                    rule_score=80,
                    reasons_json=["测试"],
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
                    source_start_ms=0,
                    source_end_ms=1_000,
                    score=80,
                    title="待清除批注",
                    hook="关键语句",
                    reason="测试",
                    layout="center_crop",
                    caption_template="clean_zh_v1",
                    effect="none",
                    risk_flags_json=[],
                    prompt_version="editing_v1",
                    model="mock",
                    degraded=True,
                    plan_json={"schema_version": "1"},
                )
            )
            connection.execute(
                insert(ClipCommentThreadRow).values(
                    id=comment_thread_id,
                    edit_plan_revision_id=revision_id,
                    source_time_ms=500,
                    clip_time_ms=500,
                    status="open",
                    version=1,
                    created_by_user_id=admin_row.id,
                    created_by_username=admin_row.username,
                    created_by_display_name=admin_row.display_name,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(ClipCommentRow).values(
                    id=comment_id,
                    thread_id=comment_thread_id,
                    sequence=1,
                    author_user_id=admin_row.id,
                    author_username=admin_row.username,
                    author_display_name=admin_row.display_name,
                    body="Project purge 必须清理这条批注",
                    created_at=now,
                )
            )
            for index, resource_id in enumerate((comment_thread_id, "z" * 32), start=1):
                connection.execute(
                    insert(IdempotencyRecordRow).values(
                        id=f"idem{index:028d}",
                        caller_scope="user:local-admin",
                        operation_scope=f"POST:/comments/{index}",
                        key_hash=str(index) * 64,
                        request_hash=str(index + 2) * 64,
                        canonical_schema_version="1",
                        resource_type="clip_comment_thread",
                        resource_id=resource_id,
                        status="completed",
                        response_status_code=201,
                        created_at=now,
                        completed_at=now,
                    )
                )
        admin = WorkspaceUser(
            user_id=str(admin_row.id),
            username=str(admin_row.username),
            display_name=str(admin_row.display_name),
            system_role="administrator",
        )

        project_dir = data_dir / project_id
        (project_dir / "renders").mkdir(parents=True)
        (project_dir / "renders" / "clip.mp4").write_bytes(b"generated-video")
        unknown = data_dir / "unknown-project"
        unknown.mkdir()
        (unknown / "orphan.bin").write_bytes(b"orphan")
        external = tmp_path / "outside.bin"
        external.write_bytes(b"must-not-be-counted" * 50)
        with suppress(OSError, NotImplementedError):
            os.symlink(external, unknown / "outside-link")

        report = runtime.storage_administration_service.report(admin)
        usage = next(item for item in report.projects if item.project_id == project_id)
        assert usage.actual_bytes == len(b"generated-video")
        assert report.unknown_project_directory_bytes == len(b"orphan")
        assert report.unsafe_entry_count >= int((unknown / "outside-link").is_symlink())
        assert report.policy.destructive_project_purge_available is True

        plan = runtime.storage_administration_service.project_purge_plan(admin, project_id)
        assert plan.ready is True
        assert plan.source_media_preserved is True
        assert plan.active_run_count == 0
        assert plan.generated_file_count == 1
        assert plan.generated_bytes == len(b"generated-video")

        wrong = ProjectPurgeCommand(
            snapshot_fingerprint=plan.snapshot_fingerprint,
            project_name=plan.project_name,
            administrator_username=admin.username,
            confirmation_phrase="PURGE wrong-project",
        )
        with pytest.raises(StorageConflict, match="confirmation phrase"):
            runtime.storage_administration_service.purge_project(admin, project_id, wrong)
        assert project_dir.exists()
        assert source.read_bytes() == b"source-media-must-survive"

        (project_dir / "scope-changed.txt").write_text("new generated scope", encoding="utf-8")
        with pytest.raises(StorageConflict, match="preview is stale"):
            runtime.storage_administration_service.purge_project(
                admin,
                project_id,
                ProjectPurgeCommand(
                    snapshot_fingerprint=plan.snapshot_fingerprint,
                    project_name=plan.project_name,
                    administrator_username=admin.username,
                    confirmation_phrase=plan.confirmation_phrase,
                ),
            )
        plan = runtime.storage_administration_service.project_purge_plan(admin, project_id)
        assert plan.generated_file_count == 2

        real_remove_tree = storage_repository_module.remove_tree_no_follow
        failed_once = False

        def fail_first_quarantine_cleanup(
            path: Path,
            *,
            required_ancestor: Path,
            expected_identity: tuple[int, int] | None = None,
        ) -> bool:
            nonlocal failed_once
            if not failed_once:
                failed_once = True
                assert expected_identity is not None
                publish_directory_no_replace_no_follow(
                    path,
                    interrupted_tree_cleanup_path(path),
                    expected_identity=expected_identity,
                )
                raise SecureFileError("simulated process exit after cleanup quarantine rename")
            return real_remove_tree(
                path,
                required_ancestor=required_ancestor,
                expected_identity=expected_identity,
            )

        monkeypatch.setattr(
            storage_repository_module,
            "remove_tree_no_follow",
            fail_first_quarantine_cleanup,
        )

        result = runtime.storage_administration_service.purge_project(
            admin,
            project_id,
            ProjectPurgeCommand(
                snapshot_fingerprint=plan.snapshot_fingerprint,
                project_name=plan.project_name,
                administrator_username=admin.username,
                confirmation_phrase=plan.confirmation_phrase,
            ),
        )
        assert result.project_id == project_id
        assert result.source_media_preserved is True
        assert result.filesystem_cleanup_pending is True
        assert not project_dir.exists()
        assert source.read_bytes() == b"source-media-must-survive"
        pending_report = runtime.storage_administration_service.report(admin)
        assert pending_report.purge_quarantine_file_count == 2
        cleanup = runtime.storage_administration_service.cleanup_terminal_attempts(admin)
        assert cleanup.inspected_purge_quarantines == 1
        assert cleanup.cleaned_purge_quarantines == 1
        assert cleanup.failed_purge_quarantines == 0
        assert cleanup.report.purge_quarantine_file_count == 0
        backup = data_dir / "database-backups" / result.database_backup_filename
        assert backup.is_file()
        assert inspect_database(backup).quick_check == "ok"

        with runtime.engine.connect() as connection:
            assert (
                connection.scalar(
                    select(func.count()).select_from(ProjectRow).where(ProjectRow.id == project_id)
                )
                == 0
            )
            assert connection.scalar(select(func.count(ClipCommentThreadRow.id))) == 0
            assert connection.scalar(select(func.count(ClipCommentRow.id))) == 0
            assert (
                connection.scalar(
                    select(func.count(IdempotencyRecordRow.id)).where(
                        IdempotencyRecordRow.resource_id == comment_thread_id
                    )
                )
                == 0
            )
            assert (
                connection.scalar(
                    select(func.count(IdempotencyRecordRow.id)).where(
                        IdempotencyRecordRow.resource_id == "z" * 32
                    )
                )
                == 1
            )
            assert (
                connection.scalar(
                    select(func.count()).select_from(TaskRow).where(TaskRow.id == task_id)
                )
                == 0
            )
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(AuditEventRow)
                    .where(
                        AuditEventRow.action == "storage.project_purge_completed",
                        AuditEventRow.target_id == project_id,
                    )
                )
                == 1
            )
    finally:
        runtime.close()


def test_project_purge_blocks_active_work_and_source_inside_project_dir(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    data_dir = tmp_path / "projects"
    runtime = LiveClipRuntime.open(
        Settings(
            data_dir=data_dir,
            allowed_media_roots_raw=str(tmp_path),
            ai_provider="mock",
            bootstrap_admin_password="administrator password 2026",
            _env_file=None,
        ),
        project_root=project_root,
    )
    project_id = "4" * 32
    project_dir = data_dir / project_id
    project_dir.mkdir()
    source = project_dir / "source.ts"
    source.write_bytes(b"source")
    now = datetime(2026, 8, 15, tzinfo=UTC)
    try:
        with runtime.engine.begin() as connection:
            admin_row = connection.execute(
                select(
                    WorkspaceUserRow.id,
                    WorkspaceUserRow.username,
                    WorkspaceUserRow.display_name,
                ).where(WorkspaceUserRow.username == "local-admin")
            ).one()
            connection.execute(
                insert(ProjectRow).values(
                    id=project_id,
                    name="危险源路径",
                    owner_id=admin_row.id,
                    visibility="private",
                    lifecycle=ProjectLifecycle.ARCHIVED.value,
                    lifecycle_before_archive=ProjectLifecycle.DRAFT.value,
                    management_version=1,
                    priority="normal",
                    archived_at=now,
                    source_request_path=str(source),
                    current_generation=0,
                    current_pipeline_run_id=None,
                    revision_epoch=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(SourceMediaRow).values(
                    id="5" * 32,
                    project_id=project_id,
                    resolved_path=str(source),
                    filename=source.name,
                    sha256="6" * 64,
                    size_bytes=source.stat().st_size,
                    mtime_ns=source.stat().st_mtime_ns,
                    device=source.stat().st_dev,
                    inode=source.stat().st_ino,
                    duration_ms=1_000,
                    width=640,
                    height=360,
                    video_stream_index=0,
                    audio_stream_index=1,
                    video_rotation_degrees=0,
                    video_codec="h264",
                    audio_codec="aac",
                    frame_rate="25/1",
                    probe_json={"format": {}},
                    created_at=now,
                )
            )
        admin = WorkspaceUser(
            user_id=str(admin_row.id),
            username=str(admin_row.username),
            display_name=str(admin_row.display_name),
            system_role="administrator",
        )
        plan = runtime.storage_administration_service.project_purge_plan(admin, project_id)
        assert plan.ready is False
        assert plan.blockers == ("source_reference_inside_generated_project_directory",)
        assert source.exists()
    finally:
        runtime.close()


def test_project_purge_tree_verification_does_not_block_worker_heartbeat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    data_dir = tmp_path / "projects"
    runtime = LiveClipRuntime.open(
        Settings(
            data_dir=data_dir,
            allowed_media_roots_raw=str(tmp_path),
            ai_provider="mock",
            bootstrap_admin_password="administrator password 2026",
            _env_file=None,
        ),
        project_root=project_root,
    )
    purge_project_id = "4" * 32
    active_project_id = "5" * 32
    active_run_id = "6" * 32
    now = datetime.now(UTC)
    try:
        with runtime.engine.begin() as connection:
            admin_row = connection.execute(
                select(
                    WorkspaceUserRow.id,
                    WorkspaceUserRow.username,
                    WorkspaceUserRow.display_name,
                ).where(WorkspaceUserRow.username == "local-admin")
            ).one()
            connection.execute(
                insert(ProjectRow).values(
                    id=purge_project_id,
                    name="慢速扫描清除",
                    owner_id=admin_row.id,
                    visibility="private",
                    lifecycle=ProjectLifecycle.ARCHIVED.value,
                    lifecycle_before_archive=ProjectLifecycle.DRAFT.value,
                    management_version=1,
                    priority="normal",
                    archived_at=now,
                    source_request_path=str(tmp_path / "external-purge.ts"),
                    current_generation=0,
                    current_pipeline_run_id=None,
                    revision_epoch=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(ProjectRow).values(
                    id=active_project_id,
                    name="活跃项目",
                    owner_id=admin_row.id,
                    visibility="private",
                    lifecycle=ProjectLifecycle.PROCESSING.value,
                    management_version=1,
                    priority="normal",
                    source_request_path=str(tmp_path / "external-active.ts"),
                    current_generation=1,
                    current_pipeline_run_id=active_run_id,
                    revision_epoch=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(PipelineRunRow).values(
                    id=active_run_id,
                    project_id=active_project_id,
                    generation=1,
                    status=PipelineRunStatus.RUNNING.value,
                    config_json={"top_n": 1},
                    config_fingerprint="7" * 64,
                    progress=0,
                    manual_retry_count=0,
                    created_at=now,
                    updated_at=now,
                )
            )
        purge_dir = data_dir / purge_project_id
        purge_dir.mkdir()
        (purge_dir / "large-generated.mp4").write_bytes(b"generated")
        active_task_id = runtime.task_queue.enqueue(
            TaskSpec(
                kind=TaskKind.RENDER,
                target_id="8" * 32,
                operation_key="render:purge-heartbeat",
                input_fingerprint="9" * 64,
                pipeline_run_id=active_run_id,
                resource_class=ResourceClass.HEAVY,
            ),
            now=now,
        ).task_id
        active_lease = runtime.task_queue.claim(worker_id="active-worker", now=now)
        assert active_lease is not None and active_lease.task_id == active_task_id
        admin = WorkspaceUser(
            user_id=str(admin_row.id),
            username=str(admin_row.username),
            display_name=str(admin_row.display_name),
            system_role="administrator",
        )
        plan = runtime.storage_administration_service.project_purge_plan(
            admin,
            purge_project_id,
        )
        verify_started = threading.Event()
        allow_verify = threading.Event()
        real_verify = storage_repository_module._verify_quarantined_project_tree

        def block_tree_verification(*args: object, **kwargs: object) -> None:
            verify_started.set()
            assert allow_verify.wait(timeout=5)
            real_verify(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(
            storage_repository_module,
            "_verify_quarantined_project_tree",
            block_tree_verification,
        )
        results: list[object] = []
        failures: list[BaseException] = []

        def purge() -> None:
            try:
                results.append(
                    runtime.storage_administration_service.purge_project(
                        admin,
                        purge_project_id,
                        ProjectPurgeCommand(
                            snapshot_fingerprint=plan.snapshot_fingerprint,
                            project_name=plan.project_name,
                            administrator_username=admin.username,
                            confirmation_phrase=plan.confirmation_phrase,
                        ),
                    )
                )
            except BaseException as exc:  # pragma: no cover - surfaced below
                failures.append(exc)

        purge_thread = threading.Thread(target=purge)
        purge_thread.start()
        assert verify_started.wait(timeout=5)
        try:
            assert runtime.task_queue.heartbeat(active_lease, now=now) is not None
        finally:
            allow_verify.set()
            purge_thread.join(timeout=10)
        assert not purge_thread.is_alive()
        assert not failures
        assert results
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "reference_kind",
    ("own_request_without_ingest", "other_request_without_ingest", "other_source_media"),
)
def test_project_purge_protects_every_project_source_reference(
    tmp_path: Path,
    reference_kind: str,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    data_dir = tmp_path / "projects"
    runtime = LiveClipRuntime.open(
        Settings(
            data_dir=data_dir,
            allowed_media_roots_raw=str(tmp_path),
            ai_provider="mock",
            bootstrap_admin_password="administrator password 2026",
            _env_file=None,
        ),
        project_root=project_root,
    )
    target_id = "8" * 32
    referencing_id = "9" * 32
    target_dir = data_dir / target_id
    target_dir.mkdir()
    referenced_source = target_dir / "must-survive.ts"
    referenced_source.write_bytes(b"cross-project-source")
    external_source = tmp_path / "external.ts"
    external_source.write_bytes(b"external")
    now = datetime(2026, 8, 15, tzinfo=UTC)
    try:
        with runtime.engine.begin() as connection:
            admin_row = connection.execute(
                select(
                    WorkspaceUserRow.id,
                    WorkspaceUserRow.username,
                    WorkspaceUserRow.display_name,
                ).where(WorkspaceUserRow.username == "local-admin")
            ).one()
            connection.execute(
                insert(ProjectRow).values(
                    id=target_id,
                    name="被引用的归档项目",
                    owner_id=admin_row.id,
                    visibility="private",
                    lifecycle=ProjectLifecycle.ARCHIVED.value,
                    lifecycle_before_archive=ProjectLifecycle.DRAFT.value,
                    management_version=1,
                    priority="normal",
                    archived_at=now,
                    source_request_path=str(
                        referenced_source
                        if reference_kind == "own_request_without_ingest"
                        else external_source
                    ),
                    current_generation=0,
                    revision_epoch=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            if reference_kind != "own_request_without_ingest":
                connection.execute(
                    insert(ProjectRow).values(
                        id=referencing_id,
                        name="引用项目",
                        owner_id=admin_row.id,
                        visibility="private",
                        lifecycle=ProjectLifecycle.DRAFT.value,
                        management_version=1,
                        priority="normal",
                        source_request_path=str(
                            referenced_source
                            if reference_kind == "other_request_without_ingest"
                            else external_source
                        ),
                        current_generation=0,
                        revision_epoch=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
            if reference_kind == "other_source_media":
                metadata = referenced_source.stat()
                connection.execute(
                    insert(SourceMediaRow).values(
                        id="a" * 32,
                        project_id=referencing_id,
                        resolved_path=str(referenced_source),
                        filename=referenced_source.name,
                        sha256="b" * 64,
                        size_bytes=metadata.st_size,
                        mtime_ns=metadata.st_mtime_ns,
                        device=metadata.st_dev,
                        inode=metadata.st_ino,
                        duration_ms=1_000,
                        width=640,
                        height=360,
                        video_stream_index=0,
                        audio_stream_index=1,
                        video_rotation_degrees=0,
                        video_codec="h264",
                        audio_codec="aac",
                        frame_rate="25/1",
                        probe_json={"format": {}},
                        created_at=now,
                    )
                )
        admin = WorkspaceUser(
            user_id=str(admin_row.id),
            username=str(admin_row.username),
            display_name=str(admin_row.display_name),
            system_role="administrator",
        )
        plan = runtime.storage_administration_service.project_purge_plan(admin, target_id)
        assert plan.ready is False
        assert plan.blockers == ("source_reference_inside_generated_project_directory",)
        assert referenced_source.read_bytes() == b"cross-project-source"
    finally:
        runtime.close()


def test_runtime_recovers_exact_started_only_project_purge_quarantine(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    data_dir = tmp_path / "projects"
    settings = Settings(
        data_dir=data_dir,
        allowed_media_roots_raw=str(tmp_path),
        ai_provider="mock",
        bootstrap_admin_password="administrator password 2026",
        _env_file=None,
    )
    runtime = LiveClipRuntime.open(settings, project_root=project_root)
    project_id = "1" * 32
    operation_id = "2" * 32
    project_dir = data_dir / project_id
    project_dir.mkdir()
    evidence = project_dir / "render.mp4"
    evidence.write_bytes(b"must be restored")
    identity = (project_dir.stat().st_dev, project_dir.stat().st_ino)
    now = datetime(2026, 8, 15, tzinfo=UTC)
    try:
        with runtime.engine.begin() as connection:
            admin = connection.execute(
                select(
                    WorkspaceUserRow.id,
                    WorkspaceUserRow.username,
                ).where(WorkspaceUserRow.username == "local-admin")
            ).one()
            connection.execute(
                insert(ProjectRow).values(
                    id=project_id,
                    name="待恢复清除",
                    owner_id=admin.id,
                    visibility="private",
                    lifecycle=ProjectLifecycle.ARCHIVED.value,
                    lifecycle_before_archive=ProjectLifecycle.DRAFT.value,
                    management_version=1,
                    priority="normal",
                    archived_at=now,
                    source_request_path=str(tmp_path / "external.ts"),
                    current_generation=0,
                    current_pipeline_run_id=None,
                    revision_epoch=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(AuditEventRow).values(
                    id="3" * 32,
                    actor_user_id=admin.id,
                    actor_username=admin.username,
                    action="storage.project_purge_started",
                    target_type="storage_cleanup",
                    target_id=operation_id,
                    project_id=None,
                    before_json=None,
                    after_json={
                        "project_id": project_id,
                        "quarantine_device": identity[0],
                        "quarantine_inode": identity[1],
                    },
                    correlation_id=None,
                    created_at=now,
                )
            )
        quarantine = data_dir / ".purge-quarantine" / operation_id
        quarantine.parent.mkdir()
        project_dir.rename(quarantine)
    finally:
        runtime.close()

    reopened = LiveClipRuntime.open(settings, project_root=project_root)
    try:
        assert not quarantine.exists()
        assert (project_dir.stat().st_dev, project_dir.stat().st_ino) == identity
        assert evidence.read_bytes() == b"must be restored"
        with reopened.engine.connect() as connection:
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(AuditEventRow)
                    .where(
                        AuditEventRow.action == "storage.project_purge_recovered",
                        AuditEventRow.target_id == project_id,
                    )
                )
                == 1
            )
    finally:
        reopened.close()


def test_admin_purge_api_requires_csrf_and_exact_preview_confirmation(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    data_dir = tmp_path / "projects"
    settings = Settings(
        data_dir=data_dir,
        allowed_media_roots_raw=str(tmp_path),
        ai_provider="mock",
        bootstrap_admin_password="administrator password 2026",
        _env_file=None,
    )
    runtime = LiveClipRuntime.open(settings, project_root=project_root)
    project_id = "7" * 32
    now = datetime(2026, 8, 15, tzinfo=UTC)
    try:
        with runtime.engine.begin() as connection:
            admin_id = connection.scalar(
                select(WorkspaceUserRow.id).where(WorkspaceUserRow.username == "local-admin")
            )
            assert admin_id is not None
            connection.execute(
                insert(ProjectRow).values(
                    id=project_id,
                    name="API 清除测试",
                    owner_id=admin_id,
                    visibility="private",
                    lifecycle=ProjectLifecycle.ARCHIVED.value,
                    lifecycle_before_archive=ProjectLifecycle.DRAFT.value,
                    management_version=1,
                    priority="normal",
                    archived_at=now,
                    source_request_path=str(tmp_path / "external-source.ts"),
                    current_generation=0,
                    current_pipeline_run_id=None,
                    revision_epoch=0,
                    created_at=now,
                    updated_at=now,
                )
            )
        app = create_app(settings, runtime=runtime, project_root=project_root)
        with TestClient(app, raise_server_exceptions=False) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "local-admin",
                    "password": "administrator password 2026",
                },
            )
            assert login.status_code == 200
            csrf = login.json()["csrf_token"]
            plan_response = client.get(f"/api/v1/admin/storage/projects/{project_id}/purge-plan")
            assert plan_response.status_code == 200
            plan = plan_response.json()
            assert "directory_device" not in plan
            assert "directory_inode" not in plan
            assert "directory_tree_fingerprint" not in plan
            body = {
                "snapshot_fingerprint": plan["snapshot_fingerprint"],
                "project_name": plan["project_name"],
                "administrator_username": "local-admin",
                "confirmation_phrase": plan["confirmation_phrase"],
            }
            missing_csrf = client.post(
                f"/api/v1/admin/storage/projects/{project_id}/purge",
                json=body,
            )
            assert missing_csrf.status_code == 401
            stale = client.post(
                f"/api/v1/admin/storage/projects/{project_id}/purge",
                headers={"X-CSRF-Token": csrf},
                json={**body, "snapshot_fingerprint": "0" * 64},
            )
            assert stale.status_code == 409
            purged = client.post(
                f"/api/v1/admin/storage/projects/{project_id}/purge",
                headers={"X-CSRF-Token": csrf},
                json=body,
            )
            assert purged.status_code == 200
            assert purged.json()["source_media_preserved"] is True
            assert client.get(f"/api/v1/projects/{project_id}").status_code == 404
    finally:
        runtime.close()
