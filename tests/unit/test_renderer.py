import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

import liveclip.renderer.ffmpeg as renderer_module
from liveclip.domain.edit_plan import Effect, Layout
from liveclip.renderer.ffmpeg import (
    FFmpegRenderError,
    RenderRequest,
    _publish_no_clobber,
    build_ffmpeg_argv,
    build_filtergraph,
    render_clip,
)
from liveclip.renderer.quality import MediaValidationError
from liveclip.renderer.text import TextOverlay


def make_request(tmp_path: Path) -> RenderRequest:
    overlay = TextOverlay(
        path=tmp_path / "safe-generated.png",
        start_ms=0,
        end_ms=3_000,
        safe_bounds=(20, 40, 500, 140),
        kind="title",
    )
    return RenderRequest(
        source_path=tmp_path / "source.mp4",
        output_path=tmp_path / "output.mp4",
        source_start_ms=1_000,
        source_end_ms=4_000,
        width=540,
        height=960,
        layout=Layout.VERTICAL_BLUR_BACKGROUND,
        effect=Effect.FADE_IN_OUT,
        overlays=(overlay,),
    )


def test_ffmpeg_argv_is_an_argument_array_with_fixed_mapping(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    argv = build_ffmpeg_argv(
        request,
        encoder="libx264",
        temporary_output=tmp_path / "temporary.mp4",
    )

    assert argv[0] == "ffmpeg"
    assert "-filter_complex" in argv
    assert "libx264" in argv
    assert request.source_path.as_posix() in argv
    assert request.overlays[0].path.as_posix() in argv
    assert not any("LiveClip title" in argument for argument in argv)


def test_filtergraph_contains_only_numeric_windows_and_fixed_templates(tmp_path: Path) -> None:
    graph = build_filtergraph(make_request(tmp_path))
    assert "vertical_blur_background" not in graph
    assert "between(t,0.000,3.000)" in graph
    assert "boxblur" in graph
    assert "loudnorm" in graph


def test_renderer_refuses_to_overwrite_existing_revision_artifact(tmp_path: Path) -> None:
    request = make_request(tmp_path)
    request.output_path.write_bytes(b"existing successful artifact")

    with pytest.raises(FFmpegRenderError, match="refusing to overwrite"):
        render_clip(request)


def test_videotoolbox_runtime_exception_falls_back_to_libx264(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = make_request(tmp_path)
    attempted_encoders: list[str] = []

    def fake_run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        encoder = argv[argv.index("-c:v") + 1]
        attempted_encoders.append(encoder)
        if encoder == "h264_videotoolbox":
            raise subprocess.TimeoutExpired(argv, timeout=1)
        Path(argv[-1]).write_bytes(b"validated-render" * 1_000)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(renderer_module, "run_ffmpeg", fake_run)
    monkeypatch.setattr(renderer_module, "_validate_temporary_media", lambda *_: None)

    result = render_clip(request, ffmpeg_path="/deterministic/fake-ffmpeg")

    assert result.encoder == "libx264"
    assert result.attempts == 2
    assert attempted_encoders == ["h264_videotoolbox", "libx264"]
    assert request.output_path.read_bytes().startswith(b"validated-render")


def test_invalid_temporary_render_is_never_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = replace(make_request(tmp_path), encoder="libx264")

    def fake_run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        Path(argv[-1]).write_bytes(b"invalid-render" * 1_000)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def reject_validation(*_: object) -> None:
        raise MediaValidationError("invalid temporary media")

    monkeypatch.setattr(renderer_module, "run_ffmpeg", fake_run)
    monkeypatch.setattr(renderer_module, "_validate_temporary_media", reject_validation)

    with pytest.raises(FFmpegRenderError, match="rendering failed"):
        render_clip(request, ffmpeg_path="/deterministic/fake-ffmpeg")

    assert not request.output_path.exists()


def test_atomic_publication_losing_race_does_not_clobber_winner(tmp_path: Path) -> None:
    private_temporary = tmp_path / ".private-render.mp4"
    published = tmp_path / "revision.mp4"
    private_temporary.write_bytes(b"losing-render")
    published.write_bytes(b"winning-render")

    with pytest.raises(FFmpegRenderError, match="no-clobber race"):
        _publish_no_clobber(private_temporary, published)

    assert published.read_bytes() == b"winning-render"
    assert private_temporary.read_bytes() == b"losing-render"
