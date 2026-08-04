import hashlib
from pathlib import Path

import pytest

from liveclip.application.pipeline import LeaseIdentity
from liveclip.media.artifacts import (
    ArtifactPublicationError,
    attempt_directory,
    cleanup_attempt_worktree,
    project_directory,
    publish_bytes_no_clobber,
    publish_file_no_clobber,
)


def test_project_directory_rejects_existing_symlink(tmp_path: Path) -> None:
    data_dir = tmp_path / "projects"
    data_dir.mkdir()
    target = data_dir / ("a" * 32)
    target.symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(ArtifactPublicationError, match="symbolic link"):
        project_directory(data_dir, "a" * 32)


def test_attempt_directory_rejects_symlinked_intermediate(tmp_path: Path) -> None:
    project_dir = tmp_path / ("a" * 32)
    project_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (project_dir / ".attempts").symlink_to(outside, target_is_directory=True)
    lease = LeaseIdentity(
        task_id="b" * 32,
        worker_id="worker-a",
        lease_token="c" * 64,
    )

    with pytest.raises(ArtifactPublicationError, match="symbolic links"):
        attempt_directory(project_dir, lease)

    assert not (outside / lease.task_id).exists()


def test_attempt_directory_rejects_symlinked_task_root(tmp_path: Path) -> None:
    project_dir = tmp_path / ("a" * 32)
    attempts = project_dir / ".attempts"
    attempts.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    lease = LeaseIdentity(
        task_id="b" * 32,
        worker_id="worker-a",
        lease_token="c" * 64,
    )
    (attempts / lease.task_id).symlink_to(outside, target_is_directory=True)

    with pytest.raises(ArtifactPublicationError, match="symbolic links"):
        attempt_directory(project_dir, lease)

    assert not (outside / lease.lease_token).exists()


def test_publish_bytes_rejects_symlinked_nested_run_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "runs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ArtifactPublicationError, match="without clobbering"):
        publish_bytes_no_clobber(project / "runs" / "run-a" / "result.json", b"{}")

    assert not (outside / "run-a").exists()


def test_publish_bytes_rejects_destination_endpoint_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_bytes(b'{"outside": true}')
    destination = tmp_path / "runs" / "result.json"
    destination.parent.mkdir()
    destination.symlink_to(outside)

    with pytest.raises(ArtifactPublicationError, match="without clobbering"):
        publish_bytes_no_clobber(destination, b'{"inside": true}')

    assert outside.read_bytes() == b'{"outside": true}'
    assert destination.is_symlink()


def test_publish_file_is_streamed_idempotent_and_no_clobber(tmp_path: Path) -> None:
    payload = b"video-payload" * 100_000
    source = tmp_path / "attempt" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(payload)
    destination = tmp_path / "clips" / "clip.mp4"
    expected_hash = hashlib.sha256(payload).hexdigest()

    assert publish_file_no_clobber(source, destination) == expected_hash
    assert not source.exists()
    assert destination.read_bytes() == payload

    same_source = tmp_path / "attempt" / "same.mp4"
    same_source.write_bytes(payload)
    assert publish_file_no_clobber(same_source, destination) == expected_hash
    assert same_source.read_bytes() == payload

    different_source = tmp_path / "attempt" / "different.mp4"
    different_source.write_bytes(b"different")
    with pytest.raises(ArtifactPublicationError, match="without clobbering"):
        publish_file_no_clobber(different_source, destination)
    assert different_source.read_bytes() == b"different"
    assert destination.read_bytes() == payload


def test_publish_file_rejects_source_endpoint_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside-video")
    source = tmp_path / "attempt" / "clip.mp4"
    source.parent.mkdir()
    source.symlink_to(outside)
    destination = tmp_path / "clips" / "clip.mp4"

    with pytest.raises(ArtifactPublicationError, match="without clobbering"):
        publish_file_no_clobber(source, destination)

    assert outside.read_bytes() == b"outside-video"
    assert not destination.exists()


def test_publish_file_rejects_destination_endpoint_symlink(tmp_path: Path) -> None:
    source = tmp_path / "attempt" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"inside-video")
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside-video")
    destination = tmp_path / "clips" / "clip.mp4"
    destination.parent.mkdir()
    destination.symlink_to(outside)

    with pytest.raises(ArtifactPublicationError, match="without clobbering"):
        publish_file_no_clobber(source, destination)

    assert source.read_bytes() == b"inside-video"
    assert outside.read_bytes() == b"outside-video"
    assert destination.is_symlink()


def test_attempt_cleanup_preserves_only_diagnostics_when_requested(tmp_path: Path) -> None:
    project = tmp_path / ("a" * 32)
    task_id = "b" * 32
    lease_token = "c" * 64
    attempt = project / ".attempts" / task_id / lease_token
    diagnostic = attempt / "diagnostics" / "ffmpeg-render.json"
    diagnostic.parent.mkdir(parents=True)
    diagnostic.write_text("{}", encoding="utf-8")
    (attempt / "runs" / "large").mkdir(parents=True)
    (attempt / "runs" / "large" / "frame.png").write_bytes(b"large-temporary")
    (attempt / "transcript").mkdir()
    (attempt / "transcript" / "transcript.json").write_text("{}", encoding="utf-8")

    assert cleanup_attempt_worktree(
        project,
        task_id=task_id,
        lease_token=lease_token,
        preserve_diagnostics=True,
    )
    assert diagnostic.read_text(encoding="utf-8") == "{}"
    assert not (attempt / "runs").exists()
    assert not (attempt / "transcript").exists()

    assert cleanup_attempt_worktree(
        project,
        task_id=task_id,
        lease_token=lease_token,
        preserve_diagnostics=False,
    )
    assert not attempt.exists()
