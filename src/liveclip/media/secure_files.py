from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import stat
import sys
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class SecureFileError(ValueError):
    """A local artifact could not be handled as one stable regular file."""


class SecureFileMissing(SecureFileError):
    """The requested file or one of its directories does not exist."""


class SecureFileHashMismatch(SecureFileError):
    """Pinned source bytes did not match their committed SHA-256."""


_FileIdentity = tuple[int, int, int, int, int]
_DirectoryIdentity = tuple[int, int]


def cross_launch_source_stat_matches(
    observed_path: Path,
    metadata: os.stat_result,
    *,
    expected_path: Path,
    expected_size_bytes: int,
    expected_mtime_ns: int,
    expected_inode: int | None,
) -> bool:
    """Match a persisted source reference across process and mount lifetimes.

    ``st_dev`` is deliberately absent. On macOS it identifies the current mount
    instance and can change after a reboot or volume remount even when the same
    path and inode still refer to byte-identical media. Callers that consume
    source bytes must additionally verify the persisted SHA-256 while the file
    is pinned. ``PinnedRegularFile.validate_binding`` retains the stricter
    current-open identity, including device and ctime, for TOCTOU protection.
    """

    return (
        observed_path == expected_path
        and stat.S_ISREG(metadata.st_mode)
        and metadata.st_size == expected_size_bytes
        and metadata.st_mtime_ns == expected_mtime_ns
        and (expected_inode is None or metadata.st_ino == expected_inode)
    )


@dataclass(slots=True)
class PinnedRegularFile:
    """One component-anchored regular file held open across child processes."""

    path: Path
    descriptor: int
    metadata: os.stat_result
    _parent_descriptor: int
    _filename: str
    _identity: _FileIdentity
    _closed: bool = False

    @property
    def process_path(self) -> Path:
        self._require_open()
        return Path("/dev/fd") / str(self.descriptor)

    @property
    def pass_fds(self) -> tuple[int, ...]:
        self._require_open()
        return (self.descriptor,)

    def sha256(
        self,
        *,
        block_size: int = 1024 * 1024,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> str:
        self._require_open()
        if block_size <= 0:
            raise ValueError("fingerprint block size must be positive")
        value = self._sha256_descriptor(
            block_size=block_size,
            cancel_requested=cancel_requested,
        )
        self.validate_binding()
        return value

    def sha256_at(
        self,
        path: Path,
        *,
        block_size: int = 1024 * 1024,
    ) -> str:
        """Hash the held bytes and prove an arbitrary endpoint binds to this FD."""

        self._require_open()
        value = self._sha256_descriptor(block_size=block_size, cancel_requested=None)
        self.validate_at(path)
        return value

    def read_bytes(self, *, max_bytes: int) -> bytes:
        """Read bounded bytes from this FD and retain its original endpoint proof."""

        self._require_open()
        if max_bytes <= 0:
            raise ValueError("maximum file size must be positive")
        if self.metadata.st_size > max_bytes:
            raise SecureFileError("artifact exceeds its safe size limit")
        value = bytearray()
        offset = 0
        while offset < self.metadata.st_size:
            block = os.pread(
                self.descriptor,
                min(1024 * 1024, self.metadata.st_size - offset),
                offset,
            )
            if not block:
                break
            value.extend(block)
            offset += len(block)
        if offset != self.metadata.st_size:
            raise SecureFileError("pinned file changed size while reading")
        self.validate_binding()
        return bytes(value)

    def validate_binding(self) -> None:
        self._require_open()
        _assert_stable_regular_endpoint(
            self._parent_descriptor,
            self._filename,
            self.descriptor,
            expected=self._identity,
        )

    def validate_at(self, path: Path) -> None:
        """Prove another no-follow endpoint resolves to this held file identity."""

        self._require_open()
        parent_fd, filename = _open_parent(path, create=False)
        try:
            _assert_stable_regular_endpoint(
                parent_fd,
                filename,
                self.descriptor,
                expected=self._identity,
            )
        finally:
            os.close(parent_fd)

    def seal_after_write(self) -> None:
        """Fsync a newly-created writable file and capture its final identity."""

        self._require_open()
        try:
            os.fsync(self.descriptor)
            opened_now = os.fstat(self.descriptor)
            current = os.stat(
                self._filename,
                dir_fd=self._parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise SecureFileError("created file binding changed before sealing") from exc
        if (
            not stat.S_ISREG(opened_now.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or (opened_now.st_dev, opened_now.st_ino)
            != (self.metadata.st_dev, self.metadata.st_ino)
            or (current.st_dev, current.st_ino) != (opened_now.st_dev, opened_now.st_ino)
        ):
            raise SecureFileError("created file binding changed before sealing")
        self.metadata = opened_now
        self._identity = _file_identity(opened_now)
        os.fsync(self._parent_descriptor)

    def publish_no_replace(self, destination: Path) -> None:
        """Atomically rename this exact inode to a new, previously absent endpoint."""

        self._require_open()
        target = _absolute_path(destination)
        destination_parent_fd, destination_name = _open_parent(target, create=True)
        transferred_parent = False
        try:
            self.validate_binding()
            expected_device_inode = (self.metadata.st_dev, self.metadata.st_ino)
            expected_size = self.metadata.st_size
            expected_sha256 = self.sha256()
            try:
                _rename_directory_no_replace(
                    self._parent_descriptor,
                    self._filename,
                    destination_parent_fd,
                    destination_name,
                )
            except FileExistsError as exc:
                raise SecureFileError("publication destination already exists") from exc
            try:
                opened_now = os.fstat(self.descriptor)
                current = os.stat(
                    destination_name,
                    dir_fd=destination_parent_fd,
                    follow_symlinks=False,
                )
                if (
                    not stat.S_ISREG(opened_now.st_mode)
                    or not stat.S_ISREG(current.st_mode)
                    or (opened_now.st_dev, opened_now.st_ino) != expected_device_inode
                    or (current.st_dev, current.st_ino) != expected_device_inode
                    or opened_now.st_size != expected_size
                    or current.st_size != expected_size
                    or _sha256_open_descriptor(self.descriptor) != expected_sha256
                ):
                    raise SecureFileError("published regular file identity or bytes changed")
                os.fsync(self.descriptor)
                os.fsync(self._parent_descriptor)
                os.fsync(destination_parent_fd)
            except (OSError, SecureFileError) as publication_error:
                try:
                    _withdraw_pinned_regular_publication(
                        destination_parent_fd,
                        destination_name,
                        self.descriptor,
                        expected=expected_device_inode,
                    )
                except (OSError, SecureFileError) as withdrawal_error:
                    raise SecureFileError(
                        "published regular file failure could not be withdrawn safely"
                    ) from withdrawal_error
                raise SecureFileError(
                    "published database does not match the pinned source or was not durable"
                ) from publication_error
            previous_parent_fd = self._parent_descriptor
            self.metadata = opened_now
            self._identity = _file_identity(opened_now)
            self._parent_descriptor = destination_parent_fd
            self._filename = destination_name
            self.path = target
            transferred_parent = True
            with suppress(OSError):
                os.close(previous_parent_fd)
        finally:
            if not transferred_parent:
                os.close(destination_parent_fd)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        os.close(self.descriptor)
        os.close(self._parent_descriptor)

    def __enter__(self) -> PinnedRegularFile:
        self._require_open()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed:
            raise SecureFileError("pinned file is already closed")

    def _sha256_descriptor(
        self,
        *,
        block_size: int,
        cancel_requested: Callable[[], bool] | None,
    ) -> str:
        if block_size <= 0:
            raise ValueError("fingerprint block size must be positive")
        digest = hashlib.sha256()
        offset = 0
        while True:
            if cancel_requested is not None and cancel_requested():
                raise InterruptedError("pinned file fingerprint was cancelled")
            block = os.pread(self.descriptor, block_size, offset)
            if not block:
                break
            digest.update(block)
            offset += len(block)
        if cancel_requested is not None and cancel_requested():
            raise InterruptedError("pinned file fingerprint was cancelled")
        current = os.fstat(self.descriptor)
        if offset != self.metadata.st_size or _file_identity(current) != self._identity:
            raise SecureFileError("pinned file changed while hashing")
        return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class PinnedFileEvidence:
    """One held regular file and the exact bytes approved for publication."""

    pinned: PinnedRegularFile
    sha256: str
    size_bytes: int

    def validate_at(self, path: Path, *, rehash: bool) -> None:
        observed = self.pinned.sha256_at(path) if rehash else None
        if rehash and observed != self.sha256:
            raise SecureFileHashMismatch("pinned file bytes changed during publication")
        if not rehash:
            self.pinned.validate_at(path)
        if self.pinned.metadata.st_size != self.size_bytes:
            raise SecureFileError("pinned file size differs from its publication evidence")


def open_pinned_regular_file(path: Path) -> PinnedRegularFile:
    """Open one regular file without following any path component."""

    target = _absolute_path(path)
    parent_fd, filename = _open_parent(target, create=False)
    try:
        descriptor, metadata = _open_regular_from_parent(parent_fd, filename)
    except Exception:
        os.close(parent_fd)
        raise
    return PinnedRegularFile(
        path=target,
        descriptor=descriptor,
        metadata=metadata,
        _parent_descriptor=parent_fd,
        _filename=filename,
        _identity=_file_identity(metadata),
    )


def create_pinned_regular_file_no_follow(path: Path) -> PinnedRegularFile:
    """Exclusively create one writable regular file and keep its inode pinned."""

    target = _absolute_path(path)
    parent_fd, filename = _open_parent(target, create=True)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            filename,
            _read_write_create_flags(),
            0o600,
            dir_fd=parent_fd,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SecureFileError("created artifact must be a regular file")
        return PinnedRegularFile(
            path=target,
            descriptor=descriptor,
            metadata=metadata,
            _parent_descriptor=parent_fd,
            _filename=filename,
            _identity=_file_identity(metadata),
        )
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)
        raise


def capture_pinned_file_evidence(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> PinnedFileEvidence:
    """Open, hash and retain one no-follow file for a later atomic publication."""

    _validate_optional_sha256(expected_sha256)
    pinned = open_pinned_regular_file(path)
    try:
        sha256 = pinned.sha256()
        if expected_sha256 is not None and sha256 != expected_sha256:
            raise SecureFileHashMismatch("artifact source differs from its expected SHA-256")
        return PinnedFileEvidence(
            pinned=pinned,
            sha256=sha256,
            size_bytes=pinned.metadata.st_size,
        )
    except Exception:
        pinned.close()
        raise


def hash_regular_file_no_follow(
    path: Path,
    *,
    block_size: int = 1024 * 1024,
    cancel_requested: Callable[[], bool] | None = None,
) -> tuple[str, int]:
    """Return the SHA-256 and stable size of one no-follow regular file."""

    with open_pinned_regular_file(path) as pinned:
        return (
            pinned.sha256(
                block_size=block_size,
                cancel_requested=cancel_requested,
            ),
            pinned.metadata.st_size,
        )


def ensure_directory_no_follow(path: Path, *, mode: int = 0o700) -> Path:
    """Create a directory chain without following any symbolic-link component."""

    if mode <= 0 or mode > 0o777:
        raise ValueError("directory mode must be a positive permission mask")
    target = _absolute_path(path)
    descriptor = _open_directory(target, create=True, mode=mode)
    os.close(descriptor)
    return target


def create_directory_exclusive_no_follow(
    path: Path,
    *,
    mode: int = 0o700,
) -> tuple[int, int]:
    """Create one new directory and return the device/inode we own.

    This is intended for random attempt directories.  Unlike
    ``ensure_directory_no_follow``, an existing endpoint is always a conflict,
    so cleanup can later be constrained to the exact directory created here.
    """

    if mode <= 0 or mode > 0o777:
        raise ValueError("directory mode must be a positive permission mask")
    parent_fd, name = _open_parent(path, create=True)
    descriptor: int | None = None
    try:
        try:
            os.mkdir(name, mode, dir_fd=parent_fd)
        except FileExistsError as exc:
            raise SecureFileError("exclusive directory endpoint already exists") from exc
        descriptor, metadata = _open_directory_from_parent(parent_fd, name)
        identity = _directory_identity(metadata)
        _assert_stable_directory_endpoint(
            parent_fd,
            name,
            descriptor,
            expected=identity,
        )
        os.fsync(descriptor)
        os.fsync(parent_fd)
        return identity
    except SecureFileError:
        raise
    except OSError as exc:
        raise SecureFileError("exclusive directory could not be created safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)


def require_directory_no_follow(path: Path) -> Path:
    """Prove that an existing directory chain contains no symbolic links."""

    target = _absolute_path(path)
    descriptor = _open_directory(target, create=False, mode=0o700)
    os.close(descriptor)
    return target


def directory_identity_no_follow(path: Path) -> tuple[int, int]:
    """Return a stable device/inode identity for one symlink-free directory."""

    target = _absolute_path(path)
    descriptor = _open_directory(target, create=False, mode=0o700)
    try:
        return _directory_identity(os.fstat(descriptor))
    finally:
        os.close(descriptor)


def interrupted_tree_cleanup_path(path: Path) -> Path:
    """Return the deterministic private name used while deleting one tree."""

    target = _absolute_path(path)
    return target.with_name(f".{target.name}.cleanup")


def cleanup_tree_identity_no_follow(path: Path) -> tuple[int, int] | None:
    """Inspect an original or interrupted cleanup endpoint without links.

    A process may terminate after the exact directory is renamed but before
    recursive deletion completes. Exactly one of the public endpoint and its
    deterministic cleanup endpoint may exist; both is a fail-closed conflict.
    """

    identities: list[tuple[int, int]] = []
    for endpoint in (path, interrupted_tree_cleanup_path(path)):
        try:
            identities.append(directory_identity_no_follow(endpoint))
        except SecureFileMissing:
            continue
    if len(identities) > 1:
        raise SecureFileError("cleanup has competing original and interrupted endpoints")
    return identities[0] if identities else None


def read_regular_file_no_follow(path: Path, *, max_bytes: int) -> bytes:
    """Read through an anchored openat chain that rejects every symlink component."""

    if max_bytes <= 0:
        raise ValueError("maximum file size must be positive")
    parent_fd, filename = _open_parent(path, create=False)
    try:
        return _read_from_parent(parent_fd, filename, max_bytes=max_bytes)
    finally:
        os.close(parent_fd)


def read_regular_text_no_follow(path: Path, *, max_bytes: int) -> str:
    try:
        return read_regular_file_no_follow(path, max_bytes=max_bytes).decode("utf-8")
    except UnicodeError as exc:
        raise SecureFileError("artifact is not valid UTF-8") from exc


def write_bytes_immutable_no_follow(path: Path, value: bytes, *, max_bytes: int) -> None:
    """Publish bytes once within a symlink-free directory chain."""

    if max_bytes <= 0:
        raise ValueError("maximum file size must be positive")
    if len(value) > max_bytes:
        raise SecureFileError("artifact exceeds its safe size limit")
    parent_fd, filename = _open_parent(path, create=True)
    temporary_name = f".{filename}.{uuid.uuid4().hex}.tmp"
    flags = _write_create_flags()
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=parent_fd)
        _write_all(descriptor, value)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        try:
            os.link(
                temporary_name,
                filename,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            existing = _read_from_parent(parent_fd, filename, max_bytes=max_bytes)
            if existing != value:
                raise SecureFileError("immutable artifact conflicts with existing bytes") from None
        else:
            _assert_same_regular_binding(parent_fd, temporary_name, parent_fd, filename)
        os.fsync(parent_fd)
    except SecureFileError:
        raise
    except OSError as exc:
        raise SecureFileError("immutable artifact could not be published safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            os.unlink(temporary_name, dir_fd=parent_fd)
        os.close(parent_fd)


def write_text_immutable_no_follow(path: Path, value: str, *, max_bytes: int) -> None:
    """Publish bounded UTF-8 text once within a symlink-free directory chain."""

    write_bytes_immutable_no_follow(path, value.encode("utf-8"), max_bytes=max_bytes)


def write_text_atomic_no_follow(path: Path, value: str, *, max_bytes: int) -> None:
    """Atomically replace bounded UTF-8 text without following path components."""

    payload = value.encode("utf-8")
    if max_bytes <= 0:
        raise ValueError("maximum file size must be positive")
    if len(payload) > max_bytes:
        raise SecureFileError("artifact exceeds its safe size limit")
    parent_fd, filename = _open_parent(path, create=True)
    temporary_name = f".{filename}.{uuid.uuid4().hex}.tmp"
    descriptor: int | None = None
    try:
        try:
            current = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            current = None
        if current is not None and not stat.S_ISREG(current.st_mode):
            raise SecureFileError("mutable artifact target must be a regular file")
        descriptor = os.open(temporary_name, _write_create_flags(), 0o600, dir_fd=parent_fd)
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(
            temporary_name,
            filename,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        published = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(published.st_mode) or published.st_size != len(payload):
            raise SecureFileError("mutable artifact publication is unstable")
        os.fsync(parent_fd)
    except SecureFileError:
        raise
    except OSError as exc:
        raise SecureFileError("mutable artifact could not be published safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            os.unlink(temporary_name, dir_fd=parent_fd)
        os.close(parent_fd)


def publish_regular_file_immutable_no_follow(
    source: Path,
    destination: Path,
    *,
    remove_source: bool = True,
    block_size: int = 1024 * 1024,
    expected_sha256: str | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> str:
    """Stream one stable regular file into an immutable no-follow destination."""

    if block_size <= 0:
        raise ValueError("publication block size must be positive")
    _validate_optional_sha256(expected_sha256)
    source_parent_fd, source_name = _open_parent(source, create=False)
    destination_parent_fd: int | None = None
    source_fd: int | None = None
    temporary_fd: int | None = None
    temporary_name: str | None = None
    try:
        source_fd, source_metadata = _open_regular_from_parent(source_parent_fd, source_name)
        if source_metadata.st_size <= 0:
            raise SecureFileError("artifact source must not be empty")
        source_identity = _file_identity(source_metadata)

        destination_parent_fd, destination_name = _open_parent(destination, create=True)
        temporary_name = f".{destination_name}.{uuid.uuid4().hex}.tmp"
        temporary_fd = os.open(
            temporary_name,
            _write_create_flags(),
            0o600,
            dir_fd=destination_parent_fd,
        )
        digest = hashlib.sha256()
        copied = 0
        if progress is not None:
            progress(0, source_metadata.st_size)
        while True:
            block = os.read(source_fd, block_size)
            if not block:
                break
            digest.update(block)
            _write_all(temporary_fd, block)
            copied += len(block)
            if progress is not None:
                progress(copied, source_metadata.st_size)
        if copied != source_metadata.st_size:
            raise SecureFileError("artifact source changed size while reading")
        _assert_stable_regular_endpoint(
            source_parent_fd,
            source_name,
            source_fd,
            expected=source_identity,
        )
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = None
        source_hash = digest.hexdigest()
        if expected_sha256 is not None and source_hash != expected_sha256:
            raise SecureFileHashMismatch("artifact source differs from its expected SHA-256")

        try:
            os.link(
                temporary_name,
                destination_name,
                src_dir_fd=destination_parent_fd,
                dst_dir_fd=destination_parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            existing_hash = _hash_from_parent(
                destination_parent_fd,
                destination_name,
                block_size=block_size,
            )
            if existing_hash != source_hash:
                raise SecureFileError("immutable artifact conflicts with existing bytes") from None
            return source_hash

        _assert_same_regular_binding(
            destination_parent_fd,
            temporary_name,
            destination_parent_fd,
            destination_name,
        )
        os.fsync(destination_parent_fd)
        if remove_source and _absolute_path(source) != _absolute_path(destination):
            _unlink_if_same(
                source_parent_fd,
                source_name,
                expected=source_identity,
            )
        return source_hash
    except SecureFileError:
        raise
    except OSError as exc:
        raise SecureFileError("regular file could not be published safely") from exc
    finally:
        if temporary_fd is not None:
            os.close(temporary_fd)
        if temporary_name is not None and destination_parent_fd is not None:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=destination_parent_fd)
        if source_fd is not None:
            os.close(source_fd)
        if destination_parent_fd is not None:
            os.close(destination_parent_fd)
        os.close(source_parent_fd)


def publish_directory_no_replace_no_follow(
    source: Path,
    destination: Path,
    *,
    pinned_files: Mapping[str, PinnedFileEvidence] | None = None,
    expected_identity: tuple[int, int] | None = None,
) -> None:
    """Atomically publish one pinned directory without replacing an existing name.

    The native rename is anchored to no-follow parent descriptors. The source
    directory is held open across the operation and the destination must bind to
    that exact device/inode before publication is accepted.
    """

    source_path = _absolute_path(source)
    destination_path = _absolute_path(destination)
    if source_path == destination_path:
        raise SecureFileError("directory publication source and destination must differ")
    source_parent_fd, source_name = _open_parent(source_path, create=False)
    destination_parent_fd: int | None = None
    source_fd: int | None = None
    expected_files = dict(pinned_files or {})
    try:
        source_fd, source_metadata = _open_directory_from_parent(source_parent_fd, source_name)
        source_identity = _directory_identity(source_metadata)
        if expected_identity is not None and source_identity != expected_identity:
            raise SecureFileError("directory publication source identity changed")
        destination_parent_fd, destination_name = _open_parent(destination_path, create=True)
        if expected_files:
            _validate_pinned_directory_files(
                root_path=source_path,
                root_fd=source_fd,
                pinned_files=expected_files,
                rehash=False,
            )
        os.fsync(source_fd)
        _publish_pinned_directory_no_replace(
            source_parent_fd=source_parent_fd,
            source_name=source_name,
            destination_parent_fd=destination_parent_fd,
            destination_name=destination_name,
            source_fd=source_fd,
            expected=source_identity,
        )
        if expected_files:
            try:
                _validate_pinned_directory_files(
                    root_path=destination_path,
                    root_fd=source_fd,
                    pinned_files=expected_files,
                    rehash=True,
                )
            except SecureFileError as evidence_error:
                try:
                    _rollback_pinned_directory_after_content_failure(
                        source_parent_fd=source_parent_fd,
                        source_name=source_name,
                        destination_parent_fd=destination_parent_fd,
                        destination_name=destination_name,
                        expected=source_identity,
                    )
                except (OSError, SecureFileError) as rollback_error:
                    raise SecureFileError(
                        "directory member failure could not be rolled back safely"
                    ) from rollback_error
                raise SecureFileError(
                    "published directory members differ from their pinned evidence"
                ) from evidence_error
    except SecureFileError:
        raise
    except OSError as exc:
        raise SecureFileError("directory could not be published safely") from exc
    finally:
        if source_fd is not None:
            os.close(source_fd)
        if destination_parent_fd is not None:
            os.close(destination_parent_fd)
        os.close(source_parent_fd)


def validate_pinned_directory_files_no_follow(
    root: Path,
    pinned_files: Mapping[str, PinnedFileEvidence],
    *,
    rehash: bool = True,
) -> None:
    """Validate an exact regular-file tree against already-held file evidence."""

    root_path = _absolute_path(root)
    root_fd = _open_directory(root_path, create=False, mode=0o700)
    try:
        _validate_pinned_directory_files(
            root_path=root_path,
            root_fd=root_fd,
            pinned_files=pinned_files,
            rehash=rehash,
        )
    finally:
        os.close(root_fd)


def remove_tree_no_follow(
    path: Path,
    *,
    required_ancestor: Path,
    expected_identity: tuple[int, int] | None = None,
) -> bool:
    """Remove one descendant directory tree without following symbolic links."""

    target = _absolute_path(path)
    ancestor = _absolute_path(required_ancestor)
    try:
        relative = target.relative_to(ancestor)
    except ValueError as exc:
        raise SecureFileError("cleanup target escaped its required ancestor") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise SecureFileError("cleanup target must be a strict normalized descendant")
    try:
        ancestor_fd = _open_directory(ancestor, create=False, mode=0o700)
    except SecureFileMissing:
        return False
    try:
        ancestor_metadata = os.fstat(ancestor_fd)
        root_filesystem = _directory_filesystem_identity(ancestor_fd, ancestor_metadata)
    except OSError as exc:
        os.close(ancestor_fd)
        raise SecureFileError("cleanup ancestor filesystem could not be inspected") from exc
    visited: set[_DirectoryIdentity] = {_directory_identity(ancestor_metadata)}
    parent_fd = ancestor_fd
    opened_parents: list[int] = []
    try:
        for component in relative.parts[:-1]:
            try:
                child = os.open(component, _directory_flags(), dir_fd=parent_fd)
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise SecureFileError("cleanup directory chain is not symlink-free") from exc
            child_metadata = os.fstat(child)
            child_identity = _directory_identity(child_metadata)
            if (
                _directory_filesystem_identity(child, child_metadata) != root_filesystem
                or child_identity in visited
            ):
                os.close(child)
                raise SecureFileError(
                    "cleanup directory chain crosses or repeats a filesystem boundary"
                )
            visited.add(child_identity)
            opened_parents.append(child)
            parent_fd = child
        name = relative.parts[-1]
        quarantine_name = interrupted_tree_cleanup_path(target).name
        resumed_cleanup = False
        try:
            target_fd, target_metadata = _open_directory_from_parent(parent_fd, name)
        except SecureFileMissing:
            try:
                target_fd, target_metadata = _open_directory_from_parent(
                    parent_fd,
                    quarantine_name,
                )
            except SecureFileMissing:
                return False
            if expected_identity is None:
                os.close(target_fd)
                raise SecureFileError(
                    "interrupted cleanup requires an expected directory identity"
                ) from None
            resumed_cleanup = True
        if not resumed_cleanup:
            try:
                os.stat(quarantine_name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            except OSError as exc:
                os.close(target_fd)
                raise SecureFileError("cleanup quarantine endpoint could not be inspected") from exc
            else:
                os.close(target_fd)
                raise SecureFileError("cleanup has competing original and interrupted endpoints")
        target_identity = _directory_identity(target_metadata)
        if (
            _directory_filesystem_identity(target_fd, target_metadata) != root_filesystem
            or target_identity in visited
        ):
            os.close(target_fd)
            raise SecureFileError("cleanup target crosses or repeats a filesystem boundary")
        visited.add(target_identity)
        if expected_identity is not None and target_identity != expected_identity:
            os.close(target_fd)
            raise SecureFileError("cleanup target is not the directory created by this operation")
        try:
            if not resumed_cleanup:
                _publish_pinned_directory_no_replace(
                    source_parent_fd=parent_fd,
                    source_name=name,
                    destination_parent_fd=parent_fd,
                    destination_name=quarantine_name,
                    source_fd=target_fd,
                    expected=target_identity,
                )
            _remove_open_directory_contents(
                target_fd,
                root_filesystem=root_filesystem,
                visited=visited,
            )
            _assert_stable_directory_endpoint(
                parent_fd,
                quarantine_name,
                target_fd,
                expected=target_identity,
            )
            os.rmdir(quarantine_name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except (OSError, SecureFileError) as exc:
            try:
                _restore_cleanup_quarantine(
                    parent_fd,
                    original_name=name,
                    quarantine_name=quarantine_name,
                    directory_fd=target_fd,
                    expected=target_identity,
                )
            except SecureFileError as rollback_exc:
                raise SecureFileError(
                    "cleanup was interrupted and its quarantined remainder could not be restored"
                ) from rollback_exc
            raise SecureFileError("cleanup target changed while being removed") from exc
        finally:
            os.close(target_fd)
        return True
    finally:
        for descriptor in reversed(opened_parents):
            os.close(descriptor)
        os.close(ancestor_fd)


def remove_directory_children_except_no_follow(
    path: Path,
    *,
    preserve_names: frozenset[str],
    expected_identity: tuple[int, int],
) -> bool:
    """Delete every child except an exact allowlist under one pinned directory."""

    if any(
        not name or name in {".", ".."} or "/" in name or "\\" in name for name in preserve_names
    ):
        raise SecureFileError("cleanup preserve name is invalid")
    parent_fd, name = _open_parent(path, create=False)
    target_fd: int | None = None
    changed = False
    try:
        target_fd, target_metadata = _open_directory_from_parent(parent_fd, name)
        target_identity = _directory_identity(target_metadata)
        if target_identity != expected_identity:
            raise SecureFileError("cleanup target is not the recorded attempt directory")
        root_filesystem = _directory_filesystem_identity(target_fd, target_metadata)
        visited = {target_identity}
        with os.scandir(target_fd) as iterator:
            entries = tuple(iterator)
        for entry in entries:
            entry_name = entry.name
            metadata = entry.stat(follow_symlinks=False)
            if entry_name in preserve_names:
                if not stat.S_ISDIR(metadata.st_mode):
                    raise SecureFileError("preserved cleanup entry is not a directory")
                continue
            if stat.S_ISDIR(metadata.st_mode):
                child_fd, child_metadata = _open_directory_from_parent(target_fd, entry_name)
                child_identity = _directory_identity(child_metadata)
                try:
                    if child_identity != _directory_identity(metadata):
                        raise SecureFileError("cleanup child directory binding changed")
                    if (
                        _directory_filesystem_identity(child_fd, child_metadata) != root_filesystem
                        or child_identity in visited
                    ):
                        raise SecureFileError(
                            "cleanup child crosses or repeats a filesystem boundary"
                        )
                    visited.add(child_identity)
                    _remove_open_directory_contents(
                        child_fd,
                        root_filesystem=root_filesystem,
                        visited=visited,
                    )
                    _assert_stable_directory_endpoint(
                        target_fd,
                        entry_name,
                        child_fd,
                        expected=child_identity,
                    )
                finally:
                    os.close(child_fd)
                os.rmdir(entry_name, dir_fd=target_fd)
            else:
                os.unlink(entry_name, dir_fd=target_fd)
            changed = True
        _assert_stable_directory_endpoint(
            parent_fd,
            name,
            target_fd,
            expected=expected_identity,
        )
        os.fsync(target_fd)
        os.fsync(parent_fd)
        return changed
    except OSError as exc:
        raise SecureFileError("attempt cleanup changed while removing children") from exc
    finally:
        if target_fd is not None:
            os.close(target_fd)
        os.close(parent_fd)


def _remove_open_directory_contents(
    descriptor: int,
    *,
    root_filesystem: tuple[int, int | None],
    visited: set[_DirectoryIdentity],
) -> None:
    try:
        with os.scandir(descriptor) as iterator:
            entries = tuple(iterator)
    except OSError as exc:
        raise SecureFileError("cleanup directory could not be enumerated") from exc
    for entry in entries:
        name = entry.name
        if name in {"", ".", ".."}:
            raise SecureFileError("cleanup directory contains an invalid entry")
        try:
            metadata = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                if metadata.st_dev != root_filesystem[0]:
                    raise SecureFileError("cleanup refuses to cross a filesystem boundary")
                child_fd, child_metadata = _open_directory_from_parent(descriptor, name)
                child_identity = _directory_identity(child_metadata)
                if child_identity != _directory_identity(metadata):
                    os.close(child_fd)
                    raise SecureFileError("cleanup child directory binding changed")
                try:
                    if _directory_filesystem_identity(child_fd, child_metadata) != root_filesystem:
                        raise SecureFileError("cleanup refuses to cross a filesystem boundary")
                    if child_identity in visited:
                        raise SecureFileError("cleanup refuses a repeated directory identity")
                    visited.add(child_identity)
                    _remove_open_directory_contents(
                        child_fd,
                        root_filesystem=root_filesystem,
                        visited=visited,
                    )
                    _assert_stable_directory_endpoint(
                        descriptor,
                        name,
                        child_fd,
                        expected=child_identity,
                    )
                finally:
                    os.close(child_fd)
                os.rmdir(name, dir_fd=descriptor)
            else:
                os.unlink(name, dir_fd=descriptor)
        except OSError as exc:
            raise SecureFileError("cleanup entry changed while being removed") from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise SecureFileError("cleanup directory could not be synchronized") from exc


def _restore_cleanup_quarantine(
    parent_fd: int,
    *,
    original_name: str,
    quarantine_name: str,
    directory_fd: int,
    expected: _DirectoryIdentity,
) -> None:
    """Restore an interrupted deterministic quarantine when it still belongs to us."""

    try:
        _assert_stable_directory_endpoint(
            parent_fd,
            quarantine_name,
            directory_fd,
            expected=expected,
        )
    except SecureFileError:
        # The rename may have failed before publication; the original endpoint
        # must then still be the exact pinned directory.
        _assert_stable_directory_endpoint(
            parent_fd,
            original_name,
            directory_fd,
            expected=expected,
        )
        return
    try:
        os.stat(original_name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise SecureFileError("cleanup original endpoint was recreated during rollback")
    try:
        os.rename(
            quarantine_name,
            original_name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        _assert_stable_directory_endpoint(
            parent_fd,
            original_name,
            directory_fd,
            expected=expected,
        )
        os.fsync(parent_fd)
    except OSError as exc:
        raise SecureFileError("cleanup quarantine could not be rolled back") from exc


def _directory_filesystem_identity(
    descriptor: int,
    metadata: os.stat_result,
) -> tuple[int, int | None]:
    try:
        filesystem = os.fstatvfs(descriptor)
    except OSError as exc:
        raise SecureFileError("cleanup filesystem identity could not be inspected") from exc
    fsid = getattr(filesystem, "f_fsid", None)
    return metadata.st_dev, int(fsid) if fsid is not None else None


def _open_parent(path: Path, *, create: bool) -> tuple[int, str]:
    target = _absolute_path(path)
    if target.name in {"", ".", ".."}:
        raise SecureFileError("artifact path has no safe filename")
    descriptor = _open_directory(target.parent, create=create, mode=0o700)
    return descriptor, target.name


def _open_directory(path: Path, *, create: bool, mode: int) -> int:
    flags = _directory_flags()
    search_flags = flags | getattr(os, "O_SEARCH", 0)
    try:
        descriptor = os.open(path.anchor, flags)
    except OSError as exc:  # pragma: no cover - a valid absolute anchor is expected
        raise SecureFileError("artifact directory anchor cannot be opened safely") from exc
    try:
        components = path.parts[1:]
        for index, component in enumerate(components):
            # Intermediate descriptors only anchor the next openat. The final
            # directory keeps read capability for listing and durable fsync.
            component_flags = flags if index == len(components) - 1 else search_flags
            try:
                child = os.open(component, component_flags, dir_fd=descriptor)
            except FileNotFoundError as exc:
                if not create:
                    raise SecureFileMissing("artifact directory does not exist") from exc
                try:
                    os.mkdir(component, mode, dir_fd=descriptor)
                except FileExistsError:
                    pass
                except OSError as mkdir_exc:
                    raise SecureFileError(
                        "artifact directory could not be created safely"
                    ) from mkdir_exc
                try:
                    child = os.open(component, component_flags, dir_fd=descriptor)
                except OSError as open_exc:
                    raise SecureFileError(
                        "artifact directory chain is not symlink-free"
                    ) from open_exc
            except OSError as exc:
                raise SecureFileError("artifact directory chain is not symlink-free") from exc
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_directory_from_parent(
    parent_fd: int,
    name: str,
) -> tuple[int, os.stat_result]:
    try:
        descriptor = os.open(name, _directory_flags(), dir_fd=parent_fd)
    except FileNotFoundError as exc:
        raise SecureFileMissing("directory does not exist") from exc
    except OSError as exc:
        raise SecureFileError("directory endpoint is not a real directory without links") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise SecureFileError("directory endpoint must be a real directory")
        return descriptor, metadata
    except Exception:
        os.close(descriptor)
        raise


def _open_regular_from_parent(parent_fd: int, filename: str) -> tuple[int, os.stat_result]:
    try:
        descriptor = os.open(filename, _read_flags(), dir_fd=parent_fd)
    except FileNotFoundError as exc:
        raise SecureFileMissing("artifact does not exist") from exc
    except OSError as exc:
        raise SecureFileError("artifact could not be opened without following symlinks") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SecureFileError("artifact must be a regular file")
        return descriptor, metadata
    except Exception:
        os.close(descriptor)
        raise


def _read_from_parent(parent_fd: int, filename: str, *, max_bytes: int) -> bytes:
    descriptor, opened = _open_regular_from_parent(parent_fd, filename)
    try:
        if opened.st_size > max_bytes:
            raise SecureFileError("artifact exceeds its safe size limit")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        value = b"".join(chunks)
        if len(value) > max_bytes:
            raise SecureFileError("artifact grew beyond its safe size limit")
        _assert_stable_regular_endpoint(
            parent_fd,
            filename,
            descriptor,
            expected=_file_identity(opened),
        )
        return value
    finally:
        os.close(descriptor)


def _hash_from_parent(parent_fd: int, filename: str, *, block_size: int) -> str:
    descriptor, opened = _open_regular_from_parent(parent_fd, filename)
    try:
        digest = hashlib.sha256()
        copied = 0
        while block := os.read(descriptor, block_size):
            digest.update(block)
            copied += len(block)
        if copied != opened.st_size:
            raise SecureFileError("artifact changed size while hashing")
        _assert_stable_regular_endpoint(
            parent_fd,
            filename,
            descriptor,
            expected=_file_identity(opened),
        )
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _assert_stable_regular_endpoint(
    parent_fd: int,
    filename: str,
    descriptor: int,
    *,
    expected: _FileIdentity,
) -> None:
    try:
        opened_now = os.fstat(descriptor)
        current = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise SecureFileError("artifact changed while reading") from exc
    if (
        not stat.S_ISREG(opened_now.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or _file_identity(opened_now) != expected
        or _file_identity(current) != expected
    ):
        raise SecureFileError("artifact changed while reading")


def _assert_same_regular_binding(
    left_parent_fd: int,
    left_name: str,
    right_parent_fd: int,
    right_name: str,
) -> None:
    try:
        left = os.stat(left_name, dir_fd=left_parent_fd, follow_symlinks=False)
        right = os.stat(right_name, dir_fd=right_parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise SecureFileError("published artifact binding is unstable") from exc
    if (
        not stat.S_ISREG(left.st_mode)
        or not stat.S_ISREG(right.st_mode)
        or (left.st_dev, left.st_ino, left.st_size) != (right.st_dev, right.st_ino, right.st_size)
    ):
        raise SecureFileError("published artifact binding is unstable")


def _validate_pinned_directory_files(
    *,
    root_path: Path,
    root_fd: int,
    pinned_files: Mapping[str, PinnedFileEvidence],
    rehash: bool,
) -> None:
    expected_files: set[str] = set()
    expected_directories: set[str] = set()
    for raw_name in pinned_files:
        relative = _safe_relative_file_name(raw_name)
        canonical = relative.as_posix()
        if canonical in expected_files:
            raise SecureFileError("directory publication member is duplicated")
        expected_files.add(canonical)
        for index in range(1, len(relative.parts)):
            expected_directories.add(PurePosixPath(*relative.parts[:index]).as_posix())
    observed_files, observed_directories = _scan_regular_directory_tree(root_fd)
    if observed_files != expected_files or observed_directories != expected_directories:
        raise SecureFileError("directory contents differ from the pinned publication set")
    for name, evidence in pinned_files.items():
        relative = _safe_relative_file_name(name)
        evidence.validate_at(root_path / Path(*relative.parts), rehash=rehash)


def _scan_regular_directory_tree(
    descriptor: int,
    *,
    prefix: PurePosixPath | None = None,
) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    try:
        with os.scandir(descriptor) as iterator:
            entries = tuple(iterator)
    except OSError as exc:
        raise SecureFileError("directory publication tree could not be enumerated") from exc
    for entry in entries:
        if entry.name in {"", ".", ".."}:
            raise SecureFileError("directory publication tree contains an invalid entry")
        relative = PurePosixPath(entry.name) if prefix is None else prefix / entry.name
        try:
            metadata = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise SecureFileError("directory publication member changed during scan") from exc
        if stat.S_ISREG(metadata.st_mode):
            files.add(relative.as_posix())
            continue
        if not stat.S_ISDIR(metadata.st_mode):
            raise SecureFileError("directory publication tree contains a non-regular member")
        child_fd, child_metadata = _open_directory_from_parent(descriptor, entry.name)
        child_identity = _directory_identity(child_metadata)
        if child_identity != _directory_identity(metadata):
            os.close(child_fd)
            raise SecureFileError("directory publication child binding changed")
        try:
            child_files, child_directories = _scan_regular_directory_tree(
                child_fd,
                prefix=relative,
            )
            _assert_stable_directory_endpoint(
                descriptor,
                entry.name,
                child_fd,
                expected=child_identity,
            )
        finally:
            os.close(child_fd)
        directories.add(relative.as_posix())
        files.update(child_files)
        directories.update(child_directories)
    return files, directories


def _safe_relative_file_name(value: str) -> PurePosixPath:
    if "\\" in value or "\x00" in value:
        raise SecureFileError("directory publication member path is invalid")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != value
    ):
        raise SecureFileError("directory publication member path is invalid")
    return relative


def _publish_pinned_directory_no_replace(
    *,
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
    source_fd: int,
    expected: _DirectoryIdentity,
) -> None:
    _assert_stable_directory_endpoint(
        source_parent_fd,
        source_name,
        source_fd,
        expected=expected,
    )
    try:
        _rename_directory_no_replace(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
        )
    except FileExistsError as exc:
        raise SecureFileError("directory publication destination already exists") from exc
    try:
        _assert_stable_directory_endpoint(
            destination_parent_fd,
            destination_name,
            source_fd,
            expected=expected,
        )
        os.fsync(source_fd)
        os.fsync(source_parent_fd)
        os.fsync(destination_parent_fd)
    except (OSError, SecureFileError) as publication_error:
        try:
            _rollback_pinned_directory_after_content_failure(
                source_parent_fd=source_parent_fd,
                source_name=source_name,
                destination_parent_fd=destination_parent_fd,
                destination_name=destination_name,
                expected=expected,
            )
        except (OSError, SecureFileError) as rollback_error:
            raise SecureFileError(
                "published directory failure could not be rolled back safely"
            ) from rollback_error
        raise SecureFileError(
            "published directory does not match the pinned source or was not durable"
        ) from publication_error


def _rollback_pinned_directory_after_content_failure(
    *,
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
    expected: _DirectoryIdentity,
) -> None:
    try:
        destination_metadata = os.stat(
            destination_name,
            dir_fd=destination_parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    if stat.S_ISDIR(destination_metadata.st_mode) and (
        _directory_identity(destination_metadata) == expected
    ):
        try:
            _rename_directory_no_replace(
                destination_parent_fd,
                destination_name,
                source_parent_fd,
                source_name,
            )
        except FileExistsError:
            quarantine_name = f".{destination_name}.rejected-{uuid.uuid4().hex}"
            _rename_directory_no_replace(
                destination_parent_fd,
                destination_name,
                destination_parent_fd,
                quarantine_name,
            )
    else:
        _rollback_unexpected_directory_publication(
            source_parent_fd=source_parent_fd,
            destination_parent_fd=destination_parent_fd,
            destination_name=destination_name,
            expected=expected,
        )
    try:
        os.stat(
            destination_name,
            dir_fd=destination_parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        pass
    else:
        raise SecureFileError("invalid directory remained at the publication destination")
    os.fsync(source_parent_fd)
    os.fsync(destination_parent_fd)


def _rollback_unexpected_directory_publication(
    *,
    source_parent_fd: int,
    destination_parent_fd: int,
    destination_name: str,
    expected: _DirectoryIdentity,
) -> None:
    try:
        destination_metadata = os.stat(
            destination_name,
            dir_fd=destination_parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    if stat.S_ISDIR(destination_metadata.st_mode) and (
        _directory_identity(destination_metadata) == expected
    ):
        return
    # The destination is not the directory pinned by the caller.  Never move
    # it back to the source name: the outer failure cleanup owns only the
    # original source identity and must not delete these unrelated bytes.
    quarantine_name = f".{destination_name}.rejected-{uuid.uuid4().hex}"
    _rename_directory_no_replace(
        destination_parent_fd,
        destination_name,
        destination_parent_fd,
        quarantine_name,
    )
    try:
        os.stat(
            destination_name,
            dir_fd=destination_parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        pass
    else:
        raise SecureFileError("unexpected directory remained at the publication destination")
    os.fsync(source_parent_fd)
    os.fsync(destination_parent_fd)


def _quarantine_unexpected_regular_publication(parent_fd: int, name: str) -> None:
    """Remove an untrusted post-rename endpoint from the official destination name."""

    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    quarantine_name = f".{name}.rejected-{uuid.uuid4().hex}"
    try:
        _rename_directory_no_replace(parent_fd, name, parent_fd, quarantine_name)
        os.fsync(parent_fd)
    except OSError as exc:
        raise SecureFileError("unexpected regular publication could not be quarantined") from exc


def _withdraw_pinned_regular_publication(
    parent_fd: int,
    name: str,
    descriptor: int,
    *,
    expected: tuple[int, int],
) -> None:
    """Withdraw only the published pinned inode from an official endpoint."""

    try:
        opened = os.fstat(descriptor)
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise SecureFileError("published regular file could not be inspected") from exc
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or (opened.st_dev, opened.st_ino) != expected
        or (current.st_dev, current.st_ino) != expected
    ):
        _quarantine_unexpected_regular_publication(parent_fd, name)
        raise SecureFileError("publication endpoint changed while it was withdrawn")
    try:
        os.unlink(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except OSError as exc:
        raise SecureFileError(
            "published regular file withdrawal was not durably confirmed"
        ) from exc


def _sha256_open_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while True:
        block = os.pread(descriptor, 1024 * 1024, offset)
        if not block:
            return digest.hexdigest()
        digest.update(block)
        offset += len(block)


def _assert_stable_directory_endpoint(
    parent_fd: int,
    name: str,
    descriptor: int,
    *,
    expected: _DirectoryIdentity,
) -> None:
    try:
        opened_now = os.fstat(descriptor)
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise SecureFileError("directory binding changed during operation") from exc
    if (
        not stat.S_ISDIR(opened_now.st_mode)
        or not stat.S_ISDIR(current.st_mode)
        or _directory_identity(opened_now) != expected
        or _directory_identity(current) != expected
    ):
        raise SecureFileError("directory binding changed during operation")


def _rename_directory_no_replace(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = getattr(library, "renameatx_np", None)
        flags = 0x00000004  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        function = getattr(library, "renameat2", None)
        flags = 0x00000001  # RENAME_NOREPLACE
    else:
        function = None
        flags = 0
    if function is None:
        raise SecureFileError("atomic no-replace directory rename is unavailable")
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = function(
        source_parent_fd,
        os.fsencode(source_name),
        destination_parent_fd,
        os.fsencode(destination_name),
        flags,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(error_number, os.strerror(error_number), destination_name)
    raise OSError(error_number, os.strerror(error_number), destination_name)


def _unlink_if_same(parent_fd: int, filename: str, *, expected: _FileIdentity) -> None:
    try:
        current = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise SecureFileError("artifact source binding could not be rechecked") from exc
    if not stat.S_ISREG(current.st_mode) or _file_identity(current) != expected:
        return
    try:
        os.unlink(filename, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except OSError as exc:
        raise SecureFileError("published artifact source could not be removed safely") from exc


def _write_all(descriptor: int, value: bytes) -> None:
    view = memoryview(value)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise SecureFileError("artifact temporary write did not progress")
        view = view[written:]


def _absolute_path(path: Path) -> Path:
    raw = Path(path)
    if ".." in raw.parts:
        raise SecureFileError("artifact path must not contain parent traversal")
    value = os.fspath(raw)
    if "\x00" in value:
        raise SecureFileError("artifact path contains a null byte")
    return Path(os.path.abspath(value))


def _validate_optional_sha256(value: str | None) -> None:
    if value is not None and (
        len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("expected SHA-256 must be 64 lowercase hexadecimal characters")


def _file_identity(metadata: os.stat_result) -> _FileIdentity:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _directory_identity(metadata: os.stat_result) -> _DirectoryIdentity:
    return (metadata.st_dev, metadata.st_ino)


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _read_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def _write_create_flags() -> int:
    return (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _read_write_create_flags() -> int:
    return (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
