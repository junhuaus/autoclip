from __future__ import annotations

from pathlib import Path

import pytest

from liveclip.application.pipeline import (
    LeaseIdentity,
    PipelineRunConfig,
    StageWork,
)
from liveclip.application.stage_execution import StageExecutionError
from liveclip.domain.state_transitions import FailureClass, PipelineStage
from liveclip.media.preprocess import AudioPreprocessTransientError
from liveclip.pipeline.stage_handlers import PipelineStageHandlers
from liveclip.renderer.ffmpeg import FFmpegRenderError
from liveclip.renderer.quality import MediaValidationError


class FailingProxyHandlers(PipelineStageHandlers):
    def __init__(self, error: Exception) -> None:
        self._error = error

    def _proxy_render(self, *_args: object, **_kwargs: object) -> object:
        raise self._error


def _work() -> StageWork:
    return StageWork(
        task_id="1" * 32,
        stage_run_id="2" * 32,
        run_id="3" * 32,
        project_id="4" * 32,
        stage=PipelineStage.PROXY_RENDER,
        source_path=Path("/allowed/source.mp4"),
        config=PipelineRunConfig(
            provider="mock",
            top_n=3,
            minimum_clip_ms=8_000,
            maximum_clip_ms=12_000,
            chunk_duration_ms=12_000,
            chunk_overlap_ms=2_000,
            max_chunk_bytes=24_000_000,
            transcription_model="mock-asr-v1",
            llm_model="mock-llm-v1",
            preview_width=270,
            preview_height=480,
            video_encoder="libx264",
        ),
        input_fingerprint="a" * 64,
        generation=1,
        revision_epoch=0,
        already_succeeded=False,
        cancellation_requested=False,
    )


def _lease() -> LeaseIdentity:
    return LeaseIdentity(task_id="1" * 32, worker_id="worker", lease_token="b" * 64)


@pytest.mark.parametrize(
    ("error", "failure_class", "error_code"),
    [
        (FFmpegRenderError("hung encoder"), FailureClass.TRANSIENT, "RENDER_TEMPORARY"),
        (
            AudioPreprocessTransientError("hung extraction"),
            FailureClass.TRANSIENT,
            "PROXY_RENDER_EXECUTION_TEMPORARY",
        ),
        (
            MediaValidationError("bad media"),
            FailureClass.DETERMINISTIC,
            "RENDER_VALIDATION_FAILED",
        ),
    ],
)
def test_proxy_failures_are_classified_for_safe_retry(
    error: Exception,
    failure_class: FailureClass,
    error_code: str,
) -> None:
    handler = FailingProxyHandlers(error)

    with pytest.raises(StageExecutionError) as raised:
        handler.execute(_work(), _lease(), cancel_requested=lambda: False)

    assert raised.value.failure_class == failure_class
    assert raised.value.error_code == error_code
