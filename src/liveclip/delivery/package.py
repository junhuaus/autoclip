from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from collections.abc import Iterable, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.media.fingerprint import stream_sha256


class DeliveryError(RuntimeError):
    pass


class DeliveryClipInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    edit_plan_revision: int = Field(ge=1)
    render_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=40)
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    score: float = Field(ge=0, le=100)
    review_status: str = Field(pattern=r"^(pending_review|approved|rejected)$")
    render_status: str = Field(pattern=r"^(queued|running|succeeded|failed|stale)$")
    final_video_path: Path
    subtitle_srt: str = Field(min_length=1, max_length=1_000_000)

    @model_validator(mode="after")
    def validate_interval(self) -> DeliveryClipInput:
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("delivery clip end must be greater than start")
        return self


class DeliveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    delivery_id: str
    delivery_version: str
    directory: Path
    manifest_path: Path
    zip_path: Path | None
    clip_count: int = Field(gt=0)


def create_delivery(
    *,
    project_dir: Path,
    project_id: str,
    source_filename: str,
    source_fingerprint: str,
    clips: Sequence[DeliveryClipInput],
    include_zip: bool,
    expected_version: int | None = None,
    delivery_id: str | None = None,
    snapshot_fingerprint: str | None = None,
    created_at: datetime | None = None,
) -> DeliveryResult:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", project_id):
        raise DeliveryError("project ID is invalid")
    if not re.fullmatch(r"[a-fA-F0-9]{64}", source_fingerprint):
        raise DeliveryError("source fingerprint must be SHA-256")
    if expected_version is not None and not 1 <= expected_version <= 999:
        raise DeliveryError("delivery version must be between 1 and 999")
    if delivery_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", delivery_id):
        raise DeliveryError("delivery ID is invalid")
    if snapshot_fingerprint is not None and not re.fullmatch(r"[a-f0-9]{64}", snapshot_fingerprint):
        raise DeliveryError("delivery snapshot fingerprint is invalid")
    approved = tuple(clip for clip in clips if clip.review_status == "approved")
    if not approved:
        raise DeliveryError("delivery requires at least one approved clip")
    _validate_eligible_clips(approved)

    resolved_project = project_dir.resolve(strict=False)
    deliveries_dir = resolved_project / "deliveries"
    deliveries_dir.mkdir(parents=True, exist_ok=True)
    lock_path = deliveries_dir / ".delivery.lock"
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        version_number = expected_version or _next_delivery_version(deliveries_dir)
        version = f"v{version_number:03d}"
        destination = deliveries_dir / version
        if destination.exists():
            raise DeliveryError("delivery version already exists")
        temporary = Path(tempfile.mkdtemp(prefix=f".{version}-attempt-", dir=deliveries_dir))
        try:
            result = _build_delivery(
                temporary=temporary,
                destination=destination,
                delivery_id=delivery_id or f"{project_id}_{version}",
                project_id=project_id,
                version=version,
                source_filename=source_filename,
                source_fingerprint=source_fingerprint.lower(),
                snapshot_fingerprint=snapshot_fingerprint,
                clips=approved,
                include_zip=include_zip,
                created_at=created_at or datetime.now(UTC),
            )
            if destination.exists():
                raise DeliveryError("delivery version publication lost its reservation")
            os.rename(temporary, destination)
        except Exception:
            with suppress(OSError):
                shutil.rmtree(temporary)
            raise
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    return result.model_copy(
        update={
            "directory": destination,
            "manifest_path": destination / "manifest.json",
            "zip_path": destination / "delivery.zip" if include_zip else None,
        }
    )


def _build_delivery(
    *,
    temporary: Path,
    destination: Path,
    delivery_id: str,
    project_id: str,
    version: str,
    source_filename: str,
    source_fingerprint: str,
    snapshot_fingerprint: str | None,
    clips: Sequence[DeliveryClipInput],
    include_zip: bool,
    created_at: datetime,
) -> DeliveryResult:
    clips_dir = temporary / "clips"
    subtitles_dir = temporary / "subtitles"
    clips_dir.mkdir()
    subtitles_dir.mkdir()
    manifest_clips: list[dict[str, object]] = []
    archive_members: list[PurePosixPath] = []
    for index, clip in enumerate(clips, start=1):
        stem = f"{index:02d}-{safe_filename_component(clip.title)}"
        video_relative = PurePosixPath("clips") / f"{stem}.mp4"
        subtitle_relative = PurePosixPath("subtitles") / f"{stem}.srt"
        video_target = temporary / Path(*video_relative.parts)
        subtitle_target = temporary / Path(*subtitle_relative.parts)
        _copy_no_clobber(clip.final_video_path.resolve(strict=True), video_target)
        subtitle_target.write_text(normalize_srt(clip.subtitle_srt), encoding="utf-8")
        video_hash = stream_sha256(video_target)
        manifest_clips.append(
            {
                "clip_id": clip.clip_id,
                "edit_plan_revision": clip.edit_plan_revision,
                "title": clip.title,
                "video_filename": video_relative.as_posix(),
                "subtitle_filename": subtitle_relative.as_posix(),
                "source_start": round(clip.source_start_ms / 1_000, 3),
                "source_end": round(clip.source_end_ms / 1_000, 3),
                "duration": round((clip.source_end_ms - clip.source_start_ms) / 1_000, 3),
                "score": clip.score,
                "review_status": clip.review_status,
                "sha256": video_hash,
            }
        )
        archive_members.extend((video_relative, subtitle_relative))

    manifest: dict[str, object] = {
        "schema_version": "1",
        "project_id": project_id,
        "delivery_id": delivery_id,
        "delivery_version": version,
        "created_at": created_at.astimezone(UTC).isoformat(),
        "source_filename": _source_basename(source_filename),
        "source_fingerprint": source_fingerprint,
        "clips": manifest_clips,
    }
    if snapshot_fingerprint is not None:
        manifest["snapshot_fingerprint"] = snapshot_fingerprint
    manifest_path = temporary / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    archive_members.append(PurePosixPath("manifest.json"))
    zip_path: Path | None = None
    if include_zip:
        zip_path = temporary / "delivery.zip"
        _create_and_verify_zip(
            root=temporary,
            output_path=zip_path,
            members=tuple(archive_members),
            manifest=manifest,
        )
    return DeliveryResult(
        delivery_id=delivery_id,
        delivery_version=version,
        directory=destination,
        manifest_path=destination / "manifest.json",
        zip_path=destination / "delivery.zip" if include_zip else None,
        clip_count=len(clips),
    )


def safe_filename_component(value: str, *, maximum_utf8_bytes: int = 72) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    characters: list[str] = []
    previous_dash = False
    for character in normalized:
        category = unicodedata.category(character)
        if character.isspace() or character in {"_", "-"}:
            if characters and not previous_dash:
                characters.append("-")
                previous_dash = True
            continue
        if category[0] in {"L", "M", "N"}:
            characters.append(character)
            previous_dash = False
    candidate = "".join(characters).strip("-.") or "clip"
    bounded: list[str] = []
    byte_count = 0
    for character in candidate:
        encoded_size = len(character.encode("utf-8"))
        if byte_count + encoded_size > maximum_utf8_bytes:
            break
        bounded.append(character)
        byte_count += encoded_size
    return "".join(bounded).rstrip("-.") or "clip"


def validate_zip_members(names: Iterable[str]) -> tuple[str, ...]:
    checked: list[str] = []
    seen: set[str] = set()
    for name in names:
        if "\\" in name:
            raise DeliveryError("ZIP member uses a backslash")
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise DeliveryError("ZIP member is not a safe relative path")
        canonical = path.as_posix()
        if canonical != name or canonical in seen:
            raise DeliveryError("ZIP member is non-canonical or duplicated")
        seen.add(canonical)
        checked.append(canonical)
    return tuple(checked)


def _validate_eligible_clips(clips: Sequence[DeliveryClipInput]) -> None:
    identifiers: set[str] = set()
    for clip in clips:
        if clip.clip_id in identifiers:
            raise DeliveryError("delivery clip IDs must be unique")
        identifiers.add(clip.clip_id)
        if clip.render_revision != clip.edit_plan_revision:
            raise DeliveryError("approved clip has a stale final render")
        if clip.render_status != "succeeded":
            raise DeliveryError("approved clip final render is not succeeded")
        if not clip.final_video_path.is_file() or clip.final_video_path.stat().st_size == 0:
            raise DeliveryError("approved clip final render is missing")


def _next_delivery_version(deliveries_dir: Path) -> int:
    existing = [
        int(match.group(1))
        for child in deliveries_dir.iterdir()
        if child.is_dir() and (match := re.fullmatch(r"v(\d{3})", child.name))
    ]
    value = max(existing, default=0) + 1
    if value > 999:
        raise DeliveryError("delivery version space is exhausted")
    return value


def _copy_no_clobber(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise DeliveryError("delivery source video is missing")
    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
    except (FileExistsError, OSError) as exc:
        raise DeliveryError("delivery video could not be copied safely") from exc


def normalize_srt(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if "\x00" in normalized or "-->" not in normalized:
        raise DeliveryError("subtitle content is not a valid bounded SRT payload")
    return normalized + "\n"


def _source_basename(value: str) -> str:
    normalized = value.replace("\\", "/")
    name = PurePosixPath(normalized).name
    return name or "source-media"


def _create_and_verify_zip(
    *,
    root: Path,
    output_path: Path,
    members: tuple[PurePosixPath, ...],
    manifest: dict[str, object],
) -> None:
    names = validate_zip_members(member.as_posix() for member in members)
    with zipfile.ZipFile(
        output_path,
        mode="x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for name in names:
            archive.write(root / Path(*PurePosixPath(name).parts), arcname=name)
    with zipfile.ZipFile(output_path, mode="r") as archive:
        actual_names = validate_zip_members(info.filename for info in archive.infolist())
        if actual_names != names:
            raise DeliveryError("ZIP member list changed during creation")
        archived_manifest = json.loads(archive.read("manifest.json"))
        if archived_manifest != manifest:
            raise DeliveryError("ZIP manifest differs from the verified manifest")
        raw_clips = manifest.get("clips")
        if not isinstance(raw_clips, list):
            raise DeliveryError("manifest clips payload is invalid")
        for clip in raw_clips:
            if not isinstance(clip, dict):
                raise DeliveryError("manifest clip entry is invalid")
            filename = clip.get("video_filename")
            expected_hash = clip.get("sha256")
            if not isinstance(filename, str) or not isinstance(expected_hash, str):
                raise DeliveryError("manifest clip hash entry is invalid")
            if hashlib.sha256(archive.read(filename)).hexdigest() != expected_hash:
                raise DeliveryError("ZIP clip hash does not match manifest")
