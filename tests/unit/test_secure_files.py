from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from liveclip.media import secure_files
from liveclip.media.secure_files import (
    SecureFileError,
    create_directory_exclusive_no_follow,
    ensure_directory_no_follow,
    publish_directory_no_replace_no_follow,
    publish_regular_file_immutable_no_follow,
    read_regular_file_no_follow,
    remove_tree_no_follow,
    write_bytes_immutable_no_follow,
)


def test_directory_creation_rejects_ancestor_symlink_without_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "project"
    root.mkdir()
    (root / "runs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SecureFileError, match="symlink-free"):
        ensure_directory_no_follow(root / "runs" / "run-a" / "artifacts")

    assert not (outside / "run-a").exists()


def test_directory_creation_rejects_component_swap_to_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "project"
    runs = root / "runs"
    outside = tmp_path / "outside"
    runs.mkdir(parents=True)
    outside.mkdir()
    real_open = secure_files.os.open
    swapped = False

    def racing_open(
        path: str | bytes,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "runs" and dir_fd is not None and not swapped:
            swapped = True
            runs.rename(root / "detached-runs")
            runs.symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(secure_files.os, "open", racing_open)

    with pytest.raises(SecureFileError, match="symlink-free"):
        ensure_directory_no_follow(runs / "run-a" / "artifacts")

    assert swapped
    assert not (outside / "run-a").exists()


def test_immutable_bytes_are_idempotent_but_never_clobber(tmp_path: Path) -> None:
    destination = tmp_path / "runs" / "artifact.json"

    write_bytes_immutable_no_follow(destination, b"first", max_bytes=5)
    write_bytes_immutable_no_follow(destination, b"first", max_bytes=5)

    with pytest.raises(SecureFileError, match="conflicts"):
        write_bytes_immutable_no_follow(destination, b"other", max_bytes=5)

    assert destination.read_bytes() == b"first"


def test_immutable_bytes_reject_endpoint_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    destination = tmp_path / "runs" / "artifact.bin"
    destination.parent.mkdir()
    destination.symlink_to(outside)

    with pytest.raises(SecureFileError):
        write_bytes_immutable_no_follow(destination, b"inside", max_bytes=6)

    assert outside.read_bytes() == b"outside"
    assert destination.is_symlink()


def test_regular_file_publication_streams_hash_and_preserves_idempotency(
    tmp_path: Path,
) -> None:
    payload = (b"streamed-content-" * 100_000) + b"end"
    source = tmp_path / "attempt" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(payload)
    destination = tmp_path / "clips" / "clip.mp4"

    digest = publish_regular_file_immutable_no_follow(
        source,
        destination,
        block_size=64 * 1024,
    )

    assert digest == hashlib.sha256(payload).hexdigest()
    assert destination.read_bytes() == payload
    assert not source.exists()

    retry_source = tmp_path / "attempt" / "retry.mp4"
    retry_source.write_bytes(payload)
    assert (
        publish_regular_file_immutable_no_follow(
            retry_source,
            destination,
            block_size=31 * 1024,
        )
        == digest
    )
    assert retry_source.read_bytes() == payload

    conflict_source = tmp_path / "attempt" / "conflict.mp4"
    conflict_source.write_bytes(b"different")
    with pytest.raises(SecureFileError, match="conflicts"):
        publish_regular_file_immutable_no_follow(conflict_source, destination)
    assert destination.read_bytes() == payload
    assert conflict_source.read_bytes() == b"different"


def test_regular_file_publication_checks_expected_hash_before_publication(
    tmp_path: Path,
) -> None:
    source = tmp_path / "attempt" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"committed-video")
    destination = tmp_path / "clips" / "clip.mp4"
    expected = hashlib.sha256(b"committed-video").hexdigest()

    assert (
        publish_regular_file_immutable_no_follow(
            source,
            destination,
            remove_source=False,
            expected_sha256=expected,
        )
        == expected
    )

    mismatched_destination = tmp_path / "clips" / "mismatched.mp4"
    with pytest.raises(SecureFileError, match="expected SHA-256"):
        publish_regular_file_immutable_no_follow(
            source,
            mismatched_destination,
            expected_sha256="0" * 64,
        )
    assert source.read_bytes() == b"committed-video"
    assert not mismatched_destination.exists()
    assert not tuple(mismatched_destination.parent.glob(".mismatched.mp4.*.tmp"))

    with pytest.raises(ValueError, match="lowercase"):
        publish_regular_file_immutable_no_follow(
            source,
            tmp_path / "clips" / "invalid.mp4",
            expected_sha256=expected.upper(),
        )


def test_directory_publication_is_inode_bound_atomic_and_no_clobber(tmp_path: Path) -> None:
    source = tmp_path / "deliveries" / ".v001-attempt"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text("verified", encoding="utf-8")
    source_identity = (source.stat().st_dev, source.stat().st_ino)
    destination = source.parent / "v001"

    publish_directory_no_replace_no_follow(source, destination)

    assert not source.exists()
    assert (destination.stat().st_dev, destination.stat().st_ino) == source_identity
    assert (destination / "manifest.json").read_text(encoding="utf-8") == "verified"

    conflict_source = source.parent / ".v001-conflict"
    conflict_source.mkdir()
    (conflict_source / "attacker.txt").write_text("attacker", encoding="utf-8")
    with pytest.raises(SecureFileError, match="already exists"):
        publish_directory_no_replace_no_follow(conflict_source, destination)
    assert (destination / "manifest.json").read_text(encoding="utf-8") == "verified"
    assert (conflict_source / "attacker.txt").read_text(encoding="utf-8") == "attacker"


def test_directory_publication_detects_source_swap_and_rolls_back_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "deliveries"
    source = parent / ".v001-attempt"
    source.mkdir(parents=True)
    (source / "manifest.json").write_text("verified", encoding="utf-8")
    attacker = parent / ".attacker-ready"
    attacker.mkdir()
    (attacker / "attacker.txt").write_text("attacker", encoding="utf-8")
    detached = parent / ".detached-verified"
    destination = parent / "v001"
    real_rename = secure_files._rename_directory_no_replace
    swapped = False

    def racing_rename(
        source_parent_fd: int,
        source_name: str,
        destination_parent_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal swapped
        if not swapped and destination_name == "v001":
            swapped = True
            os.rename(
                source_name,
                detached.name,
                src_dir_fd=source_parent_fd,
                dst_dir_fd=source_parent_fd,
            )
            os.rename(
                attacker.name,
                source_name,
                src_dir_fd=source_parent_fd,
                dst_dir_fd=source_parent_fd,
            )
        real_rename(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
        )

    monkeypatch.setattr(secure_files, "_rename_directory_no_replace", racing_rename)

    with pytest.raises(SecureFileError, match="pinned source"):
        publish_directory_no_replace_no_follow(source, destination)

    assert swapped
    assert not destination.exists()
    quarantined = tuple(parent.glob(".v001.rejected-*"))
    assert len(quarantined) == 1
    assert (quarantined[0] / "attacker.txt").read_text(encoding="utf-8") == "attacker"
    assert (detached / "manifest.json").read_text(encoding="utf-8") == "verified"


def test_identity_constrained_cleanup_never_deletes_replacement_directory(
    tmp_path: Path,
) -> None:
    ancestor = tmp_path / "deliveries"
    target = ancestor / ".v001-attempt"
    identity = create_directory_exclusive_no_follow(target)
    (target / "manifest.json").write_text("verified", encoding="utf-8")
    target.rename(ancestor / ".detached-verified")
    target.mkdir()
    (target / "attacker.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(SecureFileError, match="not the directory created"):
        remove_tree_no_follow(
            target,
            required_ancestor=ancestor,
            expected_identity=identity,
        )

    assert (target / "attacker.txt").read_text(encoding="utf-8") == "keep"
    assert (ancestor / ".detached-verified" / "manifest.json").is_file()


@pytest.mark.parametrize("symlink_location", ["source-ancestor", "source-endpoint"])
def test_regular_file_publication_rejects_source_symlinks(
    tmp_path: Path,
    symlink_location: str,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    real_source = outside / "clip.mp4"
    real_source.write_bytes(b"outside-video")
    attempt = tmp_path / "attempt"
    if symlink_location == "source-ancestor":
        attempt.symlink_to(outside, target_is_directory=True)
        source = attempt / "clip.mp4"
    else:
        attempt.mkdir()
        source = attempt / "clip.mp4"
        source.symlink_to(real_source)
    destination = tmp_path / "clips" / "clip.mp4"

    with pytest.raises(SecureFileError):
        publish_regular_file_immutable_no_follow(source, destination)

    assert real_source.read_bytes() == b"outside-video"
    assert not destination.exists()


def test_regular_file_publication_rejects_destination_ancestor_symlink(
    tmp_path: Path,
) -> None:
    source = tmp_path / "attempt" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    outside = tmp_path / "outside"
    outside.mkdir()
    clips = tmp_path / "clips"
    clips.symlink_to(outside, target_is_directory=True)

    with pytest.raises(SecureFileError):
        publish_regular_file_immutable_no_follow(source, clips / "clip.mp4")

    assert source.read_bytes() == b"video"
    assert not (outside / "clip.mp4").exists()


def test_regular_file_publication_loses_no_clobber_race_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "attempt" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"expected")
    destination = tmp_path / "clips" / "clip.mp4"
    real_link = secure_files.os.link
    injected = False

    def racing_link(
        source_name: str,
        destination_name: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        nonlocal injected
        if destination_name == destination.name and not injected:
            injected = True
            assert dst_dir_fd is not None
            descriptor = os.open(
                destination_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dst_dir_fd,
            )
            try:
                os.write(descriptor, b"raced")
            finally:
                os.close(descriptor)
        real_link(
            source_name,
            destination_name,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(secure_files.os, "link", racing_link)

    with pytest.raises(SecureFileError, match="conflicts"):
        publish_regular_file_immutable_no_follow(source, destination)

    assert injected
    assert destination.read_bytes() == b"raced"
    assert source.read_bytes() == b"expected"


def test_regular_file_publication_rejects_source_endpoint_swap_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "attempt" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"a" * (2 * 1024 * 1024))
    replacement = tmp_path / "replacement.mp4"
    replacement.write_bytes(b"replacement")
    destination = tmp_path / "clips" / "clip.mp4"
    real_read = secure_files.os.read
    swapped = False

    def racing_read(descriptor: int, size: int) -> bytes:
        nonlocal swapped
        block = real_read(descriptor, size)
        if block and not swapped:
            swapped = True
            source.unlink()
            source.symlink_to(replacement)
        return block

    monkeypatch.setattr(secure_files.os, "read", racing_read)

    with pytest.raises(SecureFileError, match="changed"):
        publish_regular_file_immutable_no_follow(
            source,
            destination,
            block_size=64 * 1024,
        )

    assert swapped
    assert source.is_symlink()
    assert replacement.read_bytes() == b"replacement"
    assert not destination.exists()


def test_read_rejects_ancestor_and_endpoint_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    real_file = outside / "data.json"
    real_file.write_bytes(b"{}")
    ancestor = tmp_path / "cache"
    ancestor.symlink_to(outside, target_is_directory=True)

    with pytest.raises(SecureFileError):
        read_regular_file_no_follow(ancestor / "data.json", max_bytes=2)

    regular_parent = tmp_path / "regular"
    regular_parent.mkdir()
    endpoint = regular_parent / "data.json"
    endpoint.symlink_to(real_file)
    with pytest.raises(SecureFileError):
        read_regular_file_no_follow(endpoint, max_bytes=2)


def test_remove_tree_does_not_follow_nested_or_target_symlinks(tmp_path: Path) -> None:
    ancestor = tmp_path / "attempts"
    target = ancestor / "task" / "lease" / "runs"
    target.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "keep.txt"
    outside_file.write_text("keep", encoding="utf-8")
    (target / "nested").mkdir()
    (target / "nested" / "temporary.bin").write_bytes(b"temporary")
    (target / "outside-link").symlink_to(outside, target_is_directory=True)

    assert remove_tree_no_follow(target, required_ancestor=ancestor) is True
    assert not target.exists()
    assert outside_file.read_text(encoding="utf-8") == "keep"

    linked_target = ancestor / "task" / "lease" / "linked"
    linked_target.parent.mkdir(parents=True, exist_ok=True)
    linked_target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SecureFileError, match="real directory"):
        remove_tree_no_follow(linked_target, required_ancestor=ancestor)
    assert outside_file.read_text(encoding="utf-8") == "keep"


def test_remove_tree_is_ancestor_constrained_and_rejects_endpoint_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ancestor = tmp_path / "deliveries"
    target = ancestor / ".v001-attempt"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text("verified", encoding="utf-8")
    attacker = ancestor / ".attacker-ready"
    attacker.mkdir()
    (attacker / "attacker.txt").write_text("keep", encoding="utf-8")
    detached = ancestor / ".detached-verified"
    real_rename = secure_files._rename_directory_no_replace
    swapped = False

    def racing_cleanup_rename(
        source_parent_fd: int,
        source_name: str,
        destination_parent_fd: int,
        destination_name: str,
    ) -> None:
        nonlocal swapped
        if not swapped and ".cleanup-" in destination_name:
            swapped = True
            os.rename(
                source_name,
                detached.name,
                src_dir_fd=source_parent_fd,
                dst_dir_fd=source_parent_fd,
            )
            os.rename(
                attacker.name,
                source_name,
                src_dir_fd=source_parent_fd,
                dst_dir_fd=source_parent_fd,
            )
        real_rename(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
        )

    monkeypatch.setattr(secure_files, "_rename_directory_no_replace", racing_cleanup_rename)

    with pytest.raises(SecureFileError, match="pinned source"):
        remove_tree_no_follow(target, required_ancestor=ancestor)

    assert swapped
    attacker_files = tuple(ancestor.glob(".*.rejected-*/attacker.txt"))
    assert len(attacker_files) == 1
    assert attacker_files[0].read_text(encoding="utf-8") == "keep"
    assert (detached / "manifest.json").read_text(encoding="utf-8") == "verified"
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(SecureFileError, match="escaped"):
        remove_tree_no_follow(outside, required_ancestor=ancestor)
