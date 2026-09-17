from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import liveclip.pipeline.stage_handlers as stage_handler_module
from liveclip.application.pipeline import (
    LeaseIdentity,
    PipelineRunConfig,
    StageWork,
)
from liveclip.application.stage_execution import StageCancelled, StageExecutionError
from liveclip.clipping_skills.semantic_global_v1 import load_semantic_global_prompt
from liveclip.clipping_skills.semantic_global_v2 import load_semantic_global_v2_review_prompt
from liveclip.clipping_skills.semantic_global_v3 import (
    load_semantic_global_v3_boundary_prompt,
    load_semantic_global_v3_review_prompt,
)
from liveclip.domain.state_transitions import FailureClass, PipelineStage
from liveclip.media.artifacts import ArtifactPublicationError
from liveclip.media.fingerprint import stream_sha256
from liveclip.media.ingest import MediaIngestCancelled
from liveclip.media.models import SourceMediaMetadata
from liveclip.media.preprocess import AudioPreprocessTransientError
from liveclip.media.secure_files import open_pinned_regular_file
from liveclip.pipeline.semantic_global import (
    GlobalReviewStatisticsV3,
    ReviewDecision,
    ValidatedGlobalReviewV3,
)
from liveclip.pipeline.stage_handlers import PipelineStageHandlers
from liveclip.providers.asr.openrouter import (
    OPENROUTER_ASR_CONTRACT_VERSION,
    OpenRouterASRProvider,
)
from liveclip.providers.llm.structured import CodexStructuredLLMProvider, StructuredProviderError
from liveclip.providers.telemetry import (
    ProviderCallRecord,
    ProviderCallStatus,
    ProviderCancelled,
    ProviderConfigurationError,
    ProviderTransientError,
)
from liveclip.renderer.ffmpeg import FFmpegRenderError, RenderAttemptDiagnostic
from liveclip.renderer.quality import MediaValidationError


class FailingProxyHandlers(PipelineStageHandlers):
    def __init__(self, error: Exception) -> None:
        self._error = error

    def _proxy_render(self, *_args: object, **_kwargs: object) -> object:
        raise self._error


class FailingIngestHandlers(PipelineStageHandlers):
    def __init__(self) -> None:
        pass

    def _ingest(self, *_args: object, **_kwargs: object) -> object:
        raise MediaIngestCancelled("cancelled")


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


def _ingest_work() -> StageWork:
    return _work().model_copy(update={"stage": PipelineStage.INGEST})


def _lease() -> LeaseIdentity:
    return LeaseIdentity(task_id="1" * 32, worker_id="worker", lease_token="b" * 64)


def test_semantic_global_materializes_selected_and_manual_review_clips() -> None:
    selected = SimpleNamespace(decision=ReviewDecision.SELECTED, clip=SimpleNamespace(risks=()))
    manual = SimpleNamespace(
        decision=ReviewDecision.MANUAL_REVIEW,
        clip=SimpleNamespace(risks=(SimpleNamespace(type=SimpleNamespace(value="music_rights")),)),
    )
    validated = cast(
        Any,
        SimpleNamespace(selected=(selected,), manual_review=(manual,)),
    )
    retained = stage_handler_module._retained_global_review_clips(validated)

    assert retained[0] is selected
    assert retained[1] is manual
    assert stage_handler_module._global_review_risk_flags(cast(Any, manual)) == (
        "manual_review",
        "music_rights",
    )


def test_v3_assembler_materializes_only_automatic_selected_results() -> None:
    selected = cast(Any, object())
    manual = cast(Any, object())
    blocked = cast(Any, object())
    validated = ValidatedGlobalReviewV3(
        selected=(selected,),
        manual_review=(manual,),
        blocked=(blocked,),
        rejected=(),
        top_n_excluded=(),
        statistics=GlobalReviewStatisticsV3(
            discovery_candidate_count=3,
            boundary_kept_count=3,
            boundary_repaired_count=0,
            boundary_dropped_count=0,
            eligible_before_top_n_count=1,
            selected_count=1,
            manual_count=1,
            blocked_count=1,
            rejected_count=0,
            top_n_excluded_count=0,
            suspicious_exact_top_n=False,
        ),
        validation_notes=(),
    )

    assert stage_handler_module._materialized_global_review_clips(validated) == (selected,)


def _source_metadata(path: Path, *, device: int) -> SourceMediaMetadata:
    metadata = path.stat()
    return SourceMediaMetadata(
        resolved_path=path,
        filename=path.name,
        size_bytes=metadata.st_size,
        sha256=stream_sha256(path),
        duration_ms=10_000,
        format_name="mpegts",
        video_stream_index=0,
        video_codec="hevc",
        video_width=1088,
        video_height=1920,
        video_frame_rate=25.0,
        video_rotation_degrees=0,
        audio_stream_index=1,
        audio_codec="aac",
        audio_sample_rate_hz=48_000,
        audio_channels=2,
        mtime_ns=metadata.st_mtime_ns,
        inode=metadata.st_ino,
        device=device,
    )


def test_pipeline_source_validation_survives_mount_device_change(
    tmp_path: Path,
) -> None:
    source_path = (tmp_path / "source.ts").resolve()
    source_path.write_bytes(b"same immutable source bytes")
    source = _source_metadata(source_path, device=source_path.stat().st_dev + 1)

    with open_pinned_regular_file(source_path) as pinned:
        stage_handler_module._validate_pinned_pipeline_source(
            source,
            pinned,
            cancel_requested=lambda: False,
        )
        stage_handler_module._validate_pinned_pipeline_source_binding(
            source,
            pinned,
            cancel_requested=lambda: False,
        )


def test_pipeline_source_validation_still_rejects_hash_change(tmp_path: Path) -> None:
    source_path = (tmp_path / "source.ts").resolve()
    source_path.write_bytes(b"current source bytes")
    source = _source_metadata(
        source_path,
        device=source_path.stat().st_dev + 1,
    ).model_copy(update={"sha256": "f" * 64})

    with (
        open_pinned_regular_file(source_path) as pinned,
        pytest.raises(ValueError, match="changed after import"),
    ):
        stage_handler_module._validate_pinned_pipeline_source(
            source,
            pinned,
            cancel_requested=lambda: False,
        )


def _invalid_provider_response() -> ProviderTransientError:
    return ProviderTransientError(
        ProviderCallRecord(
            call_id="a" * 32,
            operation_key="b" * 64,
            subject_id="chunk_000001",
            provider="openrouter",
            operation="audio.transcriptions",
            model="openai/whisper-large-v3",
            request_id="gen_retryable_001",
            request_count=1,
            retry_count=0,
            latency_ms=25,
            status=ProviderCallStatus.INVALID,
            failure_code="OPENROUTER_ASR_RESPONSE_INVALID",
            called_at=datetime.now(UTC),
        )
    )


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
        (
            _invalid_provider_response(),
            FailureClass.TRANSIENT,
            "PROXY_RENDER_PROVIDER_TEMPORARY",
        ),
        (
            StructuredProviderError("STRUCTURED_OUTPUT_INVALID", ()),
            FailureClass.DETERMINISTIC,
            "PROXY_RENDER_PROVIDER_OUTPUT_INVALID",
        ),
        (
            StructuredProviderError("STRUCTURED_TOOL_EVENT", ()),
            FailureClass.DETERMINISTIC,
            "PROXY_RENDER_PROVIDER_INVALID",
        ),
        (
            StructuredProviderError("CODEX_CLI_APP_SERVER_PERMISSION_DENIED", ()),
            FailureClass.DETERMINISTIC,
            "PROXY_RENDER_CODEX_NESTED_SESSION",
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


def test_ingest_cancellation_is_not_persisted_as_failure() -> None:
    handler = FailingIngestHandlers()

    with pytest.raises(StageCancelled, match="ingest was cancelled"):
        handler.execute(_ingest_work(), _lease(), cancel_requested=lambda: False)


def test_stage_diagnostic_write_failure_is_visible_but_path_free(
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

    monkeypatch.setattr(stage_handler_module, "_write_stage_render_diagnostic", fail_write)
    monkeypatch.setattr(stage_handler_module.logger, "warning", capture_warning)
    result = stage_handler_module._persist_stage_ffmpeg_diagnostic(
        data_dir=tmp_path,
        work=_work(),
        lease=_lease(),
        error=error,
    )

    assert result is None
    assert warnings == [
        (
            "stage render diagnostic persistence failed error_class=%s",
            "ArtifactPublicationError",
        )
    ]
    assert "/private/tmp/source.mp4" not in repr(warnings)


def test_safe_exception_site_contains_no_error_payload() -> None:
    try:
        raise ValueError("secret transcript and /private/source.mp4")
    except ValueError as error:
        site = stage_handler_module._safe_exception_site(error)

    assert "test_stage_handlers.py" in site
    assert "secret transcript" not in site
    assert "/private/source.mp4" not in site


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("asr_concurrency", 2),
        ("asr_vocabulary_prompt", "另一个领域词"),
        ("openai_request_timeout_seconds", 121.0),
        ("openai_max_request_retries", 3),
        ("openai_retry_base_seconds", 2.0),
        ("openai_retry_max_seconds", 31.0),
        ("llm_input_price_per_million", Decimal("1.0")),
        ("llm_output_price_per_million", Decimal("1.0")),
        ("asr_contract_version", "changed-asr-v2"),
        ("llm_contract_version", "changed-llm-v2"),
        ("editing_prompt_version", "editing_v2"),
        ("editing_prompt_sha256", "f" * 64),
        ("editorial_schema_version", "editorial-suggestion-v2"),
        ("edit_plan_schema_version", "edit-plan-v2"),
    ],
)
def test_every_cloud_contract_setting_changes_pipeline_fingerprint(
    field: str, value: object
) -> None:
    baseline = _work().config
    payload = baseline.model_dump(mode="python")
    if field.startswith("llm_") and field.endswith("price_per_million"):
        payload["llm_input_price_per_million"] = Decimal("1.0")
        payload["llm_output_price_per_million"] = Decimal("1.0")
    else:
        payload[field] = value

    changed = PipelineRunConfig.model_validate(payload)

    assert baseline.fingerprint != changed.fingerprint


def test_provider_validation_binds_contract_versions() -> None:
    baseline = _work()
    changed = baseline.config.model_copy(update={"asr_contract_version": "changed-v2"})

    assert baseline.config.fingerprint != changed.fingerprint
    handlers = PipelineStageHandlers(
        data_dir=Path("/tmp/liveclip-contract-test"),
        allowed_media_roots=(),
        assets=object(),  # type: ignore[arg-type]
        state=object(),  # type: ignore[arg-type]
    )
    with pytest.raises(ProviderConfigurationError, match="persisted ASR contract"):
        handlers._asr_provider(baseline.model_copy(update={"config": changed}))

    prompt_changed = baseline.config.model_copy(update={"editing_prompt_sha256": "f" * 64})
    assert baseline.config.fingerprint != prompt_changed.fingerprint
    with pytest.raises(ProviderConfigurationError, match="persisted editing contract"):
        handlers._llm_provider(baseline.model_copy(update={"config": prompt_changed}))


def test_openrouter_mode_dispatches_only_the_openrouter_asr_adapter() -> None:
    baseline = _work()
    config = baseline.config.model_copy(
        update={
            "provider": "openrouter-codex",
            "transcription_model": "openai/whisper-large-v3",
            "asr_contract_version": OPENROUTER_ASR_CONTRACT_VERSION,
        }
    )
    handlers = PipelineStageHandlers(
        data_dir=Path("/tmp/liveclip-openrouter-contract-test"),
        allowed_media_roots=(),
        assets=object(),  # type: ignore[arg-type]
        state=object(),  # type: ignore[arg-type]
        openrouter_api_key="unit-test-router-key",
    )

    provider = handlers._asr_provider(baseline.model_copy(update={"config": config}))
    try:
        assert isinstance(provider, OpenRouterASRProvider)
        assert provider.provider_name == "openrouter"
    finally:
        provider._client.close()


def test_mlx_mode_dispatches_only_the_local_asr_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = (tmp_path / "large-v3").resolve()
    contract = "mlx-asr-large-v3-fp16-greedy-v4." + "a" * 32
    observed: dict[str, object] = {}

    def fake_provider(**kwargs: object) -> SimpleNamespace:
        observed.update(kwargs)
        return SimpleNamespace(contract_version=contract, provider_name="mlx")

    monkeypatch.setattr(stage_handler_module, "MLXASRProvider", fake_provider)
    baseline = _work()
    config = baseline.config.model_copy(
        update={
            "provider": "mlx-codex",
            "transcription_model": "openai/whisper-large-v3",
            "asr_contract_version": contract,
            "asr_concurrency": 1,
        }
    )
    handlers = PipelineStageHandlers(
        data_dir=tmp_path,
        allowed_media_roots=(),
        assets=object(),  # type: ignore[arg-type]
        state=object(),  # type: ignore[arg-type]
        mlx_asr_model_path=model_path,
    )

    provider = handlers._asr_provider(baseline.model_copy(update={"config": config}))

    assert provider.provider_name == "mlx"
    assert observed == {
        "model_path": model_path,
        "model_name": "openai/whisper-large-v3",
    }


def test_mock_runtime_rejects_persisted_openai_work_before_any_handler() -> None:
    handler = FailingProxyHandlers(AssertionError("provider mode fence was bypassed"))
    handler._runtime_provider = "mock"
    handler._openai_api_key = None
    openai_config = _work().config.model_copy(update={"provider": "openai"})

    with pytest.raises(StageExecutionError) as raised:
        handler.execute(
            _work().model_copy(update={"config": openai_config}),
            _lease(),
            cancel_requested=lambda: False,
        )

    assert raised.value.failure_class == FailureClass.DETERMINISTIC
    assert raised.value.error_code == "PROXY_RENDER_PROVIDER_INVALID"


def test_accuracy_first_codex_global_review_gets_high_reasoning_and_timeout_headroom(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers = PipelineStageHandlers(
        data_dir=tmp_path,
        allowed_media_roots=(),
        assets=object(),  # type: ignore[arg-type]
        state=object(),  # type: ignore[arg-type]
        codex_executable="codex",
    )
    config = _work().config.model_copy(
        update={
            "provider": "openrouter-codex",
            "openai_request_timeout_seconds": 300.0,
            "llm_model": "gpt-5.6-terra",
        }
    )
    work = _work().model_copy(update={"config": config})
    prompt = load_semantic_global_v2_review_prompt("general")
    monkeypatch.setattr(
        "liveclip.providers.llm.codex.resolve_codex_executable",
        lambda _configured: "/usr/bin/true",
    )
    monkeypatch.setattr(
        "liveclip.providers.llm.codex.codex_cli_contract_version",
        lambda _configured: config.llm_contract_version,
    )

    provider = handlers._structured_provider(work, prompt)

    assert isinstance(provider, CodexStructuredLLMProvider)
    assert provider.reasoning_effort == "high"
    assert provider.timeout_seconds == 600.0


def test_v3_global_uses_high_reasoning_while_boundary_review_stays_medium(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers = PipelineStageHandlers(
        data_dir=tmp_path,
        allowed_media_roots=(),
        assets=object(),  # type: ignore[arg-type]
        state=object(),  # type: ignore[arg-type]
        codex_executable="codex",
    )
    config = _work().config.model_copy(update={"provider": "openrouter-codex"})
    work = _work().model_copy(update={"config": config})
    monkeypatch.setattr(
        "liveclip.providers.llm.codex.resolve_codex_executable",
        lambda _configured: "/usr/bin/true",
    )
    monkeypatch.setattr(
        "liveclip.providers.llm.codex.codex_cli_contract_version",
        lambda _configured: config.llm_contract_version,
    )

    global_provider = handlers._structured_provider(
        work,
        load_semantic_global_v3_review_prompt("general"),
    )
    boundary_provider = handlers._structured_provider(
        work,
        load_semantic_global_v3_boundary_prompt("general"),
    )

    assert isinstance(global_provider, CodexStructuredLLMProvider)
    assert isinstance(boundary_provider, CodexStructuredLLMProvider)
    assert global_provider.reasoning_effort == "high"
    assert global_provider.timeout_seconds == 600.0
    assert boundary_provider.reasoning_effort == "medium"


def test_legacy_codex_global_review_keeps_historical_medium_reasoning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers = PipelineStageHandlers(
        data_dir=tmp_path,
        allowed_media_roots=(),
        assets=object(),  # type: ignore[arg-type]
        state=object(),  # type: ignore[arg-type]
        codex_executable="codex",
    )
    config = _work().config.model_copy(update={"provider": "openrouter-codex"})
    work = _work().model_copy(update={"config": config})
    prompt = load_semantic_global_prompt("global_review", "general")
    monkeypatch.setattr(
        "liveclip.providers.llm.codex.resolve_codex_executable",
        lambda _configured: "/usr/bin/true",
    )
    monkeypatch.setattr(
        "liveclip.providers.llm.codex.codex_cli_contract_version",
        lambda _configured: config.llm_contract_version,
    )

    provider = handlers._structured_provider(work, prompt)

    assert isinstance(provider, CodexStructuredLLMProvider)
    assert provider.reasoning_effort == "medium"


class _CancelledCallState:
    def __init__(self) -> None:
        self.records: list[ProviderCallRecord] = []

    def record_provider_call_after_cancel(self, _fence: object, record: ProviderCallRecord) -> bool:
        self.records.append(record)
        return True


class _CancelledProviderHandlers(PipelineStageHandlers):
    cancelled_record: ProviderCallRecord

    def _proxy_render(self, *_args: object, **_kwargs: object) -> object:
        raise ProviderCancelled(self.cancelled_record)


def test_stage_persists_provider_call_evidence_before_acknowledging_cancel() -> None:
    state = _CancelledCallState()
    handler = _CancelledProviderHandlers(
        data_dir=Path("/tmp/liveclip-cancel-test"),
        allowed_media_roots=(),
        assets=object(),  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
    )
    handler.cancelled_record = ProviderCallRecord(
        call_id="a" * 32,
        operation_key="b" * 64,
        subject_id="candidate_1",
        provider="openai",
        operation="responses.edit.initial",
        model="gpt-5.6-terra",
        request_count=1,
        retry_count=0,
        latency_ms=25,
        status=ProviderCallStatus.CANCELLED,
        failure_code="OPENAI_CANCELLED",
        prompt_version="editing_v1",
        prompt_sha256="c" * 64,
        called_at=datetime.now(UTC),
    )

    with pytest.raises(StageCancelled):
        handler.execute(_work(), _lease(), cancel_requested=lambda: False)

    assert state.records == [handler.cancelled_record]
