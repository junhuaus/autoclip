from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from PIL import Image

import liveclip.delivery.release_package as release_package_module
from liveclip.application.assets import AssetReservation
from liveclip.application.pipeline import LeaseIdentity
from liveclip.application.releases import ReleasePackageWork
from liveclip.delivery.edit_package import EditPackageTransientError
from liveclip.delivery.release_package import (
    ReleasePackageError,
    ReleasePackageTransientError,
    create_release_package,
    validate_existing_release_package,
)
from liveclip.delivery.release_package_task_handler import ReleasePackageTaskHandler
from liveclip.domain.edit_plan import CaptionCue
from liveclip.domain.releases import (
    ReleaseCaptionMode,
    ReleaseChecklist,
    ReleasePlatform,
    ReleasePreflight,
    ReleasePreflightCheck,
    get_platform_preset,
)
from liveclip.domain.state_transitions import AssetStatus
from liveclip.media.fingerprint import stream_sha256

pytestmark = pytest.mark.integration


def _create_portrait_video(path: Path, *, frequency: int = 660) -> None:
    executable = shutil.which("ffmpeg")
    if executable is None:
        pytest.skip("ffmpeg is required for release package integration")
    result = subprocess.run(
        [
            executable,
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=540x960:rate=12:duration=3",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate=48000:duration=3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def _work(video: Path) -> ReleasePackageWork:
    checklist = ReleaseChecklist.model_validate(
        {name: True for name in ReleaseChecklist.model_fields}
    )
    preflight = ReleasePreflight(
        preset_id=get_platform_preset(ReleasePlatform.GENERIC_VERTICAL).preset_id,
        checked_at=date(2026, 8, 15),
        passed=True,
        blocker_count=0,
        warning_count=0,
        checks=(
            ReleasePreflightCheck(
                code="test_passed",
                category="media",
                outcome="passed",
                message="测试预检通过。",
            ),
        ),
    )
    return ReleasePackageWork(
        release_package_id="release_package_1",
        release_item_id="release_item_1",
        task_id="task_1",
        project_id="project_1",
        project_name="直播发布项目",
        requested_by_user_id="editor_1",
        requested_by_username="editor",
        run_id="run_1",
        generation=1,
        revision_epoch=2,
        release_item_version=4,
        version=1,
        preset=get_platform_preset(ReleasePlatform.GENERIC_VERTICAL),
        caption_mode=ReleaseCaptionMode.CLEAN_SEPARATE,
        include_zip=True,
        snapshot_fingerprint="a" * 64,
        package_fingerprint="b" * 64,
        snapshot={"schema_version": "liveclip.release-package-snapshot.v1"},
        created_at=datetime(2026, 8, 15, 10, tzinfo=UTC),
        source_filename="直播源.ts",
        source_fingerprint="c" * 64,
        source_render_job_id="render_1",
        source_video_asset_id="asset_1",
        source_video_relative_path="renders/review.mp4",
        source_video_sha256=stream_sha256(video),
        source_video_size_bytes=video.stat().st_size,
        clip_id="clip_1",
        edit_plan_revision=3,
        source_start_ms=20_000,
        source_end_ms=23_000,
        score=92.5,
        high_impact_sentence="这是一句适合放到屏幕上的高光语句。",
        risk_flags=("事实复核",),
        account_label="主账号",
        planned_publish_at=datetime(2026, 8, 16, 12, tzinfo=UTC),
        title="直播高光发布",
        description="这是一段可编辑的发布正文。",
        title_variants=("直播高光备选",),
        hashtags=("直播", "高光"),
        cta="欢迎关注",
        cover_time_ms=1_000,
        captions=(
            CaptionCue(start_ms=0, end_ms=1_400, text="第一句字幕"),
            CaptionCue(start_ms=1_500, end_ms=2_800, text="第二句字幕"),
        ),
        preflight=preflight,
        checklist=checklist,
    )


def test_release_package_builds_real_media_cover_metadata_and_zip(tmp_path: Path) -> None:
    video = tmp_path / "portrait.mp4"
    _create_portrait_video(video)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    work = _work(video)

    result = create_release_package(
        project_dir=project_dir,
        work=work,
        video_path=video,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "liveclip.release-package.v1"
    assert manifest["platform"] == "generic_vertical"
    assert manifest["caption_mode"] == "clean_separate"
    assert manifest["media_validation"]["fast_start"] is True
    assert manifest["media_validation"]["duration_ms"] == 3_000
    assert manifest["package_preflight"]["passed"] is True
    assert manifest["subtitle_filename"].endswith(".srt")
    cover = result.directory / manifest["cover_filename"]
    with Image.open(cover) as image:
        assert image.height > image.width
    assert result.zip_path is not None
    with zipfile.ZipFile(result.zip_path) as archive:
        assert archive.testzip() is None
        assert "README-发布说明.txt" in archive.namelist()
        assert "metadata/release-copy.txt" in archive.namelist()
        assert manifest["video_filename"] in archive.namelist()
        assert manifest["subtitle_filename"] in archive.namelist()

    recovered = validate_existing_release_package(result.directory, work=work)
    assert recovered.manifest_sha256 == result.manifest_sha256
    assert recovered.zip_sha256 == result.zip_sha256


def test_permission_loss_after_publication_withdraws_new_release_package(
    tmp_path: Path,
) -> None:
    video = tmp_path / "portrait.mp4"
    _create_portrait_video(video)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    work = _work(video)
    calls = 0

    def revoke_after_publish() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("requester permission was revoked")

    with pytest.raises(PermissionError, match="permission was revoked"):
        create_release_package(
            project_dir=project_dir,
            work=work,
            video_path=video,
            publication_fence=revoke_after_publish,
        )

    item_dir = project_dir / "release-packages" / work.release_item_id
    assert calls == 2
    assert not (item_dir / "v001").exists()
    assert not tuple(item_dir.glob(".v001-attempt-*"))


class _NoCommitReleaseAssetStore:
    def __init__(self, *, fail_on_commit: int = 1) -> None:
        self.commits = 0
        self.invalidations = 0
        self.invalidated_asset_ids: tuple[str, ...] = ()
        self._fail_on_commit = fail_on_commit

    def reserve(
        self,
        _lease: LeaseIdentity,
        *,
        relative_path: str,
        **_kwargs: object,
    ) -> AssetReservation:
        return AssetReservation(
            asset_id=f"asset-{len(relative_path)}",
            status=AssetStatus.PENDING,
            relative_path=relative_path,
            sha256=None,
            size_bytes=None,
        )

    def commit(
        self,
        _lease: LeaseIdentity,
        reservation: AssetReservation,
        **kwargs: object,
    ) -> AssetReservation:
        self.commits += 1
        if self.commits == self._fail_on_commit:
            raise RuntimeError("simulated Asset commit failure")
        expected_sha256 = kwargs.get("expected_sha256")
        return AssetReservation(
            asset_id=reservation.asset_id,
            status=AssetStatus.COMMITTED,
            relative_path=reservation.relative_path,
            sha256=str(expected_sha256),
            size_bytes=1,
        )

    def invalidate_attempt_assets(
        self,
        _lease: LeaseIdentity,
        asset_ids: tuple[str, ...],
        **_kwargs: object,
    ) -> None:
        self.invalidations += 1
        self.invalidated_asset_ids = asset_ids

    def withdraw_attempt_publication(
        self,
        lease: LeaseIdentity,
        asset_ids: tuple[str, ...],
        *,
        project_dir: Path,
        relative_directory: str,
        **kwargs: object,
    ) -> bool:
        shutil.rmtree(project_dir / relative_directory)
        self.invalidate_attempt_assets(lease, asset_ids, **kwargs)
        return True


def _release_handler_work(
    tmp_path: Path,
) -> tuple[Path, Path, ReleasePackageWork, LeaseIdentity]:
    data_dir = tmp_path / "projects"
    project_id = "1" * 32
    project_dir = data_dir / project_id
    video = project_dir / "renders" / "review.mp4"
    video.parent.mkdir(parents=True)
    _create_portrait_video(video)
    work = replace(_work(video), project_id=project_id)
    lease = LeaseIdentity(task_id="task_1", worker_id="worker_1", lease_token="lease_1")
    return data_dir, project_dir, work, lease


def test_task_handler_third_fence_withdraws_published_release_package(
    tmp_path: Path,
) -> None:
    data_dir, project_dir, work, lease = _release_handler_work(tmp_path)
    calls = 0

    def revoke_at_handler_fence(
        _lease: LeaseIdentity,
        _work: ReleasePackageWork,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise PermissionError("requester permission was revoked")

    assets = _NoCommitReleaseAssetStore()
    handler = ReleasePackageTaskHandler(
        data_dir=data_dir,
        assets=assets,  # type: ignore[arg-type]
        publication_fence=revoke_at_handler_fence,
    )
    with pytest.raises(PermissionError, match="permission was revoked"):
        handler.execute(work, lease, cancel_requested=lambda: False)

    item_dir = project_dir / "release-packages" / work.release_item_id
    assert calls == 3
    assert assets.commits == 0
    assert assets.invalidations == 1
    assert not (item_dir / "v001").exists()
    assert not tuple(item_dir.glob(".v001-attempt-*"))


def test_second_asset_commit_failure_withdraws_release_package_and_both_reservations(
    tmp_path: Path,
) -> None:
    data_dir, project_dir, work, lease = _release_handler_work(tmp_path)
    assets = _NoCommitReleaseAssetStore(fail_on_commit=2)
    handler = ReleasePackageTaskHandler(
        data_dir=data_dir,
        assets=assets,  # type: ignore[arg-type]
        publication_fence=lambda _lease, _work: None,
    )

    with pytest.raises(RuntimeError, match="Asset commit failure"):
        handler.execute(work, lease, cancel_requested=lambda: False)

    item_dir = project_dir / "release-packages" / work.release_item_id
    assert assets.commits == 2
    assert assets.invalidations == 1
    assert len(assets.invalidated_asset_ids) == 2
    assert not (item_dir / "v001").exists()
    assert not tuple(item_dir.glob(".v001-attempt-*"))


def test_adopted_corrupt_release_package_is_withdrawn_and_next_retry_rebuilds(
    tmp_path: Path,
) -> None:
    data_dir, project_dir, work, lease = _release_handler_work(tmp_path)
    destination = project_dir / "release-packages" / work.release_item_id / "v001"
    destination.mkdir(parents=True)
    (destination / "manifest.json").write_text("not-json", encoding="utf-8")
    assets = _NoCommitReleaseAssetStore(fail_on_commit=999)
    handler = ReleasePackageTaskHandler(
        data_dir=data_dir,
        assets=assets,  # type: ignore[arg-type]
        publication_fence=lambda _lease, _work: None,
    )

    with pytest.raises(ReleasePackageError, match="manifest is invalid"):
        handler.execute(work, lease, cancel_requested=lambda: False)

    assert assets.invalidations == 1
    assert not destination.exists()
    persistence = handler.execute(work, lease, cancel_requested=lambda: False)
    assert destination.is_dir()
    assert persistence.manifest_asset_id
    assert persistence.zip_asset_id
    assert assets.commits == 2


def test_actual_media_preflight_preserves_duplicate_content_warning(tmp_path: Path) -> None:
    video = tmp_path / "portrait.mp4"
    _create_portrait_video(video)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    work = _work(video)
    duplicate_warning = ReleasePreflightCheck(
        code="duplicate_content",
        category="editorial",
        outcome="warning",
        message="发现一个已导出内容可能重复。",
    )
    work = replace(
        work,
        preflight=work.preflight.model_copy(
            update={
                "checks": (*work.preflight.checks, duplicate_warning),
                "warning_count": 1,
            }
        ),
    )

    result = create_release_package(
        project_dir=project_dir,
        work=work,
        video_path=video,
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    duplicate = next(
        check
        for check in manifest["package_preflight"]["checks"]
        if check["code"] == "duplicate_content"
    )
    assert duplicate == duplicate_warning.model_dump(mode="json")
    assert manifest["package_preflight"]["warning_count"] >= 1


def test_release_package_recovery_rejects_changed_copy(tmp_path: Path) -> None:
    video = tmp_path / "portrait.mp4"
    _create_portrait_video(video)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    work = _work(video)
    result = create_release_package(
        project_dir=project_dir,
        work=work,
        video_path=video,
    )
    (result.directory / "metadata/release-copy.txt").write_text(
        "changed",
        encoding="utf-8",
    )

    with pytest.raises(ReleasePackageError, match="missing or unsafe"):
        validate_existing_release_package(result.directory, work=work)


def test_release_package_recovery_rejects_resigned_foreign_video(
    tmp_path: Path,
) -> None:
    video = tmp_path / "portrait.mp4"
    replacement = tmp_path / "replacement.mp4"
    _create_portrait_video(video)
    _create_portrait_video(replacement, frequency=880)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    work = _work(video)
    result = create_release_package(
        project_dir=project_dir,
        work=work,
        video_path=video,
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    video_member = str(manifest["video_filename"])
    packaged_video = result.directory / video_member
    packaged_video.unlink()
    shutil.copyfile(replacement, packaged_video)
    replacement_sha256 = stream_sha256(packaged_video)
    manifest["video_sha256"] = replacement_sha256
    manifest["media_validation"]["size_bytes"] = packaged_video.stat().st_size
    manifest["members"][video_member] = replacement_sha256
    manifest_payload = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    result.manifest_path.unlink()
    result.manifest_path.write_bytes(manifest_payload)
    hashes = {str(name): str(digest) for name, digest in manifest["members"].items()}
    hashes["manifest.json"] = stream_sha256(result.manifest_path)
    checksums = "".join(f"{hashes[name]}  {name}\n" for name in sorted(hashes)).encode("utf-8")
    checksums_path = result.directory / "checksums.sha256"
    checksums_path.unlink()
    checksums_path.write_bytes(checksums)
    assert result.zip_path is not None
    result.zip_path.unlink()
    with zipfile.ZipFile(result.zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member in sorted((*hashes, "checksums.sha256")):
            archive.write(result.directory / member, arcname=member)

    with pytest.raises(ReleasePackageError, match="video differs from its source"):
        validate_existing_release_package(result.directory, work=work)


def test_release_package_rechecks_actual_bytes_against_selected_preset(
    tmp_path: Path,
) -> None:
    video = tmp_path / "portrait.mp4"
    _create_portrait_video(video)
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    work = _work(video)
    stricter_preset = work.preset.model_copy(update={"minimum_width": 800, "minimum_height": 1_000})

    with pytest.raises(
        ReleasePackageError,
        match="does not satisfy the selected platform preset",
    ):
        create_release_package(
            project_dir=project_dir,
            work=replace(work, preset=stricter_preset),
            video_path=video,
        )


def test_release_package_preserves_transient_media_validation_for_worker_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    video = tmp_path / "portrait.mp4"
    video.write_bytes(b"temporary media bytes")
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    work = _work(video)

    def fail_validation(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise EditPackageTransientError("temporary decoder failure")

    monkeypatch.setattr(
        release_package_module,
        "validate_editor_video",
        fail_validation,
    )

    with pytest.raises(ReleasePackageTransientError, match="temporarily failed"):
        create_release_package(
            project_dir=project_dir,
            work=work,
            video_path=video,
        )
    assert not (project_dir / "release-packages" / work.release_item_id / "v001").exists()


@pytest.mark.parametrize(
    "failure",
    (
        OSError("temporary ffmpeg launch failure"),
        subprocess.TimeoutExpired(cmd="ffmpeg", timeout=60),
    ),
)
def test_cover_process_launch_and_timeout_remain_retryable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: BaseException,
) -> None:
    video = tmp_path / "portrait.mp4"
    video.write_bytes(b"not inspected")
    output = tmp_path / "cover.png"

    def fail_process(*_args: object, **_kwargs: object) -> object:
        raise failure

    monkeypatch.setattr(release_package_module, "run_cancellable_process", fail_process)

    with pytest.raises(ReleasePackageTransientError):
        release_package_module._extract_cover(
            video,
            output,
            timestamp_ms=0,
            cancel_requested=lambda: False,
        )
    assert not output.exists()
