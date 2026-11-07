"""Stage 19a: import of finished dual-profile runs (synthetic fixtures only)."""

from __future__ import annotations

import hashlib
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
from liveclip.domain.edit_plan import captions_to_srt
from liveclip.pipeline.dual_profile import (
    CandidateDisposition,
    DualProfileFinalResult,
    DualProfileRunManifest,
    FinalProfileCandidate,
    FinalProfileResult,
    ProfileManifestStats,
    profile_statistics,
)
from liveclip.pipeline.srt import load_srt_transcript
from liveclip.services.captions import captions_for_clip

pytestmark = pytest.mark.integration
PROJECT_ROOT = Path(__file__).resolve().parents[2]
USER_ID = "a" * 32
OTHER_USER_ID = "b" * 32
FIXED_NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
V9 = "quality-gate-risk-routing-v9"


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _candidate(
    *,
    candidate_id: str,
    profile: ClipProfile,
    start_ms: int,
    end_ms: int,
    cue_id: int,
    title: str,
    status: CandidateDisposition,
) -> FinalProfileCandidate:
    return FinalProfileCandidate(
        candidate_id=candidate_id,
        profile=profile,
        source_candidate_ids=(candidate_id,),
        source_window_ids=(f"{profile.value}_window",),
        start_cue_id=cue_id,
        end_cue_id=cue_id,
        start_ms=start_ms,
        end_ms=end_ms,
        duration_ms=end_ms - start_ms,
        title=title,
        hook=f"{title}高光语句",
        summary=f"{title}内容摘要",
        score=88,
        review_status=status,
        evidence_cue_ids=(cue_id,),
        review_reason=f"{title}内部审核理由",
    )


def _profile_result(
    candidate: FinalProfileCandidate, *extra: FinalProfileCandidate
) -> FinalProfileResult:
    values = (candidate, *extra)
    by_status: dict[str, list[FinalProfileCandidate]] = {}
    for value in values:
        by_status.setdefault(value.review_status.value, []).append(value)
    return FinalProfileResult(
        profile=candidate.profile,
        raw_candidate_ids=tuple(value.candidate_id for value in values),
        selected=tuple(by_status.get("selected", ())),
        manual_review=tuple(by_status.get("manual_review", ())),
        blocked=tuple(by_status.get("blocked", ())),
        statistics=profile_statistics(tuple(value.candidate_id for value in values), values),
    )


@dataclass
class RunFixture:
    base: Path
    root: Path
    run_dir: Path
    transcript: Path
    render_manifest: Path
    final: Path

    def manifest(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(self.render_manifest.read_text(encoding="utf-8"))
        return loaded

    def write_manifest(self, value: dict[str, Any]) -> None:
        self.render_manifest.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def build_run(
    base: Path,
    *,
    name: str = "run-1",
    routing: str | None = V9,
    relative_paths: bool = True,
    quality_status: str = "passed",
    include_blocked: bool = False,
) -> RunFixture:
    root = base / "evaluations"
    run_dir = root / name
    run_dir.mkdir(parents=True)
    transcript = root / f"{name}-transcript.srt"
    transcript.write_text(
        "1\n00:00:00,000 --> 00:00:45,000\n短片完整教学主题\n\n"
        "2\n00:01:40,000 --> 00:03:20,001\n长片完整教学主题\n\n"
        "3\n00:04:00,000 --> 00:04:50,000\n被拦截的片段\n",
        encoding="utf-8",
    )
    source_hash = _sha(transcript.read_bytes())
    short = _candidate(
        candidate_id="short-one",
        profile=ClipProfile.SHORT_HIGHLIGHT,
        start_ms=0,
        end_ms=45_000,
        cue_id=1,
        title="短片教学",
        status=CandidateDisposition.SELECTED,
    )
    lesson = _candidate(
        candidate_id="lesson-one",
        profile=ClipProfile.MINI_LESSON,
        start_ms=100_000,
        end_ms=200_001,
        cue_id=2,
        title="小课教学",
        status=CandidateDisposition.MANUAL_REVIEW,
    )
    blocked = _candidate(
        candidate_id="short-blocked",
        profile=ClipProfile.SHORT_HIGHLIGHT,
        start_ms=240_000,
        end_ms=290_000,
        cue_id=3,
        title="拦截片段",
        status=CandidateDisposition.BLOCKED,
    )
    short_extra = (blocked,) if include_blocked else ()
    final = DualProfileFinalResult(
        source_hash=source_hash,
        requested_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        executed_profiles=(ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON),
        profiles={
            ClipProfile.SHORT_HIGHLIGHT: _profile_result(short, *short_extra),
            ClipProfile.MINI_LESSON: _profile_result(lesson),
        },
        routing_policy_version=routing,  # type: ignore[arg-type]
    )
    final_path = run_dir / "final-validated.json"
    final_path.write_text(
        json.dumps(final.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8"
    )
    run_manifest = DualProfileRunManifest(
        source_hash=source_hash,
        requested_profiles=final.requested_profiles,
        executed_profiles=final.executed_profiles,
        profiles={
            profile: ProfileManifestStats(**value.statistics.model_dump())
            for profile, value in final.profiles.items()
        },
        provider="mock",
        model="mock-model",
        prompt_files={"discovery": ("prompt.md",)},
        prompt_hashes={"short_highlight.discovery": "d" * 64},
        calls={"discovery": 2, "global_review": 2},
        input_tokens=100,
        output_tokens=20,
        latency_ms=50,
        cache_hits=0,
        retry_count=0,
        repair_count=0,
    )
    (run_dir / "run-manifest.json").write_text(
        json.dumps(run_manifest.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8"
    )
    transcript_doc = load_srt_transcript(transcript)
    render_root = run_dir / "renders"
    render_root.mkdir()

    def recorded(path: Path) -> str:
        return str(path.relative_to(base)) if relative_paths else str(path)

    clips: list[dict[str, object]] = []
    for candidate in (short, lesson):
        profile_dir = render_root / candidate.profile.value
        quality_dir = profile_dir / f"{candidate.candidate_id}-quality"
        quality_dir.mkdir(parents=True)
        video = profile_dir / f"{candidate.candidate_id}.mp4"
        video.write_bytes(f"video-{candidate.candidate_id}".encode())
        video_sha = _sha(video.read_bytes())
        captions = captions_for_clip(
            transcript_doc.segments,
            source_start_ms=candidate.start_ms,
            source_end_ms=candidate.end_ms,
        )
        subtitle = profile_dir / f"{candidate.candidate_id}.srt"
        subtitle.write_text(captions_to_srt(captions), encoding="utf-8")
        contact = quality_dir / "contact-sheet.png"
        contact.write_bytes(f"png-{candidate.candidate_id}".encode())
        quality = quality_dir / "quality-report.json"
        quality.write_text(
            json.dumps(
                {
                    "media_sha256": video_sha,
                    "automatic_status": quality_status,
                    "full_decode": "passed",
                }
            ),
            encoding="utf-8",
        )
        clips.append(
            {
                "candidate_id": candidate.candidate_id,
                "profile": candidate.profile.value,
                "variant_group_id": candidate.variant_group_id,
                "review_status": candidate.review_status.value,
                "start_ms": candidate.start_ms,
                "end_ms": candidate.end_ms,
                "duration_ms": candidate.duration_ms,
                "video_path": recorded(video),
                "video_sha256": video_sha,
                "subtitle_path": recorded(subtitle),
                "subtitle_sha256": _sha(subtitle.read_bytes()),
                "quality_report_path": str(quality),
                "contact_sheet_path": str(contact),
                "contact_sheet_sha256": _sha(contact.read_bytes()),
                "encoder": "fixture",
                "render_attempts": 1,
            }
        )
    render_manifest = render_root / "render-manifest.json"
    fixture = RunFixture(
        base=base,
        root=root,
        run_dir=run_dir,
        transcript=transcript,
        render_manifest=render_manifest,
        final=final_path,
    )
    fixture.write_manifest(
        {
            "schema_version": "1",
            "algorithm_version": "dual-profile-direct-v1",
            "source_video": "直播源.ts",
            "profiles": ["short_highlight", "mini_lesson"],
            "candidate_filter": ["lesson-one", "short-one"],
            "clip_count": 2,
            "clips": clips,
        }
    )
    return fixture


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
