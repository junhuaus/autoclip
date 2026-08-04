from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import SecretStr

from liveclip.api.media import (
    ByteRange,
    MediaRangeNotSatisfiable,
    parse_single_range,
    stream_asset_response,
)
from liveclip.api.security import ApiAuthenticationError, ApiSecurity
from liveclip.application.media_assets import (
    MediaAssetInvalid,
    MediaAssetNotFound,
    MediaAssetRecord,
    MediaAssetService,
)
from liveclip.config import Settings


class FakeMediaRepository:
    def __init__(self, record: MediaAssetRecord) -> None:
        self.record = record

    def get_committed_asset(self, asset_id: str) -> MediaAssetRecord:
        if asset_id != self.record.asset_id:
            raise MediaAssetNotFound("missing")
        return self.record


def test_single_range_parser_accepts_bounded_open_and_suffix_ranges() -> None:
    assert parse_single_range(None, size_bytes=100) is None
    assert parse_single_range("bytes=0-9", size_bytes=100) == ByteRange(start=0, end=9)
    assert parse_single_range("bytes=90-", size_bytes=100) == ByteRange(start=90, end=99)
    suffix = parse_single_range("bytes=-12", size_bytes=100)
    assert suffix is not None and (suffix.start, suffix.end) == (88, 99)
    clamped = parse_single_range("bytes=95-500", size_bytes=100)
    assert clamped is not None and (clamped.start, clamped.end) == (95, 99)


@pytest.mark.parametrize(
    "value",
    ["items=0-1", "bytes=", "bytes=1-0", "bytes=100-", "bytes=-0", "bytes=0-1,3-4"],
)
def test_single_range_parser_rejects_malformed_or_unsatisfiable_ranges(value: str) -> None:
    with pytest.raises(MediaRangeNotSatisfiable) as caught:
        parse_single_range(value, size_bytes=100)
    assert caught.value.size_bytes == 100


def test_media_asset_service_resolves_only_verified_allowlisted_regular_files(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "projects"
    project_id = "a" * 32
    relative_path = "runs/g001/renders/final/clip/final.mp4"
    media_path = data_dir / project_id / relative_path
    media_path.parent.mkdir(parents=True)
    payload = b"verified-media-bytes"
    media_path.write_bytes(payload)
    record = MediaAssetRecord(
        asset_id="b" * 32,
        project_id=project_id,
        kind="final_video",
        relative_path=relative_path,
        mime_type="video/mp4",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )
    service = MediaAssetService(FakeMediaRepository(record), data_dir=data_dir)

    resolved = service.resolve(record.asset_id)

    assert resolved.path == media_path.resolve()
    response = stream_asset_response(resolved, range_header="bytes=2-7")
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 2-7/{len(payload)}"
    media_path.write_bytes(b"tampered-media-bytes")
    with pytest.raises(MediaAssetInvalid, match="hash"):
        service.resolve(record.asset_id)


def test_media_asset_service_rejects_internal_kinds_and_symbolic_components(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "projects"
    project_id = "c" * 32
    target = tmp_path / "outside.mp4"
    target.write_bytes(b"outside")
    linked = data_dir / project_id / "linked.mp4"
    linked.parent.mkdir(parents=True)
    try:
        linked.symlink_to(target)
    except OSError as exc:  # pragma: no cover - platform capability guard
        pytest.skip(f"symlinks unavailable: {exc.__class__.__name__}")
    linked_record = MediaAssetRecord(
        asset_id="d" * 32,
        project_id=project_id,
        kind="review_proxy",
        relative_path="linked.mp4",
        mime_type="video/mp4",
        sha256=hashlib.sha256(b"outside").hexdigest(),
        size_bytes=7,
    )
    with pytest.raises(MediaAssetInvalid, match="symbolic"):
        MediaAssetService(FakeMediaRepository(linked_record), data_dir=data_dir).resolve(
            linked_record.asset_id
        )

    internal = MediaAssetRecord(
        asset_id="e" * 32,
        project_id=project_id,
        kind="source_metadata",
        relative_path="internal.json",
        mime_type="application/json",
        sha256="f" * 64,
        size_bytes=1,
    )
    with pytest.raises(MediaAssetNotFound, match="not available"):
        MediaAssetService(FakeMediaRepository(internal), data_dir=data_dir).resolve(
            internal.asset_id
        )


def test_media_hash_cache_cannot_hide_same_size_tamper_with_restored_mtime(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "projects"
    project_id = "1" * 32
    relative_path = "runs/g001/renders/final/clip/final.mp4"
    media_path = data_dir / project_id / relative_path
    media_path.parent.mkdir(parents=True)
    payload = b"original-media"
    media_path.write_bytes(payload)
    record = MediaAssetRecord(
        asset_id="2" * 32,
        project_id=project_id,
        kind="final_video",
        relative_path=relative_path,
        mime_type="video/mp4",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )
    service = MediaAssetService(FakeMediaRepository(record), data_dir=data_dir)
    service.resolve(record.asset_id)
    before = media_path.stat()
    media_path.write_bytes(b"tampered-media")
    os.utime(media_path, ns=(before.st_atime_ns, before.st_mtime_ns))

    with pytest.raises(MediaAssetInvalid, match="hash"):
        service.resolve(record.asset_id)


def test_range_response_pins_verified_inode_before_headers_are_returned(tmp_path: Path) -> None:
    data_dir = tmp_path / "projects"
    project_id = "3" * 32
    relative_path = "runs/g001/renders/final/clip/final.mp4"
    media_path = data_dir / project_id / relative_path
    media_path.parent.mkdir(parents=True)
    original = b"verified-original-media"
    media_path.write_bytes(original)
    record = MediaAssetRecord(
        asset_id="4" * 32,
        project_id=project_id,
        kind="final_video",
        relative_path=relative_path,
        mime_type="video/mp4",
        sha256=hashlib.sha256(original).hexdigest(),
        size_bytes=len(original),
    )
    resolved = MediaAssetService(FakeMediaRepository(record), data_dir=data_dir).resolve(
        record.asset_id
    )
    response = stream_asset_response(resolved, range_header=None)
    replacement = media_path.with_name("replacement.mp4")
    replacement.write_bytes(b"x" * len(original))
    os.replace(replacement, media_path)

    async def body() -> bytes:
        return b"".join([chunk async for chunk in response.body_iterator])

    assert asyncio.run(body()) == original
    assert response.headers["etag"] == f'"{record.sha256}"'


def test_range_response_rejects_in_place_change_before_response_creation(tmp_path: Path) -> None:
    data_dir = tmp_path / "projects"
    project_id = "5" * 32
    relative_path = "runs/g001/renders/final/clip/final.mp4"
    media_path = data_dir / project_id / relative_path
    media_path.parent.mkdir(parents=True)
    original = b"verified-original-media"
    media_path.write_bytes(original)
    record = MediaAssetRecord(
        asset_id="6" * 32,
        project_id=project_id,
        kind="final_video",
        relative_path=relative_path,
        mime_type="video/mp4",
        sha256=hashlib.sha256(original).hexdigest(),
        size_bytes=len(original),
    )
    resolved = MediaAssetService(FakeMediaRepository(record), data_dir=data_dir).resolve(
        record.asset_id
    )
    before = media_path.stat()
    media_path.write_bytes(b"x" * len(original))
    os.utime(media_path, ns=(before.st_atime_ns, before.st_mtime_ns))

    with pytest.raises(OSError, match="identity changed"):
        stream_asset_response(resolved, range_header=None)


def test_api_security_requires_token_off_loopback_and_issues_short_lived_signed_urls() -> None:
    with pytest.raises(ValueError, match="Bearer token"):
        ApiSecurity(Settings(api_host="0.0.0.0", cors_origins_raw="http://127.0.0.1:5173"))
    with pytest.raises(ValueError, match="CORS"):
        ApiSecurity(Settings(cors_origins_raw="https://example.com"))

    security = ApiSecurity(
        Settings(
            api_token=SecretStr("local-secret-token"),
            media_url_ttl_seconds=120,
            cors_origins_raw="http://127.0.0.1:5173",
        )
    )
    url = security.signed_url(
        path="/api/v1/media/asset1",
        resource="asset:asset1",
        now=1_000,
    )
    assert "local-secret-token" not in url
    query = parse_qs(urlsplit(url).query)
    expires = int(query["expires"][0])
    signature = query["signature"][0]
    security.authorize_resource(
        path="/api/v1/media/asset1",
        resource="asset:asset1",
        authorization=None,
        expires=expires,
        signature=signature,
        now=1_050,
    )
    with pytest.raises(ApiAuthenticationError):
        security.authorize_resource(
            path="/api/v1/media/asset2",
            resource="asset:asset2",
            authorization=None,
            expires=expires,
            signature=signature,
            now=1_050,
        )
    with pytest.raises(ApiAuthenticationError):
        security.authorize_resource(
            path="/api/v1/media/asset1/other",
            resource="asset:asset1",
            authorization=None,
            expires=expires,
            signature=signature,
            now=1_050,
        )
    with pytest.raises(ApiAuthenticationError):
        security.authorize_resource(
            path="/api/v1/media/asset1",
            resource="asset:asset1",
            authorization=None,
            expires=expires,
            signature=signature,
            now=expires + 1,
        )
    far_future_url = security.signed_url(
        path="/api/v1/media/asset1",
        resource="asset:asset1",
        now=5_000,
    )
    far_future_query = parse_qs(urlsplit(far_future_url).query)
    with pytest.raises(ApiAuthenticationError):
        security.authorize_resource(
            path="/api/v1/media/asset1",
            resource="asset:asset1",
            authorization=None,
            expires=int(far_future_query["expires"][0]),
            signature=far_future_query["signature"][0],
            now=1_000,
        )
    with pytest.raises(ApiAuthenticationError):
        security.authorize_resource(
            path="/api/v1/media/asset1",
            resource="asset:asset1",
            authorization=None,
            expires=expires,
            signature="0" * len(signature),
            now=1_050,
        )
    security.require_bearer("Bearer local-secret-token")
    with pytest.raises(ApiAuthenticationError):
        security.require_bearer("Bearer wrong-token")
