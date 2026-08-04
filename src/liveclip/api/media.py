from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi.responses import StreamingResponse

from liveclip.application.media_assets import ResolvedMediaAsset


class MediaRangeNotSatisfiable(ValueError):
    def __init__(self, size_bytes: int) -> None:
        super().__init__("requested byte range is not satisfiable")
        self.size_bytes = size_bytes


@dataclass(frozen=True, slots=True)
class ByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def parse_single_range(value: str | None, *, size_bytes: int) -> ByteRange | None:
    if value is None:
        return None
    if size_bytes <= 0 or not value.startswith("bytes=") or "," in value:
        raise MediaRangeNotSatisfiable(size_bytes)
    raw = value[6:]
    match = re.fullmatch(r"([0-9]*)-([0-9]*)", raw)
    if match is None or (not match.group(1) and not match.group(2)):
        raise MediaRangeNotSatisfiable(size_bytes)
    if match.group(1):
        start = int(match.group(1))
        if start >= size_bytes:
            raise MediaRangeNotSatisfiable(size_bytes)
        requested_end = int(match.group(2)) if match.group(2) else size_bytes - 1
        if requested_end < start:
            raise MediaRangeNotSatisfiable(size_bytes)
        return ByteRange(start=start, end=min(requested_end, size_bytes - 1))
    suffix_length = int(match.group(2))
    if suffix_length <= 0:
        raise MediaRangeNotSatisfiable(size_bytes)
    length = min(suffix_length, size_bytes)
    return ByteRange(start=size_bytes - length, end=size_bytes - 1)


def stream_asset_response(
    asset: ResolvedMediaAsset,
    *,
    range_header: str | None,
    download_filename: str | None = None,
) -> StreamingResponse:
    selected = parse_single_range(range_header, size_bytes=asset.size_bytes)
    start = selected.start if selected is not None else 0
    length = selected.length if selected is not None else asset.size_bytes
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "ETag": f'"{asset.sha256}"',
        "Cache-Control": "private, no-cache",
        "X-Content-Type-Options": "nosniff",
    }
    if selected is not None:
        headers["Content-Range"] = f"bytes {selected.start}-{selected.end}/{asset.size_bytes}"
    if download_filename is not None:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "-", download_filename)[:160]
        headers["Content-Disposition"] = f'attachment; filename="{safe_name or "download.bin"}"'
    descriptor = _open_verified_asset_descriptor(asset)
    return StreamingResponse(
        _read_file_range(descriptor, asset=asset, start=start, length=length),
        status_code=206 if selected is not None else 200,
        media_type=asset.mime_type,
        headers=headers,
    )


def _read_file_range(
    descriptor: int,
    asset: ResolvedMediaAsset,
    *,
    start: int,
    length: int,
    chunk_size: int = 1024 * 1024,
) -> Iterator[bytes]:
    remaining = length
    try:
        with os.fdopen(descriptor, "rb", closefd=True) as source:
            descriptor = -1
            source.seek(start)
            while remaining > 0:
                block = source.read(min(chunk_size, remaining))
                if not block:
                    raise OSError("asset ended before its committed size")
                remaining -= len(block)
                yield block
            if not _descriptor_content_remained_stable(source.fileno(), asset.stat_identity):
                raise OSError("asset changed while it was being streamed")
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _open_verified_asset_descriptor(asset: ResolvedMediaAsset) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(asset.path, flags)
    try:
        if _descriptor_identity(descriptor) != asset.stat_identity:
            raise OSError("asset identity changed after integrity verification")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _descriptor_identity(descriptor: int) -> tuple[int, int, int, int | None, int | None]:
    metadata = os.fstat(descriptor)
    return (
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        getattr(metadata, "st_dev", None),
        getattr(metadata, "st_ino", None),
    )


def _descriptor_content_remained_stable(
    descriptor: int,
    expected: tuple[int, int, int, int | None, int | None],
) -> bool:
    metadata = os.fstat(descriptor)
    stable_content_identity = (
        metadata.st_size,
        metadata.st_mtime_ns,
        getattr(metadata, "st_dev", None),
        getattr(metadata, "st_ino", None),
    )
    expected_content_identity = (expected[0], expected[1], expected[3], expected[4])
    if stable_content_identity != expected_content_identity:
        return False
    # Replacing the pathname can change ctime on the already-open old inode while
    # reducing its link count to zero; its pinned bytes remain the verified body.
    return metadata.st_ctime_ns == expected[2] or metadata.st_nlink == 0
