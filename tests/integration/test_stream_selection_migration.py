from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError

from liveclip.db.models import SourceMediaRow
from liveclip.media.models import AudioChunkManifest, SourceMediaMetadata

PREVIOUS_REVISION = "f3d2a9b817c4"
STREAM_SELECTION_REVISION = "a71d4f9c2e10"


def _alembic_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, Path]:
    project_root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "legacy-stream-selection.sqlite3"
    monkeypatch.setenv("LIVECLIP_DATABASE_PATH", str(database_path))
    return Config(str(project_root / "alembic.ini")), database_path


def _insert_legacy_source(database_path: Path) -> dict[str, object]:
    instant = "2026-08-03T00:00:00+00:00"
    project_id = "p" * 32
    old_probe_payload: dict[str, object] = {
        "schema_version": "1",
        "resolved_path": "/allowed/nonstandard-layout.mkv",
        "filename": "nonstandard-layout.mkv",
        "size_bytes": 987_654,
        "sha256": "a" * 64,
        "duration_ms": 123_456,
        "format_name": "matroska,webm",
        "video_codec": "hevc",
        "video_width": 720,
        "video_height": 1280,
        "video_frame_rate": 29.97,
        "audio_codec": "flac",
        "audio_sample_rate_hz": 96_000,
        "audio_channels": 6,
        "mtime_ns": 123_000_000,
        "inode": 44,
        "device": 55,
    }
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO projects (
                id, name, source_request_path, current_generation,
                current_pipeline_run_id, revision_epoch, created_at, updated_at
            ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                project_id,
                "legacy nonstandard layout",
                "/allowed/nonstandard-layout.mkv",
                0,
                0,
                instant,
                instant,
            ),
        )
        connection.execute(
            """
            INSERT INTO source_media (
                id, project_id, resolved_path, filename, sha256, size_bytes,
                mtime_ns, device, inode, duration_ms, width, height,
                video_codec, audio_codec, frame_rate, probe_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s" * 32,
                project_id,
                "/allowed/nonstandard-layout.mkv",
                "nonstandard-layout.mkv",
                "a" * 64,
                987_654,
                123_000_000,
                55,
                44,
                123_456,
                720,
                1280,
                "hevc",
                "flac",
                "30000/1001",
                json.dumps(old_probe_payload),
                instant,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return old_probe_payload


@pytest.mark.integration
def test_legacy_stream_selection_remains_unverified_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, database_path = _alembic_config(tmp_path, monkeypatch)
    command.upgrade(config, PREVIOUS_REVISION)
    old_probe_payload = _insert_legacy_source(database_path)

    command.upgrade(config, STREAM_SELECTION_REVISION)

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            """
            SELECT video_stream_index, audio_stream_index, video_rotation_degrees
            FROM source_media
            """
        ).fetchone() == (None, None, None)
        stored_probe = connection.execute("SELECT probe_json FROM source_media").fetchone()
        assert stored_probe is not None
        assert json.loads(stored_probe[0]) == old_probe_payload

        columns = {row[1]: row for row in connection.execute("PRAGMA table_info(source_media)")}
        for column_name in (
            "video_stream_index",
            "audio_stream_index",
            "video_rotation_degrees",
        ):
            assert columns[column_name][3] == 0
            assert columns[column_name][4] is None

        connection.execute(
            """
            UPDATE source_media
            SET video_stream_index = 4,
                audio_stream_index = 7,
                video_rotation_degrees = 270
            """
        )
        connection.commit()
        assert connection.execute(
            """
            SELECT video_stream_index, audio_stream_index, video_rotation_degrees
            FROM source_media
            """
        ).fetchone() == (4, 7, 270)

        invalid_selections = (
            (None, 7, None),
            (-1, 7, 0),
            (4, 4, 0),
            (4, 7, 45),
        )
        for selection in invalid_selections:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    UPDATE source_media
                    SET video_stream_index = ?,
                        audio_stream_index = ?,
                        video_rotation_degrees = ?
                    """,
                    selection,
                )
            connection.rollback()
    finally:
        connection.close()

    command.downgrade(config, PREVIOUS_REVISION)

    connection = sqlite3.connect(database_path)
    try:
        column_names = {row[1] for row in connection.execute("PRAGMA table_info(source_media)")}
        assert "video_stream_index" not in column_names
        assert "audio_stream_index" not in column_names
        assert "video_rotation_degrees" not in column_names
        stored_probe = connection.execute("SELECT probe_json FROM source_media").fetchone()
        assert stored_probe is not None
        assert json.loads(stored_probe[0]) == old_probe_payload
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()

    command.upgrade(config, STREAM_SELECTION_REVISION)
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            """
            SELECT video_stream_index, audio_stream_index, video_rotation_degrees
            FROM source_media
            """
        ).fetchone() == (None, None, None)
    finally:
        connection.close()


def test_current_models_require_explicit_verified_stream_selection() -> None:
    source_payload = {
        "resolved_path": "/allowed/source.mp4",
        "filename": "source.mp4",
        "size_bytes": 1_000,
        "sha256": "a" * 64,
        "duration_ms": 10_000,
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "video_codec": "h264",
        "video_width": 1920,
        "video_height": 1080,
        "video_frame_rate": 30.0,
        "audio_codec": "aac",
        "audio_sample_rate_hz": 48_000,
        "audio_channels": 2,
        "mtime_ns": 1,
    }
    with pytest.raises(ValidationError) as source_error:
        SourceMediaMetadata.model_validate(source_payload)
    assert {error["loc"] for error in source_error.value.errors()} >= {
        ("video_stream_index",),
        ("audio_stream_index",),
        ("video_rotation_degrees",),
    }

    manifest_payload = {
        "source_sha256": "a" * 64,
        "source_duration_ms": 10_000,
        "chunk_duration_ms": 10_000,
        "chunk_overlap_ms": 0,
        "sample_rate_hz": 16_000,
        "bitrate": "64k",
        "silence_noise_db": -35,
        "silence_min_duration_ms": 500,
        "max_chunk_bytes": 20_000_000,
        "expected_chunk_count": 1,
    }
    with pytest.raises(ValidationError) as manifest_error:
        AudioChunkManifest.model_validate(manifest_payload)
    assert ("source_audio_stream_index",) in {
        error["loc"] for error in manifest_error.value.errors()
    }

    for column_name in (
        "video_stream_index",
        "audio_stream_index",
        "video_rotation_degrees",
    ):
        column = SourceMediaRow.__table__.c[column_name]
        assert column.nullable is True
        assert column.default is None
        assert column.server_default is None
