"""Fail closed when synthetic completion evidence contains credential material."""

from __future__ import annotations

import hashlib
import os
import re
import zipfile
from collections.abc import Collection
from pathlib import PurePosixPath

TEXT_ASSET_KINDS = frozenset(
    {
        "source_metadata",
        "audio_manifest",
        "transcript_json",
        "transcript_srt",
        "rough_candidates",
        "edit_plans",
        "clip_subtitle_srt",
        "render_quality_report",
        "delivery_manifest",
    }
)
_TEXT_ZIP_SUFFIXES = frozenset({".json", ".srt", ".html", ".sha256", ".txt", ".md", ".csv"})
_FIXTURE_CREDENTIALS = (
    "liveclip-real-browser-test-token",
    "liveclip real browser password 2026",
)
_SECRET_LABEL_OR_URL = re.compile(
    r"authorization|bearer\s+|download_url|signed_url|access_token|api_key"
    r"|\bsk-[a-z0-9]|\"lease_token\"\s*:"
    r"|[?&](?:token|signature|sig|expires|x-amz-signature|x-amz-credential"
    r"|x-amz-security-token|x-goog-signature|x-goog-credential)=",
    re.IGNORECASE,
)
_RAW_LEASE_CANDIDATE = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")


def reject_sensitive_text(raw: bytes, *, lease_token_hashes: Collection[str] = ()) -> None:
    """Inspect actual fixture values as well as labels without disclosing matches."""

    value = raw.decode("utf-8")
    if _SECRET_LABEL_OR_URL.search(value):
        raise ValueError("secret/URL in retained text")
    credentials = {*_FIXTURE_CREDENTIALS}
    credentials.update(
        secret
        for secret in (
            os.environ.get("LIVECLIP_E2E_TOKEN"),
            os.environ.get("LIVECLIP_E2E_PASSWORD"),
        )
        if secret
    )
    if any(secret in value for secret in credentials):
        raise ValueError("secret/URL in retained text")
    if lease_token_hashes and any(
        hashlib.sha256(match.group().encode()).hexdigest() in lease_token_hashes
        for match in _RAW_LEASE_CANDIDATE.finditer(value)
    ):
        raise ValueError("secret/URL in retained text")


def scan_zip_text(archive: zipfile.ZipFile, *, lease_token_hashes: Collection[str] = ()) -> None:
    """Scan every supported text member; reject other unreviewed member types."""

    for name in archive.namelist():
        suffix = PurePosixPath(name).suffix.lower()
        if suffix == ".mp4":
            continue
        if suffix not in _TEXT_ZIP_SUFFIXES:
            raise ValueError("unsupported retained ZIP member type")
        reject_sensitive_text(archive.read(name), lease_token_hashes=lease_token_hashes)
