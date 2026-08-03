import json
import zipfile
from pathlib import Path

import pytest

from liveclip.config.settings import Settings
from liveclip.renderer.quality import full_decode, probe_media
from liveclip.services.demo import run_demo


@pytest.mark.integration
def test_real_mock_demo_reaches_delivered_with_current_revision_media(tmp_path: Path) -> None:
    settings = Settings(video_encoder="libx264", _env_file=None)

    result = run_demo(project_root=tmp_path, settings=settings)

    assert result.project_status == "delivered"
    assert result.candidate_count == 3
    assert result.final_video.is_file()
    assert result.contact_sheet.is_file()
    assert result.delivery_zip.is_file()

    state = json.loads(result.state_path.read_text(encoding="utf-8"))
    selected = state["clips"][0]
    assert state["project_status"] == "delivered"
    assert selected["current_revision"] == 2
    assert [revision["origin"] for revision in selected["revisions"]] == ["ai", "human"]
    assert [render["status"] for render in selected["renders"]] == ["stale", "succeeded"]
    assert [decision["revision"] for decision in selected["decisions"]] == [1, 2]

    probe = probe_media(result.final_video)
    streams = probe["streams"]
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    audio = next(stream for stream in streams if stream["codec_type"] == "audio")
    assert (video["codec_name"], video["width"], video["height"]) == ("h264", 1080, 1920)
    assert audio["codec_name"] == "aac"
    full_decode(result.final_video)

    manifest = json.loads((result.delivery_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["delivery_version"] == "v001"
    assert manifest["clips"][0]["edit_plan_revision"] == 2
    with zipfile.ZipFile(result.delivery_zip) as archive:
        names = archive.namelist()
        assert names[-1] == "manifest.json"
        assert len(names) == 3
        subtitle_name = manifest["clips"][0]["subtitle_filename"]
        subtitle = archive.read(subtitle_name).decode("utf-8")
    assert "00:00:00,000 -->" in subtitle

    quality = json.loads(result.quality_report.read_text(encoding="utf-8"))
    assert quality["automatic_status"] == "passed"
    assert quality["video_codec"] == "h264"
    assert quality["audio_codec"] == "aac"
