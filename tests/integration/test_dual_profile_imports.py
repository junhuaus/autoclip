"""Stage 19a: import of finished dual-profile runs (synthetic fixtures only)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from liveclip.application.dual_profile_imports import (
    DUAL_PROFILE_SUBTITLE_ASSET_KIND,
    DUAL_PROFILE_VIDEO_ASSET_KIND,
    DualProfileImportError,
    DualProfileImportService,
    default_dual_profile_import_root,
)
from liveclip.application.media_assets import MediaAssetService
from liveclip.bootstrap import upgrade_database
from liveclip.db.dual_profile_repository import (
    DualProfileClipNotFound,
    SqlAlchemyDualProfileImportRepository,
)
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.media_repository import SqlAlchemyMediaAssetRepository
from liveclip.db.models import (
    AssetRow,
    AuditEventRow,
    CustomerDeliveryClipRow,
    CustomerDeliveryRow,
    DualProfileClipDecisionRow,
    DualProfileImportClipRow,
    DualProfileImportRow,
    ProjectMemberRow,
    ProjectRow,
    WorkspaceUserRow,
)
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.customer_delivery import (
    ClipDecisionAction,
    CustomerDeliveryRuleError,
    CustomerText,
    ImportedClipStatus,
)
from tests.dual_profile_fixtures import V9, RunFixture, _sha, build_run

pytestmark = pytest.mark.integration
PROJECT_ROOT = Path(__file__).resolve().parents[2]
USER_ID = "a" * 32
OTHER_USER_ID = "b" * 32
FIXED_NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def migrated_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("template").resolve() / "liveclip.sqlite3"
    engine = create_sqlite_engine(path)
    try:
        upgrade_database(engine, project_root=PROJECT_ROOT)
        with engine.begin() as connection:
            for user_id, username in ((USER_ID, "importer"), (OTHER_USER_ID, "other")):
                connection.execute(
                    insert(WorkspaceUserRow).values(
                        id=user_id,
                        username=username,
                        display_name=username,
                        system_role="member",
                        is_active=True,
                        created_at=FIXED_NOW,
                        updated_at=FIXED_NOW,
                    )
                )
    finally:
        engine.dispose(close=True)
    return path


@dataclass
class Harness:
    base: Path
    data_dir: Path
    engine: Engine
    repository: SqlAlchemyDualProfileImportRepository
    service: DualProfileImportService


@pytest.fixture
def harness(tmp_path: Path, migrated_template: Path) -> Iterator[Harness]:
    base = tmp_path.resolve()
    data_dir = base / "data" / "projects"
    data_dir.mkdir(parents=True)
    database = data_dir / "liveclip.sqlite3"
    shutil.copyfile(migrated_template, database)
    engine = create_sqlite_engine(database)
    repository = SqlAlchemyDualProfileImportRepository(engine)
    (base / "evaluations").mkdir()
    service = DualProfileImportService(
        repository,
        data_dir=data_dir,
        allowed_run_roots=(base / "evaluations",),
        allowed_transcript_roots=(base / "evaluations",),
        relative_path_base=base,
        now=lambda: FIXED_NOW,
    )
    try:
        yield Harness(base, data_dir, engine, repository, service)
    finally:
        engine.dispose(close=True)


def _import(harness: Harness, fixture: RunFixture, **kwargs: Any) -> Any:
    return harness.service.import_run(
        acting_user_id=kwargs.pop("acting_user_id", USER_ID),
        run_dir=kwargs.pop("run_dir", fixture.run_dir),
        transcript_path=kwargs.pop("transcript_path", fixture.transcript),
        **kwargs,
    )


def _project_dirs(harness: Harness) -> list[Path]:
    return [path for path in harness.data_dir.iterdir() if path.is_dir()]


def test_import_records_project_clips_assets_and_copies(harness: Harness) -> None:
    fixture = build_run(harness.base, include_blocked=True)

    result = _import(harness, fixture)

    assert result.created is True and result.clip_count == 2
    with harness.engine.connect() as connection:
        project = connection.execute(
            select(ProjectRow).where(ProjectRow.id == result.project_id)
        ).one()
        assert project.lifecycle == "editorial_review"
        assert project.source_request_path == (
            f"dual-profile-import:{result.snapshot_fingerprint[:20]}"
        )
        assert project.owner_id == USER_ID
        assert project.current_pipeline_run_id is None
        assert project.name == "直播源 双轨结果"
        member = connection.execute(
            select(ProjectMemberRow.role).where(ProjectMemberRow.project_id == result.project_id)
        ).scalar_one()
        assert member == "owner"
        imported = connection.execute(select(DualProfileImportRow)).one()
        assert imported.routing_policy_version == V9
        assert imported.algorithm_version == "dual-profile-direct-v1"
        assert imported.prompt_hashes_json == {"short_highlight.discovery": "d" * 64}
        assert imported.source_hash == _sha(fixture.transcript.read_bytes())
        assert imported.final_result_sha256 == _sha(fixture.final.read_bytes())
        assert imported.source_filename == "直播源.ts"
        clips = connection.execute(
            select(DualProfileImportClipRow).order_by(DualProfileImportClipRow.candidate_id)
        ).all()
        assert [(row.candidate_id, row.routed_status) for row in clips] == [
            ("lesson-one", "manual_review"),
            ("short-one", "selected"),
        ]
        assets = connection.execute(
            select(AssetRow).where(AssetRow.project_id == result.project_id)
        ).all()
        audit = connection.execute(
            select(AuditEventRow.action, AuditEventRow.after_json).where(
                AuditEventRow.project_id == result.project_id
            )
        ).one()
    assert {asset.kind for asset in assets} == {
        DUAL_PROFILE_VIDEO_ASSET_KIND,
        DUAL_PROFILE_SUBTITLE_ASSET_KIND,
    }
    assert all(asset.status == "committed" for asset in assets)
    project_dir = harness.data_dir / result.project_id
    for asset in assets:
        assert asset.relative_path.startswith(f"imports/{result.import_id}/")
        copied = project_dir / asset.relative_path
        assert copied.is_file() and _sha(copied.read_bytes()) == asset.sha256
    assert audit.action == "dual_profile.imported"
    serialized_audit = json.dumps(audit.after_json)
    assert str(harness.base) not in serialized_audit
    assert "evaluations" not in serialized_audit

    media = MediaAssetService(
        SqlAlchemyMediaAssetRepository(harness.engine), data_dir=harness.data_dir
    )
    for asset in assets:
        resolved = media.resolve(asset.id)
        assert resolved.sha256 == asset.sha256

    states = harness.repository.list_clip_states(project_id=result.project_id)
    assert [state.profile for state in states] == [
        ClipProfile.SHORT_HIGHLIGHT,
        ClipProfile.MINI_LESSON,
    ]
    short, lesson = states
    assert short.routed_status is ImportedClipStatus.SELECTED and short.deliverable
    assert lesson.routed_status is ImportedClipStatus.MANUAL_REVIEW and not lesson.deliverable


def test_import_accepts_absolute_render_paths(harness: Harness) -> None:
    fixture = build_run(harness.base, relative_paths=False)
    assert _import(harness, fixture).created is True


def test_reimport_is_idempotent_per_user_and_snapshot(harness: Harness) -> None:
    fixture = build_run(harness.base)
    first = _import(harness, fixture)
    second = _import(harness, fixture)

    assert second.created is False
    assert (second.project_id, second.import_id) == (first.project_id, first.import_id)
    assert _project_dirs(harness) == [harness.data_dir / first.project_id]
    with harness.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(DualProfileImportRow)) == 1
        assert connection.scalar(select(func.count()).select_from(ProjectRow)) == 1

    other = _import(harness, fixture, acting_user_id=OTHER_USER_ID)
    assert other.created is True and other.project_id != first.project_id


def test_concurrent_duplicate_import_resolves_to_the_winner(harness: Harness) -> None:
    fixture = build_run(harness.base)
    winner = _import(harness, fixture)

    class _StaleFirstLookup:
        def __init__(self, inner: SqlAlchemyDualProfileImportRepository) -> None:
            self._inner = inner
            self._calls = 0

        def find_import(self, **kwargs: Any) -> Any:
            self._calls += 1
            return None if self._calls == 1 else self._inner.find_import(**kwargs)

        def insert_import(self, record: Any) -> Any:
            return self._inner.insert_import(record)

    racing = DualProfileImportService(
        _StaleFirstLookup(harness.repository),
        data_dir=harness.data_dir,
        allowed_run_roots=(harness.base / "evaluations",),
        allowed_transcript_roots=(harness.base / "evaluations",),
        relative_path_base=harness.base,
        now=lambda: FIXED_NOW,
    )
    loser = racing.import_run(
        acting_user_id=USER_ID,
        run_dir=fixture.run_dir,
        transcript_path=fixture.transcript,
    )

    assert loser.created is False
    assert (loser.project_id, loser.import_id) == (winner.project_id, winner.import_id)
    assert _project_dirs(harness) == [harness.data_dir / winner.project_id]
    with harness.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ProjectRow)) == 1
        assert connection.scalar(select(func.count()).select_from(AssetRow)) == 4


def test_relative_run_and_transcript_paths_resolve_against_the_base(harness: Harness) -> None:
    fixture = build_run(harness.base)
    result = _import(
        harness,
        fixture,
        run_dir=fixture.run_dir.relative_to(harness.base),
        transcript_path=fixture.transcript.relative_to(harness.base),
    )
    assert result.created is True


def _tamper_file_hash(fixture: RunFixture) -> None:
    video = fixture.run_dir / "renders" / "short_highlight" / "short-one.mp4"
    video.write_bytes(b"tampered video bytes")


def _tamper_routing_v8(fixture: RunFixture) -> None:
    payload = json.loads(fixture.final.read_text(encoding="utf-8"))
    payload["routing_policy_version"] = "quality-gate-risk-routing-v8"
    fixture.final.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _tamper_routing_missing(fixture: RunFixture) -> None:
    payload = json.loads(fixture.final.read_text(encoding="utf-8"))
    payload.pop("routing_policy_version")
    fixture.final.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _tamper_algorithm(fixture: RunFixture) -> None:
    manifest = fixture.manifest()
    manifest["algorithm_version"] = "dual-profile-direct-v2"
    fixture.write_manifest(manifest)


def _tamper_source_hash(fixture: RunFixture) -> None:
    with fixture.transcript.open("a", encoding="utf-8") as handle:
        handle.write("\n4\n00:05:00,000 --> 00:05:01,000\n追加\n")


def _tamper_candidate_not_in_final(fixture: RunFixture) -> None:
    manifest = fixture.manifest()
    manifest["clips"][0]["candidate_id"] = "short-unknown"
    manifest["candidate_filter"] = ["lesson-one", "short-unknown"]
    fixture.write_manifest(manifest)


def _tamper_blocked_candidate(fixture: RunFixture) -> None:
    manifest = fixture.manifest()
    manifest["clips"][0]["candidate_id"] = "short-blocked"
    manifest["clips"][0]["start_ms"] = 240_000
    manifest["clips"][0]["end_ms"] = 290_000
    manifest["clips"][0]["duration_ms"] = 50_000
    manifest["candidate_filter"] = ["lesson-one", "short-blocked"]
    fixture.write_manifest(manifest)


def _tamper_symlink_escape(fixture: RunFixture) -> None:
    outside = fixture.base / "outside.mp4"
    video = fixture.run_dir / "renders" / "short_highlight" / "short-one.mp4"
    outside.write_bytes(video.read_bytes())
    video.unlink()
    video.symlink_to(outside)


def _tamper_relative_path_outside_render_root(fixture: RunFixture) -> None:
    outside = fixture.base / "elsewhere"
    outside.mkdir()
    video = fixture.run_dir / "renders" / "short_highlight" / "short-one.mp4"
    shutil.copyfile(video, outside / "short-one.mp4")
    manifest = fixture.manifest()
    manifest["clips"][0]["video_path"] = "elsewhere/short-one.mp4"
    fixture.write_manifest(manifest)


def _tamper_absolute_path_outside_render_root(fixture: RunFixture) -> None:
    outside = fixture.root / "other-run"
    outside.mkdir()
    video = fixture.run_dir / "renders" / "short_highlight" / "short-one.mp4"
    copied = outside / "short-one.mp4"
    shutil.copyfile(video, copied)
    manifest = fixture.manifest()
    manifest["clips"][0]["video_path"] = str(copied)
    fixture.write_manifest(manifest)


def _tamper_relative_dotdot(fixture: RunFixture) -> None:
    manifest = fixture.manifest()
    manifest["clips"][0]["video_path"] = "../outside/short-one.mp4"
    fixture.write_manifest(manifest)


def _tamper_quality_not_passed(fixture: RunFixture) -> None:
    quality = (
        fixture.run_dir
        / "renders"
        / "short_highlight"
        / "short-one-quality"
        / "quality-report.json"
    )
    payload = json.loads(quality.read_text(encoding="utf-8"))
    payload["automatic_status"] = "needs_review"
    quality.write_text(json.dumps(payload), encoding="utf-8")


def _tamper_renders_symlink(fixture: RunFixture) -> None:
    renders = fixture.run_dir / "renders"
    moved = fixture.base / "moved-renders"
    renders.rename(moved)
    renders.symlink_to(moved, target_is_directory=True)


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        (_tamper_file_hash, "differs from its manifest hash"),
        (_tamper_routing_v8, "routing policy"),
        (_tamper_routing_missing, "routing policy"),
        (_tamper_algorithm, "evidence is invalid"),
        (_tamper_source_hash, "transcript hash differs"),
        (_tamper_candidate_not_in_final, "not selected/manual final evidence"),
        (_tamper_blocked_candidate, "not selected/manual final evidence"),
        (_tamper_symlink_escape, "escapes the render directory"),
        (_tamper_relative_path_outside_render_root, "escapes the render directory"),
        (_tamper_absolute_path_outside_render_root, "escapes the render directory"),
        (_tamper_relative_dotdot, "not an absolute system path"),
        (_tamper_quality_not_passed, "automatically validated"),
        (_tamper_renders_symlink, "symbolic link"),
    ],
)
def test_tampered_runs_are_rejected_without_side_effects(
    harness: Harness,
    tamper: Any,
    message: str,
) -> None:
    fixture = build_run(harness.base)
    tamper(fixture)

    with pytest.raises(DualProfileImportError, match=message):
        _import(harness, fixture)

    assert _project_dirs(harness) == []
    with harness.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ProjectRow)) == 0
        assert connection.scalar(select(func.count()).select_from(AssetRow)) == 0


def test_run_dir_outside_allowed_root_is_rejected(harness: Harness) -> None:
    fixture = build_run(harness.base)
    outside_run = harness.base / "not-allowed" / "run-1"
    shutil.copytree(fixture.run_dir, outside_run)

    with pytest.raises(DualProfileImportError, match="outside the allowed import roots"):
        _import(harness, fixture, run_dir=Path("not-allowed/run-1"))
    with pytest.raises(DualProfileImportError, match="outside the allowed import roots"):
        _import(harness, fixture, run_dir=outside_run)
    with pytest.raises(DualProfileImportError, match=r"must not contain '\.\.'"):
        _import(harness, fixture, run_dir=Path("evaluations/../not-allowed/run-1"))


def test_symlinked_run_dir_escaping_the_root_is_rejected(harness: Harness) -> None:
    fixture = build_run(harness.base)
    outside_run = harness.base / "not-allowed" / "run-1"
    shutil.copytree(fixture.run_dir, outside_run)
    link = fixture.root / "linked-run"
    link.symlink_to(outside_run, target_is_directory=True)

    with pytest.raises(DualProfileImportError, match="outside the allowed import roots"):
        _import(harness, fixture, run_dir=link)


def test_the_managed_data_dir_is_never_an_import_source(harness: Harness) -> None:
    fixture = build_run(harness.base)
    smuggled_run = harness.data_dir / "smuggled-run"
    shutil.copytree(fixture.run_dir, smuggled_run)
    smuggled_transcript = harness.data_dir / "smuggled.srt"
    shutil.copyfile(fixture.transcript, smuggled_transcript)
    permissive = DualProfileImportService(
        harness.repository,
        data_dir=harness.data_dir,
        allowed_run_roots=(harness.base,),
        allowed_transcript_roots=(harness.base,),
        relative_path_base=harness.base,
        now=lambda: FIXED_NOW,
    )

    with pytest.raises(DualProfileImportError, match="run path is outside"):
        permissive.import_run(
            acting_user_id=USER_ID, run_dir=smuggled_run, transcript_path=fixture.transcript
        )
    with pytest.raises(DualProfileImportError, match="transcript path is outside"):
        permissive.import_run(
            acting_user_id=USER_ID, run_dir=fixture.run_dir, transcript_path=smuggled_transcript
        )
    assert permissive.import_run(
        acting_user_id=USER_ID, run_dir=fixture.run_dir, transcript_path=fixture.transcript
    ).created


def test_paths_outside_the_roots_do_not_reveal_existence(harness: Harness) -> None:
    fixture = build_run(harness.base)
    existing = harness.base / "not-allowed"
    existing.mkdir()
    messages = []
    for run_dir in (existing, harness.base / "missing-outside", Path("/definitely/missing")):
        with pytest.raises(DualProfileImportError) as caught:
            _import(harness, fixture, run_dir=run_dir)
        messages.append(str(caught.value))
    assert messages == ["run path is outside the allowed import roots"] * 3
    with pytest.raises(DualProfileImportError, match="run path does not exist"):
        _import(harness, fixture, run_dir=fixture.root / "missing-inside")


def test_transcript_outside_allowed_roots_is_rejected(harness: Harness) -> None:
    fixture = build_run(harness.base)
    outside = harness.base / "transcript.srt"
    shutil.copyfile(fixture.transcript, outside)

    with pytest.raises(DualProfileImportError, match="transcript path is outside"):
        _import(harness, fixture, transcript_path=outside)


def test_inactive_user_cannot_import_and_leaves_no_files(harness: Harness) -> None:
    fixture = build_run(harness.base)
    with harness.engine.begin() as connection:
        connection.execute(
            update(WorkspaceUserRow)
            .where(WorkspaceUserRow.id == USER_ID)
            .values(is_active=False, updated_at=FIXED_NOW)
        )

    with pytest.raises(DualProfileImportError, match="inactive"):
        _import(harness, fixture)
    assert _project_dirs(harness) == []


def test_decisions_are_append_only_sequenced_and_drive_eligibility(harness: Harness) -> None:
    result = _import(harness, build_run(harness.base))
    lesson = next(
        state
        for state in harness.repository.list_clip_states(project_id=result.project_id)
        if state.profile is ClipProfile.MINI_LESSON
    )

    first = harness.repository.append_decision(
        project_id=result.project_id,
        import_clip_id=lesson.import_clip_id,
        acting_user_id=USER_ID,
        action=ClipDecisionAction.APPROVE,
        title_override="审核后的小课标题",
        now=FIXED_NOW,
    )
    second = harness.repository.append_decision(
        project_id=result.project_id,
        import_clip_id=lesson.import_clip_id,
        acting_user_id=USER_ID,
        action=ClipDecisionAction.SELECT,
        now=FIXED_NOW,
    )
    assert (first.sequence, second.sequence) == (1, 2)

    state = next(
        value
        for value in harness.repository.list_clip_states(project_id=result.project_id)
        if value.import_clip_id == lesson.import_clip_id
    )
    assert state.deliverable and state.selected_for_delivery
    assert state.effective_text == CustomerText(
        title="审核后的小课标题", hook="小课教学高光语句", summary="小课教学内容摘要"
    )
    assert state.original_text.title == "小课教学"

    harness.repository.append_decision(
        project_id=result.project_id,
        import_clip_id=lesson.import_clip_id,
        acting_user_id=USER_ID,
        action=ClipDecisionAction.REJECT,
        now=FIXED_NOW,
    )
    state = next(
        value
        for value in harness.repository.list_clip_states(project_id=result.project_id)
        if value.import_clip_id == lesson.import_clip_id
    )
    assert not state.deliverable and not state.selected_for_delivery

    with pytest.raises(CustomerDeliveryRuleError):
        harness.repository.append_decision(
            project_id=result.project_id,
            import_clip_id=lesson.import_clip_id,
            acting_user_id=USER_ID,
            action=ClipDecisionAction.REJECT,
            hook_override="拒绝时不能改写",
            now=FIXED_NOW,
        )
    with pytest.raises(DualProfileClipNotFound):
        harness.repository.append_decision(
            project_id="f" * 32,
            import_clip_id=lesson.import_clip_id,
            acting_user_id=USER_ID,
            action=ClipDecisionAction.APPROVE,
            now=FIXED_NOW,
        )
    with harness.engine.connect() as connection:
        actions = connection.execute(
            select(AuditEventRow.action)
            .where(AuditEventRow.project_id == result.project_id)
            .order_by(AuditEventRow.created_at, AuditEventRow.action)
        ).scalars()
        assert sorted(actions) == [
            "dual_profile.clip_approve",
            "dual_profile.clip_reject",
            "dual_profile.clip_select",
            "dual_profile.imported",
        ]


@pytest.mark.parametrize(
    ("row", "values"),
    [
        (DualProfileImportRow, {"clip_count": 99}),
        (DualProfileImportClipRow, {"title": "篡改的模型原标题"}),
        (DualProfileClipDecisionRow, {"action": "reject"}),
    ],
)
def test_imported_rows_are_immutable_in_sqlite(
    harness: Harness,
    row: Any,
    values: dict[str, object],
) -> None:
    result = _import(harness, build_run(harness.base))
    clip_id = harness.repository.list_clip_states(project_id=result.project_id)[0].import_clip_id
    harness.repository.append_decision(
        project_id=result.project_id,
        import_clip_id=clip_id,
        acting_user_id=USER_ID,
        action=ClipDecisionAction.APPROVE,
        now=FIXED_NOW,
    )

    with (
        pytest.raises((IntegrityError, OperationalError), match="immutable"),
        harness.engine.begin() as connection,
    ):
        connection.execute(update(row).values(**values))


@pytest.mark.parametrize(
    "row",
    [DualProfileImportRow, DualProfileImportClipRow, DualProfileClipDecisionRow],
)
def test_immutable_rows_cannot_be_deleted_while_their_project_exists(
    harness: Harness,
    row: Any,
) -> None:
    result = _import(harness, build_run(harness.base))
    clip_id = harness.repository.list_clip_states(project_id=result.project_id)[0].import_clip_id
    harness.repository.append_decision(
        project_id=result.project_id,
        import_clip_id=clip_id,
        acting_user_id=USER_ID,
        action=ClipDecisionAction.APPROVE,
        now=FIXED_NOW,
    )

    with (
        pytest.raises((IntegrityError, OperationalError), match="deleted only with their project"),
        harness.engine.begin() as connection,
    ):
        connection.execute(delete(row))
    with harness.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(row)) >= 1


def test_customer_delivery_clips_cannot_be_deleted_directly(harness: Harness) -> None:
    result = _import(harness, build_run(harness.base))
    state = harness.repository.list_clip_states(project_id=result.project_id)[0]
    with harness.engine.begin() as connection:
        connection.execute(
            insert(CustomerDeliveryRow).values(
                id="d" * 32,
                project_id=result.project_id,
                import_id=result.import_id,
                version=1,
                title="交付",
                status="succeeded",
                snapshot_fingerprint="e" * 64,
                created_by=USER_ID,
                created_at=FIXED_NOW,
            )
        )
        connection.execute(
            insert(CustomerDeliveryClipRow).values(
                id="c" * 32,
                delivery_id="d" * 32,
                import_clip_id=state.import_clip_id,
                ordinal=1,
                profile=state.profile.value,
                title="标题",
                hook="钩子",
                summary="摘要",
                duration_ms=state.duration_ms,
                video_asset_id=state.video_asset_id,
                subtitle_asset_id=state.subtitle_asset_id,
                video_sha256="1" * 64,
                subtitle_sha256="2" * 64,
            )
        )
    for statement in (
        delete(CustomerDeliveryClipRow),
        delete(CustomerDeliveryRow),
    ):
        with (
            pytest.raises((IntegrityError, OperationalError), match="deleted only"),
            harness.engine.begin() as connection,
        ):
            connection.execute(statement)

    with harness.engine.begin() as connection:
        connection.execute(delete(ProjectRow).where(ProjectRow.id == result.project_id))
    with harness.engine.connect() as connection:
        for table in (CustomerDeliveryRow, CustomerDeliveryClipRow, DualProfileImportRow):
            assert connection.scalar(select(func.count()).select_from(table)) == 0


def test_decision_override_columns_are_constrained_to_approvals(harness: Harness) -> None:
    result = _import(harness, build_run(harness.base))
    clip_id = harness.repository.list_clip_states(project_id=result.project_id)[0].import_clip_id

    with pytest.raises(IntegrityError), harness.engine.begin() as connection:
        connection.execute(
            insert(DualProfileClipDecisionRow).values(
                id="c" * 32,
                import_clip_id=clip_id,
                project_id=result.project_id,
                sequence=1,
                action="select",
                title_override="绕过领域规则",
                actor_user_id=USER_ID,
                decided_at=FIXED_NOW,
            )
        )


def test_project_deletion_cascades_through_import_rows(harness: Harness) -> None:
    result = _import(harness, build_run(harness.base))
    clip_id = harness.repository.list_clip_states(project_id=result.project_id)[0].import_clip_id
    harness.repository.append_decision(
        project_id=result.project_id,
        import_clip_id=clip_id,
        acting_user_id=USER_ID,
        action=ClipDecisionAction.APPROVE,
        now=FIXED_NOW,
    )

    with harness.engine.begin() as connection:
        connection.execute(delete(ProjectRow).where(ProjectRow.id == result.project_id))
    with harness.engine.connect() as connection:
        for table in (
            DualProfileImportRow,
            DualProfileImportClipRow,
            DualProfileClipDecisionRow,
            AssetRow,
        ):
            assert connection.scalar(select(func.count()).select_from(table)) == 0


def test_default_import_root_is_data_evaluations() -> None:
    assert default_dual_profile_import_root(Path("/repo")) == Path("/repo/data/evaluations")
