from pathlib import Path

import pytest

from liveclip.application.pipeline import LeaseIdentity
from liveclip.media.artifacts import (
    ArtifactPublicationError,
    attempt_directory,
    project_directory,
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
