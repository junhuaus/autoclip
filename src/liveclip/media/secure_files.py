from __future__ import annotations

import os
import stat
import uuid
from contextlib import suppress
from pathlib import Path


class SecureFileError(ValueError):
    """A local artifact could not be handled as one stable regular file."""


class SecureFileMissing(SecureFileError):
    """The requested file or one of its directories does not exist."""


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


def write_text_immutable_no_follow(path: Path, value: str, *, max_bytes: int) -> None:
    """Publish UTF-8 bytes once within a symlink-free directory chain."""

    payload = value.encode("utf-8")
    if len(payload) > max_bytes:
        raise SecureFileError("artifact exceeds its safe size limit")
    parent_fd, filename = _open_parent(path, create=True)
    temporary_name = f".{filename}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=parent_fd)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise SecureFileError("artifact temporary write did not progress")
            view = view[written:]
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
            if existing != payload:
                raise SecureFileError("immutable artifact conflicts with existing bytes") from None
        os.fsync(parent_fd)
    except OSError as exc:
        raise SecureFileError("immutable artifact could not be published safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        finally:
            os.close(parent_fd)


def _open_parent(path: Path, *, create: bool) -> tuple[int, str]:
    target = Path(os.path.abspath(path))
    if target.name in {"", ".", ".."}:
        raise SecureFileError("artifact path has no safe filename")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target.anchor, flags)
    try:
        for component in target.parts[1:-1]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError as exc:
                if not create:
                    raise SecureFileMissing("artifact directory does not exist") from exc
                with suppress(FileExistsError):
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                child = os.open(component, flags, dir_fd=descriptor)
            except OSError as exc:
                raise SecureFileError("artifact directory chain is not symlink-free") from exc
            os.close(descriptor)
            descriptor = child
        return descriptor, target.name
    except Exception:
        os.close(descriptor)
        raise


def _read_from_parent(parent_fd: int, filename: str, *, max_bytes: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(filename, flags, dir_fd=parent_fd)
    except FileNotFoundError as exc:
        raise SecureFileMissing("artifact does not exist") from exc
    except OSError as exc:
        raise SecureFileError("artifact could not be opened without following symlinks") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise SecureFileError("artifact must be a regular file")
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
        closed = os.fstat(descriptor)
        current = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        expected = (opened.st_dev, opened.st_ino, opened.st_size)
        if (closed.st_dev, closed.st_ino, closed.st_size) != expected or (
            current.st_dev,
            current.st_ino,
            current.st_size,
        ) != expected:
            raise SecureFileError("artifact changed while reading")
        return value
    finally:
        os.close(descriptor)
