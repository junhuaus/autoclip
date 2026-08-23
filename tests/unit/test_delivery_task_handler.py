from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from liveclip.application.assets import AssetReservation
from liveclip.application.deliveries import DeliveryWork, DeliveryWorkClip
from liveclip.application.pipeline import LeaseIdentity
from liveclip.delivery.package import DeliveryError
from liveclip.delivery.task_handler import DeliveryTaskHandler
from liveclip.domain.state_transitions import AssetStatus
from liveclip.media.secure_files import capture_pinned_file_evidence


@dataclass
class RecordingAssetStore:
    existing_hashes: dict[str, str] = field(default_factory=dict)
    commits: list[tuple[str, str]] = field(default_factory=list)

    def reserve(
        self,
        lease: LeaseIdentity,
        *,
        project_id: str,
        kind: str,
        relative_path: str,
        mime_type: str,
        input_fingerprint: str,
        generation: int | None = None,
        candidate_id: str | None = None,
        edit_plan_revision: int | None = None,
        revision_epoch: int | None = None,
    ) -> AssetReservation:
        del (
            lease,
            project_id,
            mime_type,
            input_fingerprint,
            generation,
            candidate_id,
            edit_plan_revision,
            revision_epoch,
        )
        sha256 = self.existing_hashes.get(relative_path)
        return AssetReservation(
            asset_id=f"asset-{kind}",
            status=AssetStatus.COMMITTED if sha256 is not None else AssetStatus.PENDING,
            relative_path=relative_path,
            sha256=sha256,
            size_bytes=None,
        )

    def commit(
        self,
        lease: LeaseIdentity,
        reservation: AssetReservation,
        *,
        project_dir: Path,
        validation: dict[str, object],
        expected_sha256: str | None = None,
    ) -> AssetReservation:
        del lease, validation
        assert expected_sha256 is not None
        evidence = capture_pinned_file_evidence(
            project_dir / reservation.relative_path,
            expected_sha256=expected_sha256,
        )
        try:
            size_bytes = evidence.size_bytes
        finally:
            evidence.pinned.close()
        self.commits.append((reservation.relative_path, expected_sha256))
        self.existing_hashes[reservation.relative_path] = expected_sha256
        return AssetReservation(
            asset_id=reservation.asset_id,
            status=AssetStatus.COMMITTED,
            relative_path=reservation.relative_path,
            sha256=expected_sha256,
            size_bytes=size_bytes,
        )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _make_work(tmp_path: Path) -> tuple[Path, DeliveryWork, LeaseIdentity]:
    data_dir = tmp_path / "projects"
    project_id = "a" * 32
    project_dir = data_dir / project_id
    video_relative = "renders/final/clip-1/r001/final.mp4"
    subtitle_relative = "renders/final/clip-1/r001/final.srt"
    video = project_dir / video_relative
    subtitle = project_dir / subtitle_relative
    video.parent.mkdir(parents=True)
    video_payload = b"verified-final-video" * 100
    subtitle_payload = b"1\n00:00:00,000 --> 00:00:02,000\ncaption\n"
    video.write_bytes(video_payload)
    subtitle.write_bytes(subtitle_payload)
    work = DeliveryWork(
        delivery_id="delivery-1",
        task_id="b" * 32,
        project_id=project_id,
        run_id="c" * 32,
        generation=1,
        revision_epoch=1,
        version=1,
        include_zip=True,
        snapshot_fingerprint="d" * 64,
        package_fingerprint="e" * 64,
        created_at=datetime(2026, 8, 4, tzinfo=UTC),
        source_filename="source.mp4",
        source_fingerprint="f" * 64,
        clips=(
            DeliveryWorkClip(
                clip_id="clip_1",
                edit_plan_revision_id="revision-1",
                render_job_id="render-1",
                edit_plan_revision=1,
                title="稳定交付",
                source_start_ms=1_000,
                source_end_ms=31_000,
                score=90.0,
                video_relative_path=video_relative,
                video_sha256=_sha256(video_payload),
                subtitle_relative_path=subtitle_relative,
                subtitle_sha256=_sha256(subtitle_payload),
            ),
        ),
    )
    lease = LeaseIdentity(
        task_id=work.task_id,
        worker_id="worker",
        lease_token="1" * 64,
    )
    return data_dir, work, lease


def test_task_handler_commits_exact_new_manifest_and_zip_hashes(tmp_path: Path) -> None:
    data_dir, work, lease = _make_work(tmp_path)
    assets = RecordingAssetStore()

    persistence = DeliveryTaskHandler(data_dir=data_dir, assets=assets).execute(
        work,
        lease,
        cancel_requested=lambda: False,
    )

    assert persistence.manifest_asset_id == "asset-delivery_manifest"
    assert persistence.zip_asset_id == "asset-delivery_zip"
    assert [path for path, _sha in assets.commits] == [
        "deliveries/v001/manifest.json",
        "deliveries/v001/delivery.zip",
    ]
    for relative_path, expected_sha256 in assets.commits:
        assert _sha256((data_dir / work.project_id / relative_path).read_bytes()) == expected_sha256
    assert persistence.manifest_clips[0].clip_id == "clip_1"


@pytest.mark.parametrize(
    "member_kind",
    ("video", "subtitle", "manifest", "index", "checksums", "zip"),
)
def test_existing_delivery_retry_rejects_exact_member_tamper(
    tmp_path: Path,
    member_kind: str,
) -> None:
    data_dir, work, lease = _make_work(tmp_path)
    initial_assets = RecordingAssetStore()
    handler = DeliveryTaskHandler(data_dir=data_dir, assets=initial_assets)
    handler.execute(work, lease, cancel_requested=lambda: False)
    delivery = data_dir / work.project_id / "deliveries" / "v001"
    manifest = json.loads((delivery / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["clips"][0]
    targets = {
        "video": delivery / entry["video_filename"],
        "subtitle": delivery / entry["subtitle_filename"],
        "manifest": delivery / "manifest.json",
        "index": delivery / "index.html",
        "checksums": delivery / "checksums.sha256",
        "zip": delivery / "delivery.zip",
    }
    targets[member_kind].write_bytes(f"attacker-{member_kind}".encode())
    retry_assets = RecordingAssetStore(existing_hashes=dict(initial_assets.existing_hashes))

    with pytest.raises(DeliveryError):
        DeliveryTaskHandler(data_dir=data_dir, assets=retry_assets).execute(
            work,
            lease,
            cancel_requested=lambda: False,
        )

    assert retry_assets.commits == []


def test_pending_existing_retry_verifies_every_zip_member_hash(tmp_path: Path) -> None:
    data_dir, work, lease = _make_work(tmp_path)
    initial_assets = RecordingAssetStore()
    DeliveryTaskHandler(data_dir=data_dir, assets=initial_assets).execute(
        work,
        lease,
        cancel_requested=lambda: False,
    )
    delivery = data_dir / work.project_id / "deliveries" / "v001"
    archive_path = delivery / "delivery.zip"
    with zipfile.ZipFile(archive_path, mode="r") as archive:
        names = archive.namelist()
        payloads = {name: archive.read(name) for name in names}
    subtitle_name = next(name for name in names if name.startswith("subtitles/"))
    payloads[subtitle_name] = b"x" * len(payloads[subtitle_name])
    archive_path.unlink()
    with zipfile.ZipFile(archive_path, mode="x") as archive:
        for name in names:
            archive.writestr(name, payloads[name])
    pending_assets = RecordingAssetStore()

    with pytest.raises(DeliveryError, match="ZIP member hash"):
        DeliveryTaskHandler(data_dir=data_dir, assets=pending_assets).execute(
            work,
            lease,
            cancel_requested=lambda: False,
        )

    assert pending_assets.commits == []
