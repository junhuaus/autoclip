from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from liveclip.cli.app import app
from liveclip.config.settings import get_settings
from liveclip.services.demo_media import create_demo_source


@pytest.mark.integration
def test_cli_foreground_run_status_and_clips_share_persisted_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_root = tmp_path / "media"
    source_path = media_root / "source.mp4"
    data_dir = tmp_path / "projects"
    create_demo_source(output_path=source_path, duration_ms=32_000)
    settings = {
        "LIVECLIP_DATA_DIR": str(data_dir),
        "LIVECLIP_ALLOWED_MEDIA_ROOTS": str(media_root),
        "LIVECLIP_AI_PROVIDER": "mock",
        "ASR_CHUNK_SECONDS": "12",
        "ASR_CHUNK_OVERLAP_SECONDS": "2",
        "MIN_CLIP_SECONDS": "8",
        "MAX_CLIP_SECONDS": "12",
        "PREVIEW_RENDER_WIDTH": "270",
        "PREVIEW_RENDER_HEIGHT": "480",
        "FINAL_RENDER_WIDTH": "360",
        "FINAL_RENDER_HEIGHT": "640",
        "LIVECLIP_VIDEO_ENCODER": "libx264",
        "WORKER_LEASE_SECONDS": "30",
        "WORKER_HEARTBEAT_SECONDS": "5",
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    runner = CliRunner()
    try:
        run_result = runner.invoke(
            app,
            [
                "run",
                "--input",
                str(source_path.resolve()),
                "--top-n",
                "3",
                "--wait",
            ],
        )
        assert run_result.exit_code == 0, run_result.output
        assert "Pipeline status: completed" in run_result.output
        assert "Project status: pending_review" in run_result.output
        match = re.search(r"Project ID: ([a-f0-9]{32})", run_result.output)
        assert match is not None
        project_id = match.group(1)

        status_result = runner.invoke(app, ["status", project_id])
        assert status_result.exit_code == 0, status_result.output
        assert "Project status: pending_review" in status_result.output
        assert " - proxy_render: succeeded (100%)" in status_result.output

        clips_result = runner.invoke(app, ["clips", project_id])
        assert clips_result.exit_code == 0, clips_result.output
        lines = [line for line in clips_result.output.splitlines() if "pending_review" in line]
        assert len(lines) == 3
        assert "  Hook: " in clips_result.output
        assert "  Reason: " in clips_result.output
        assert "  Risk flags: " in clips_result.output
        assert "  Proxy status: succeeded" in clips_result.output
        assert re.search(r"  Captions \([1-9][0-9]*, clip-relative\):", clips_result.output)
        assert re.search(r"    01 \| 0\.000-[0-9]+\.[0-9]{3}s \| ", clips_result.output)
        assert "  Proxy path: " in clips_result.output
        assert str(data_dir.resolve()) in clips_result.output
        clip_id = lines[0].split(" | ", maxsplit=1)[0]

        review_result = runner.invoke(
            app,
            [
                "review",
                clip_id,
                "--title",
                "CLI 人工确认高光",
                "--approve",
            ],
        )
        assert review_result.exit_code == 0, review_result.output
        assert "EditPlan revision: 2" in review_result.output
        assert "Review status: approved" in review_result.output
        assert "Hook: " in review_result.output
        assert "Captions (" in review_result.output
        assert "clip-relative" in review_result.output

        render_result = runner.invoke(app, ["rerender", clip_id, "--wait"])
        assert render_result.exit_code == 0, render_result.output
        assert "Render status: succeeded" in render_result.output

        delivery_result = runner.invoke(app, ["deliver", project_id, "--zip"])
        assert delivery_result.exit_code == 0, delivery_result.output
        assert "Delivery version: v001" in delivery_result.output
        assert "Delivery status: succeeded" in delivery_result.output
        assert (data_dir / project_id / "deliveries" / "v001" / "delivery.zip").is_file()

        delivered_status = runner.invoke(app, ["status", project_id])
        assert delivered_status.exit_code == 0, delivered_status.output
        assert "Project status: delivered" in delivered_status.output
        assert (data_dir / "liveclip.sqlite3").is_file()
    finally:
        get_settings.cache_clear()


@pytest.mark.integration
def test_cli_worker_once_exits_successfully_when_queue_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVECLIP_DATA_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["worker", "--once"])

        assert result.exit_code == 0, result.output
        assert "LiveClip worker started:" in result.output
        assert "operation failed" not in result.output
        assert (tmp_path / "projects" / "liveclip.sqlite3").is_file()
    finally:
        get_settings.cache_clear()
