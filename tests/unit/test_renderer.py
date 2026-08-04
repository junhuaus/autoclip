import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import liveclip.renderer.ffmpeg as renderer_module
import liveclip.renderer.task_handler as render_task_handler
from liveclip.domain.edit_plan import Effect, Layout
from liveclip.media.artifacts import ArtifactPublicationError
from liveclip.media.process import ProcessCancelled
from liveclip.renderer.ffmpeg import (
    FFmpegRenderCancelled,
    FFmpegRenderError,
    RenderAttemptDiagnostic,
    RenderRequest,
    _publish_no_clobber,
    _render_timeout_seconds,
    build_ffmpeg_argv,
    build_filtergraph,
    render_clip,
    render_diagnostics_payload,
    render_execution_diagnostics_payload,
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


def fake_quality_for(path: Path) -> SimpleNamespace:
    return SimpleNamespace(media_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def test_failed_render_diagnostic_write_failure_is_visible_but_path_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostic = RenderAttemptDiagnostic(
        encoder="libx264",
        runtime_attempt=1,
        outcome="process_failed",
        elapsed_ms=1,
        exit_code=1,
        logical_argv=("ffmpeg", "[SOURCE_MEDIA]"),
        stderr_tail="bounded failure",
    )
    error = FFmpegRenderError("failed", diagnostics=(diagnostic,))

    def fail_write(**_kwargs: object) -> str:
        raise ArtifactPublicationError("secret /private/tmp/source.mp4")

    warnings: list[tuple[str, str]] = []

    def capture_warning(message: str, value: str) -> None:
        warnings.append((message, value))

    monkeypatch.setattr(render_task_handler, "_write_attempt_render_diagnostic", fail_write)
    monkeypatch.setattr(render_task_handler.logger, "warning", capture_warning)
    result = render_task_handler._persist_failed_render_diagnostic(
        project_dir=tmp_path / "project",
        attempt_dir=tmp_path / "attempt",
        error=error,
    )

    assert result is None
    assert warnings == [
        (
            "render diagnostic persistence failed error_class=%s",
            "ArtifactPublicationError",
        )
    ]
    assert "/private/tmp/source.mp4" not in repr(warnings)


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
    assert "-loop" not in argv
    assert argv[argv.index("-filter_complex_threads") + 1] == "2"
    assert argv[argv.index("-threads:v") + 1] == "4"
    assert not any("LiveClip title" in argument for argument in argv)


def test_filtergraph_contains_only_numeric_windows_and_fixed_templates(tmp_path: Path) -> None:
    graph = build_filtergraph(make_request(tmp_path))
    assert "vertical_blur_background" not in graph
    assert "between(t,0.000,3.000)" in graph
    assert "boxblur" in graph
    assert "loudnorm" in graph
    assert "eof_action=repeat:repeatlast=1" in graph


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

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        encoder = argv[argv.index("-c:v") + 1]
        attempted_encoders.append(encoder)
        if encoder == "h264_videotoolbox":
            raise subprocess.TimeoutExpired(argv, timeout=1)
        Path(argv[-1]).write_bytes(b"validated-render" * 1_000)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(renderer_module, "run_ffmpeg", fake_run)
    monkeypatch.setattr(
        renderer_module,
        "_validate_temporary_media",
        lambda path, *_args, **_kwargs: fake_quality_for(path),
    )

    result = render_clip(request, ffmpeg_path="/deterministic/fake-ffmpeg")

    assert result.encoder == "libx264"
    assert result.attempts == 2
    assert attempted_encoders == ["h264_videotoolbox", "libx264"]
    assert request.output_path.read_bytes().startswith(b"validated-render")


def test_libx264_runtime_timeout_is_retried_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = replace(make_request(tmp_path), encoder="libx264")
    attempted_encoders: list[str] = []
    attempted_thread_profiles: list[tuple[str, str]] = []

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        encoder = argv[argv.index("-c:v") + 1]
        attempted_encoders.append(encoder)
        attempted_thread_profiles.append(
            (
                argv[argv.index("-filter_complex_threads") + 1],
                argv[argv.index("-threads:v") + 1],
            )
        )
        if len(attempted_encoders) == 1:
            raise subprocess.TimeoutExpired(argv, timeout=1)
        Path(argv[-1]).write_bytes(b"validated-render" * 1_000)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(renderer_module, "run_ffmpeg", fake_run)
    monkeypatch.setattr(
        renderer_module,
        "_validate_temporary_media",
        lambda path, *_args, **_kwargs: fake_quality_for(path),
    )

    result = render_clip(request, ffmpeg_path="/deterministic/fake-ffmpeg")

    assert result.encoder == "libx264"
    assert result.attempts == 2
    assert attempted_encoders == ["libx264", "libx264"]
    assert attempted_thread_profiles == [("2", "4"), ("1", "1")]
    assert request.output_path.read_bytes().startswith(b"validated-render")


def test_libx264_timeout_diagnostics_keep_bounded_partial_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = replace(make_request(tmp_path), encoder="libx264")
    attempts = 0

    def timeout(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal attempts
        attempts += 1
        raise subprocess.TimeoutExpired(
            argv,
            timeout=1,
            stderr=("ignored\n" * 30) + "frame=42 speed=0.0x",
        )

    monkeypatch.setattr(renderer_module, "run_ffmpeg", timeout)

    with pytest.raises(FFmpegRenderError, match="2 bounded attempt") as caught:
        render_clip(request, ffmpeg_path="/deterministic/fake-ffmpeg")

    assert attempts == 2
    assert len(str(caught.value)) < 8_500
    assert len(caught.value.diagnostics) == 2
    assert all(item.outcome == "timeout" for item in caught.value.diagnostics)
    assert all("frame=42 speed=0.0x" in item.stderr_tail for item in caught.value.diagnostics)
    assert all(
        str(tmp_path) not in " ".join(item.logical_argv) for item in caught.value.diagnostics
    )
    assert not request.output_path.exists()


def test_ffmpeg_diagnostics_remove_absolute_relative_and_fd_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = replace(make_request(tmp_path), encoder="libx264")

    def timeout(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            argv,
            timeout=1,
            stderr=(
                "source /opt/liveclip/input/secret name.mp4 failed\n"
                "fd /dev/fd/17 failed\n"
                "relative/private.mp4 failed\n"
                "frame=42 speed=0.0x sk-super-secret-value"
            ),
        )

    monkeypatch.setattr(renderer_module, "run_ffmpeg", timeout)

    with pytest.raises(FFmpegRenderError) as caught:
        render_clip(request, ffmpeg_path="/deterministic/fake-ffmpeg")

    payload = "\n".join(item.stderr_tail for item in caught.value.diagnostics)
    argv_payload = " ".join(
        argument for item in caught.value.diagnostics for argument in item.logical_argv
    )
    assert "secret name.mp4" not in payload
    assert "/opt/" not in payload
    assert "/dev/fd" not in payload
    assert "relative/private.mp4" not in payload
    assert "sk-super-secret-value" not in payload
    assert "frame=42 speed=0.0x" in payload
    assert str(tmp_path) not in argv_payload
    assert "/dev/fd" not in argv_payload


def test_invalid_temporary_render_is_never_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = replace(make_request(tmp_path), encoder="libx264")

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        Path(argv[-1]).write_bytes(b"invalid-render" * 1_000)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def reject_validation(*_: object, **_kwargs: object) -> None:
        raise MediaValidationError("invalid temporary media")

    monkeypatch.setattr(renderer_module, "run_ffmpeg", fake_run)
    monkeypatch.setattr(renderer_module, "_validate_temporary_media", reject_validation)

    with pytest.raises(FFmpegRenderError, match="rendering failed"):
        render_clip(request, ffmpeg_path="/deterministic/fake-ffmpeg")

    assert not request.output_path.exists()


def test_renderer_cancellation_does_not_fallback_or_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = make_request(tmp_path)
    attempts = 0

    def cancel_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal attempts
        attempts += 1
        raise ProcessCancelled("cancelled")

    monkeypatch.setattr(renderer_module, "run_ffmpeg", cancel_run)

    with pytest.raises(FFmpegRenderCancelled, match="cancelled"):
        render_clip(request, ffmpeg_path="/deterministic/fake-ffmpeg")

    assert attempts == 1
    assert not request.output_path.exists()
    assert not list(tmp_path.glob(".*.tmp-*.mp4"))


def test_render_timeout_scales_with_duration_and_resolution(tmp_path: Path) -> None:
    preview = make_request(tmp_path)
    final = replace(
        preview,
        source_end_ms=91_000,
        width=1080,
        height=1920,
    )

    assert _render_timeout_seconds(preview) == 120
    assert _render_timeout_seconds(final) == 1_800


def test_atomic_publication_losing_race_does_not_clobber_winner(tmp_path: Path) -> None:
    private_temporary = tmp_path / ".private-render.mp4"
    published = tmp_path / "revision.mp4"
    private_temporary.write_bytes(b"losing-render")
    published.write_bytes(b"winning-render")

    with pytest.raises(FFmpegRenderError, match="no-clobber race"):
        _publish_no_clobber(
            private_temporary,
            published,
            expected_sha256=hashlib.sha256(b"losing-render").hexdigest(),
        )

    assert published.read_bytes() == b"winning-render"
    assert private_temporary.read_bytes() == b"losing-render"


def test_publication_failure_preserves_completed_attempt_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = replace(make_request(tmp_path), encoder="libx264")

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        Path(argv[-1]).write_bytes(b"validated-render" * 1_000)
        return subprocess.CompletedProcess(argv, 0, "", "frame=10 speed=1.0x")

    def lose_publication(*_args: object, **_kwargs: object) -> None:
        raise FFmpegRenderError("publication lost", retryable=False)

    monkeypatch.setattr(renderer_module, "run_ffmpeg", fake_run)
    monkeypatch.setattr(
        renderer_module,
        "_validate_temporary_media",
        lambda path, *_args, **_kwargs: fake_quality_for(path),
    )
    monkeypatch.setattr(renderer_module, "_publish_no_clobber", lose_publication)

    with pytest.raises(FFmpegRenderError, match="publication lost") as caught:
        render_clip(request, ffmpeg_path="/deterministic/fake-ffmpeg")

    assert caught.value.retryable is False
    assert len(caught.value.diagnostics) == 1
    assert caught.value.diagnostics[0].outcome == "succeeded"
    assert "frame=10 speed=1.0x" in caught.value.diagnostics[0].stderr_tail
    assert not request.output_path.exists()


def test_diagnostic_payloads_have_hard_serialized_size_limits() -> None:
    diagnostic = RenderAttemptDiagnostic(
        encoder="libx264",
        runtime_attempt=1,
        outcome="process_failed",
        elapsed_ms=1,
        exit_code=1,
        logical_argv=tuple("x" * 2_048 for _ in range(256)),
        stderr_tail="y" * 4_000,
    )

    encode = render_diagnostics_payload((diagnostic,) * 100)
    execution = render_execution_diagnostics_payload(
        (diagnostic,) * 100,
        ({"stderr_tail": "z" * 200_000},) * 100,
    )

    assert len(json.dumps(encode, ensure_ascii=False).encode("utf-8")) <= 64 * 1024
    assert len(json.dumps(execution, ensure_ascii=False).encode("utf-8")) <= 80 * 1024
    assert int(encode["records_dropped"]) > 0
    assert int(execution["quality_records_dropped"]) > 0
