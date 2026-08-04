from __future__ import annotations

import re
import stat
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from liveclip.media.fingerprint import stream_sha256


class MediaAssetNotFound(LookupError):
    """The requested public asset does not exist or is not publishable."""


class MediaAssetInvalid(RuntimeError):
    """A persisted asset no longer satisfies its local integrity contract."""


@dataclass(frozen=True, slots=True)
class MediaAssetRecord:
    asset_id: str
    project_id: str
    kind: str
    relative_path: str
    mime_type: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ResolvedMediaAsset:
    asset_id: str
    project_id: str
    kind: str
    path: Path
    filename: str
    mime_type: str
    sha256: str
    size_bytes: int
    stat_identity: tuple[int, int, int | None, int | None]


class MediaAssetRepository(Protocol):
    def get_committed_asset(self, asset_id: str) -> MediaAssetRecord: ...


_PUBLIC_ASSET_KINDS = frozenset(
    {
        "review_proxy",
        "final_video",
        "render_contact_sheet",
        "clip_subtitle_srt",
    }
)
_SCOPED_ASSET_KINDS = frozenset({"delivery_zip"})


class MediaAssetService:
    def __init__(self, repository: MediaAssetRepository, *, data_dir: Path) -> None:
        self._repository = repository
        self._data_dir = data_dir.resolve(strict=True)
        self._verified: dict[str, tuple[tuple[int, int, int | None, int | None], str]] = {}
        self._cache_lock = threading.Lock()

    def resolve(self, asset_id: str, *, required_kind: str | None = None) -> ResolvedMediaAsset:
        record = self._repository.get_committed_asset(asset_id)
        if required_kind is None:
            if record.kind not in _PUBLIC_ASSET_KINDS:
                raise MediaAssetNotFound("asset is not available through the media interface")
        elif (
            required_kind not in _PUBLIC_ASSET_KINDS | _SCOPED_ASSET_KINDS
            or record.kind != required_kind
        ):
            raise MediaAssetNotFound("asset does not match the requested media resource")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", record.project_id):
            raise MediaAssetInvalid("asset project identity is invalid")
        relative = _safe_relative_path(record.relative_path)
        project_dir = self._data_dir / record.project_id
        candidate = project_dir.joinpath(*relative.parts)
        _reject_symbolic_components(self._data_dir, (record.project_id, *relative.parts))
        try:
            resolved = candidate.resolve(strict=True)
            metadata = resolved.stat()
        except (OSError, RuntimeError) as exc:
            raise MediaAssetInvalid("asset file is missing or cannot be inspected") from exc
        if self._data_dir not in resolved.parents or not stat.S_ISREG(metadata.st_mode):
            raise MediaAssetInvalid("asset file escaped its project directory")
        if metadata.st_size != record.size_bytes or record.size_bytes <= 0:
            raise MediaAssetInvalid("asset file size differs from committed metadata")
        identity = (
            metadata.st_size,
            metadata.st_mtime_ns,
            getattr(metadata, "st_dev", None),
            getattr(metadata, "st_ino", None),
        )
        with self._cache_lock:
            cached = self._verified.get(record.asset_id)
        if cached != (identity, record.sha256):
            try:
                observed_sha256 = stream_sha256(resolved)
            except OSError as exc:
                raise MediaAssetInvalid("asset file could not be verified") from exc
            if observed_sha256 != record.sha256:
                raise MediaAssetInvalid("asset file hash differs from committed metadata")
            with self._cache_lock:
                self._verified[record.asset_id] = (identity, record.sha256)
        return ResolvedMediaAsset(
            asset_id=record.asset_id,
            project_id=record.project_id,
            kind=record.kind,
            path=resolved,
            filename=resolved.name,
            mime_type=record.mime_type,
            sha256=record.sha256,
            size_bytes=record.size_bytes,
            stat_identity=identity,
        )


def _safe_relative_path(value: str) -> PurePosixPath:
    if not value or "\\" in value:
        raise MediaAssetInvalid("asset path is invalid")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise MediaAssetInvalid("asset path is invalid")
    return relative


def _reject_symbolic_components(root: Path, parts: tuple[str, ...]) -> None:
    current = root
    for part in parts:
        current = current / part
        try:
            if current.is_symlink():
                raise MediaAssetInvalid("asset path contains a symbolic link")
        except OSError as exc:
            raise MediaAssetInvalid("asset path cannot be inspected") from exc
