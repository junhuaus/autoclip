from __future__ import annotations

import hashlib
import json
import logging
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from liveclip.application.assets import AssetReservation, AssetStore
from liveclip.application.pipeline import LeaseIdentity, StageWork
from liveclip.application.stage_execution import (
    CommittedStageAsset,
    PersistedRevision,
    PreparedRevision,
    ProxyRenderIntent,
    ProxyRenderPersistence,
    StageCancelled,
    StageExecutionError,
    StageExecutionResult,
    StageMutationFence,
    StageStateStore,
    stage_output_fingerprint,
)
from liveclip.clipping_skills import (
    load_semantic_continuous_skill,
    load_semantic_discovery_skill,
)
from liveclip.clipping_skills.semantic_global_v1 import (
    SemanticGlobalPromptBundle,
    load_semantic_global_prompt,
)
from liveclip.clipping_skills.semantic_windowed_v1 import (
    load_semantic_windowed_discovery_prompt,
)
from liveclip.domain.edit_plan import (
    EDIT_PLAN_PIPELINE_CONTRACT_VERSION,
    CaptionTemplate,
    EditPlan,
    Effect,
    Layout,
    captions_to_srt,
)
from liveclip.domain.review import EditPlanRevision, RevisionOrigin
from liveclip.domain.state_transitions import AssetStatus, FailureClass, PipelineStage
from liveclip.domain.transcript import TranscriptDocument
from liveclip.media.artifacts import (
    ArtifactPublicationError,
    attempt_directory,
    cleanup_attempt_worktree,
    project_directory,
    publish_file_no_clobber,
    write_json_no_clobber,
    write_text_no_clobber,
)
from liveclip.media.ingest import (
    MediaIngestCancelled,
    MediaIngestError,
    MediaIngestTransientError,
    ingest_source,
)
from liveclip.media.models import AudioChunkManifest, SourceMediaMetadata
from liveclip.media.preprocess import (
    AudioPreprocessCancelled,
    AudioPreprocessError,
    AudioPreprocessTransientError,
    preprocess_audio,
)
from liveclip.media.secure_files import (
    PinnedRegularFile,
    SecureFileError,
    hash_regular_file_no_follow,
    open_pinned_regular_file,
    read_regular_file_no_follow,
)
from liveclip.pipeline.candidates import CandidateGenerationConfig, generate_candidates
from liveclip.pipeline.editing import edit_and_rank_candidates
from liveclip.pipeline.semantic_cache import (
    load_semantic_stage_cache,
    semantic_stage_cache_key,
    write_semantic_stage_cache,
)
from liveclip.pipeline.semantic_clipping import (
    generate_semantic_analysis_windows,
    select_semantic_clips,
)
from liveclip.pipeline.semantic_global import (
    DiscoveryOutput,
    GlobalReviewOutput,
    SemanticGlobalConfig,
    SemanticInputMode,
    SemanticInputPlan,
    SemanticInputUnit,
    ValidatedGlobalClip,
    build_global_review_payload,
    discovery_request_payload,
    namespace_discovery_output,
    plan_boundary_bridge_units,
    plan_semantic_input,
    plan_semantic_windowed_input,
    semantic_global_output_slots,
    semantic_repair_payload,
    semantic_request_tokens,
    validate_discovery_output,
    validate_global_review,
)
from liveclip.pipeline.transcript import transcribe_chunks_detailed
from liveclip.prompts import EditingPromptBundle
from liveclip.providers.asr.base import AudioChunkLike
from liveclip.providers.asr.mock import MockASRProvider
from liveclip.providers.asr.openai import OpenAIASRProvider
from liveclip.providers.asr.openrouter import OpenRouterASRProvider
from liveclip.providers.llm.base import EDITORIAL_SUGGESTION_SCHEMA_VERSION
from liveclip.providers.llm.codex import CodexCLILLMProvider
from liveclip.providers.llm.mock import MockLLMProvider
from liveclip.providers.llm.openai import OpenAILLMProvider
from liveclip.providers.llm.structured import (
    CodexStructuredLLMProvider,
    MockStructuredLLMProvider,
    OpenAIStructuredLLMProvider,
    StructuredCallResult,
    StructuredLLMProvider,
    StructuredProviderError,
)
from liveclip.providers.openai_retry import OpenAIRetryPolicy
from liveclip.providers.telemetry import (
    ProviderCallRecord,
    ProviderCallStatus,
    ProviderCancelled,
    ProviderConfigurationError,
    ProviderDeterministicError,
    ProviderTransientError,
)
from liveclip.renderer.contracts import FFMPEG_RENDERER_CONTRACT_VERSION
from liveclip.renderer.ffmpeg import (
    FFmpegRenderCancelled,
    FFmpegRenderError,
    render_error_diagnostics_payload,
)
from liveclip.renderer.quality import (
    MediaValidationCancelled,
    MediaValidationError,
    MediaValidationTransientError,
    validate_rendered_media,
)
from liveclip.renderer.service import (
    RenderTextMode,
    render_edit_plan_revision,
    render_revision_overlays_for_mode,
)
from liveclip.services.captions import captions_for_clip

logger = logging.getLogger(__name__)


class PipelineStageHandlers:
    def __init__(
        self,
        *,
        data_dir: Path,
        allowed_media_roots: tuple[Path, ...],
        assets: AssetStore,
        state: StageStateStore,
        openai_api_key: str | None = None,
        openrouter_api_key: str | None = None,
        openrouter_base_url: str = "https://openrouter.ai/api/v1",
        codex_executable: str = "codex",
        runtime_provider: str | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._allowed_media_roots = allowed_media_roots
        self._assets = assets
        self._state = state
        self._openai_api_key = openai_api_key or None
        self._openrouter_api_key = openrouter_api_key or None
        self._openrouter_base_url = openrouter_base_url
        self._codex_executable = codex_executable
        self._runtime_provider = runtime_provider

    def execute(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        *,
        cancel_requested: Callable[[], bool],
    ) -> StageExecutionResult:
        _check_cancel(cancel_requested)
        try:
            if (
                getattr(self, "_runtime_provider", None) is not None
                and work.config.provider != self._runtime_provider
            ):
                raise ProviderConfigurationError(
                    "persisted AI provider does not match the active runtime mode"
                )
            handlers = {
                PipelineStage.INGEST: self._ingest,
                PipelineStage.PREPROCESS: self._preprocess,
                PipelineStage.TRANSCRIBE: self._transcribe,
                PipelineStage.CANDIDATES: self._candidates,
                PipelineStage.EDIT: self._edit,
                PipelineStage.PROXY_RENDER: self._proxy_render,
            }
            return handlers[work.stage](work, lease, cancel_requested)
        except (AudioPreprocessCancelled, MediaIngestCancelled) as exc:
            raise StageCancelled(f"{work.stage.value} was cancelled") from exc
        except (FFmpegRenderCancelled, MediaValidationCancelled) as exc:
            raise StageCancelled("proxy rendering was cancelled") from exc
        except ProviderCancelled as exc:
            for record in exc.call_records:
                self._state.record_provider_call_after_cancel(
                    _mutation_fence(work, lease),
                    record,
                )
            raise StageCancelled("cloud provider work was cancelled") from exc
        except ProviderTransientError as exc:
            raise StageExecutionError(
                failure_class=FailureClass.TRANSIENT,
                error_code=f"{work.stage.value.upper()}_PROVIDER_TEMPORARY",
                safe_message=f"The {work.stage.value} cloud request failed temporarily",
            ) from exc
        except (ProviderDeterministicError, ProviderConfigurationError) as exc:
            raise StageExecutionError(
                failure_class=FailureClass.DETERMINISTIC,
                error_code=f"{work.stage.value.upper()}_PROVIDER_INVALID",
                safe_message=f"The {work.stage.value} cloud provider configuration is invalid",
            ) from exc
        except (
            AudioPreprocessTransientError,
            MediaIngestTransientError,
            MediaValidationTransientError,
        ) as exc:
            raise StageExecutionError(
                failure_class=FailureClass.TRANSIENT,
                error_code=f"{work.stage.value.upper()}_EXECUTION_TEMPORARY",
                safe_message=f"The {work.stage.value} stage failed temporarily and may be retried",
            ) from exc
        except (AudioPreprocessError, MediaIngestError) as exc:
            raise StageExecutionError(
                failure_class=FailureClass.DETERMINISTIC,
                error_code=f"{work.stage.value.upper()}_INPUT_INVALID",
                safe_message=f"The {work.stage.value} stage rejected its deterministic input",
            ) from exc
        except FFmpegRenderError as exc:
            raise StageExecutionError(
                failure_class=(
                    FailureClass.TRANSIENT if exc.retryable else FailureClass.DETERMINISTIC
                ),
                error_code=("RENDER_TEMPORARY" if exc.retryable else "RENDER_VALIDATION_FAILED"),
                safe_message=(
                    "The local renderer failed temporarily and may be retried"
                    if exc.retryable
                    else "A proxy render failed deterministic media validation"
                ),
                diagnostic_relative_path=_persist_stage_ffmpeg_diagnostic(
                    data_dir=getattr(self, "_data_dir", None),
                    work=work,
                    lease=lease,
                    error=exc,
                ),
            ) from exc
        except MediaValidationError as exc:
            raise StageExecutionError(
                failure_class=FailureClass.DETERMINISTIC,
                error_code="RENDER_VALIDATION_FAILED",
                safe_message="A rendered proxy did not pass deterministic media validation",
            ) from exc
        except StageCancelled:
            raise
        except StageExecutionError:
            raise
        except OSError as exc:
            raise StageExecutionError(
                failure_class=FailureClass.TRANSIENT,
                error_code="LOCAL_IO_TEMPORARY",
                safe_message="A local artifact operation failed temporarily",
            ) from exc
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            diagnostic_relative_path = _persist_stage_validation_diagnostic(
                data_dir=getattr(self, "_data_dir", None),
                work=work,
                lease=lease,
                error=exc,
            )
            logger.warning(
                "stage local output rejected stage=%s error_class=%s error_site=%s",
                work.stage.value,
                type(exc).__name__,
                _safe_exception_site(exc),
            )
            raise StageExecutionError(
                failure_class=FailureClass.DETERMINISTIC,
                error_code=f"{work.stage.value.upper()}_OUTPUT_INVALID",
                safe_message=f"The {work.stage.value} stage produced invalid local data",
                diagnostic_relative_path=diagnostic_relative_path,
            ) from exc

    def _ingest(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        cancel_requested: Callable[[], bool],
    ) -> StageExecutionResult:
        project_dir = project_directory(self._data_dir, work.project_id)
        relative_path = _generation_relative(work.generation, "source/source-media.json")
        reservation = self._reserve(
            work,
            lease,
            kind="source_metadata",
            relative_path=relative_path,
            mime_type="application/json",
        )
        _check_cancel(cancel_requested)
        source = ingest_source(
            work.source_path,
            allowed_roots=self._allowed_media_roots,
            cancel_requested=cancel_requested,
        )
        write_json_no_clobber(
            project_dir / relative_path,
            source.model_dump(mode="json"),
        )
        committed = self._commit(
            lease,
            reservation,
            project_dir=project_dir,
            validation={
                "schema_version": "1",
                "source_sha256": source.sha256,
                "streams": ["video", "audio"],
            },
        )
        source_id = self._state.save_source(_mutation_fence(work, lease), source=source)
        return self._result(
            work.stage,
            (committed,),
            {"source_media_id": source_id},
        )

    def _preprocess(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        cancel_requested: Callable[[], bool],
    ) -> StageExecutionResult:
        project_dir = project_directory(self._data_dir, work.project_id)
        generation_dir = _generation_directory(project_dir, work.generation)
        source = self._load_verified_source(work, project_dir=project_dir)
        manifest_relative = _generation_relative(work.generation, "audio/chunk-manifest.json")
        manifest_reservation = self._reserve(
            work,
            lease,
            kind="audio_manifest",
            relative_path=manifest_relative,
            mime_type="application/json",
        )
        manifest = preprocess_audio(
            source=source,
            output_dir=generation_dir / "audio",
            chunk_duration_ms=work.config.chunk_duration_ms,
            overlap_ms=work.config.chunk_overlap_ms,
            max_chunk_bytes=work.config.max_chunk_bytes,
            cancel_requested=cancel_requested,
        )
        committed: list[AssetReservation] = [
            self._commit(
                lease,
                manifest_reservation,
                project_dir=project_dir,
                validation={
                    "schema_version": "1",
                    "complete": manifest.complete,
                    "chunk_count": len(manifest.chunks),
                },
            )
        ]
        chunk_asset_ids: dict[int, str] = {}
        for chunk in manifest.chunks:
            _check_cancel(cancel_requested)
            relative_path = chunk.path.relative_to(project_dir).as_posix()
            reservation = self._assets.reserve(
                lease,
                project_id=work.project_id,
                kind="audio_chunk",
                relative_path=relative_path,
                mime_type="audio/mp4",
                input_fingerprint=chunk.cache_key,
                generation=work.generation,
            )
            chunk_asset = self._commit(
                lease,
                reservation,
                project_dir=project_dir,
                validation={
                    "schema_version": "1",
                    "source_start_ms": chunk.source_start_ms,
                    "source_end_ms": chunk.source_end_ms,
                    "sha256": chunk.sha256,
                },
            )
            if chunk_asset.sha256 != chunk.sha256:
                raise ValueError("committed audio chunk hash differs from its manifest")
            committed.append(chunk_asset)
            chunk_asset_ids[chunk.index] = chunk_asset.asset_id
        self._state.save_audio(
            _mutation_fence(work, lease),
            manifest=manifest,
            chunk_asset_ids=chunk_asset_ids,
        )
        return self._result(
            work.stage,
            tuple(committed),
            {"chunk_count": len(manifest.chunks)},
        )

    def _transcribe(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        cancel_requested: Callable[[], bool],
    ) -> StageExecutionResult:
        project_dir = project_directory(self._data_dir, work.project_id)
        generation_dir = _generation_directory(project_dir, work.generation)
        attempt_dir = attempt_directory(project_dir, lease)
        source = self._load_verified_source(work, project_dir=project_dir)
        manifest_relative = _generation_relative(work.generation, "audio/chunk-manifest.json")
        manifest = AudioChunkManifest.model_validate_json(
            self._committed_asset_bytes(
                work,
                project_dir=project_dir,
                kind="audio_manifest",
                relative_path=manifest_relative,
                max_bytes=8 * 1024 * 1024,
            )
        )
        if (
            not manifest.complete
            or manifest.source_sha256 != source.sha256
            or manifest.source_duration_ms != source.duration_ms
            or manifest.source_audio_stream_index != source.audio_stream_index
        ):
            raise ValueError("audio manifest source binding differs from imported media")
        _validate_audio_chunk_assets(
            project_dir=project_dir,
            manifest=manifest,
            assets=self._committed_assets(work, kinds=("audio_chunk",)),
            cancel_requested=cancel_requested,
        )
        reservations = (
            self._reserve(
                work,
                lease,
                kind="transcript_json",
                relative_path=_generation_relative(work.generation, "transcript/transcript.json"),
                mime_type="application/json",
            ),
            self._reserve(
                work,
                lease,
                kind="transcript_srt",
                relative_path=_generation_relative(work.generation, "transcript/transcript.srt"),
                mime_type="application/x-subrip",
            ),
        )
        _check_cancel(cancel_requested)
        provider = self._asr_provider(work)
        fence = _mutation_fence(work, lease)

        def record_outcome(
            chunk: AudioChunkLike,
            call_record: ProviderCallRecord | None,
            status: ProviderCallStatus,
            cache_hit: bool,
        ) -> None:
            cache_key = getattr(chunk, "cache_key", None)
            if not isinstance(cache_key, str):
                raise ValueError("audio chunk outcome lacks its cache key")
            if status == ProviderCallStatus.CANCELLED:
                if call_record is not None:
                    self._state.record_provider_call_after_cancel(fence, call_record)
                return
            self._state.record_asr_chunk_outcome(
                fence,
                cache_key=cache_key,
                status=status,
                # A cache hit performs no provider request in this run. Keep the
                # immutable call evidence on the run that actually made it.
                call_record=None if cache_hit else call_record,
                cache_hit=cache_hit,
            )

        transcript_run = transcribe_chunks_detailed(
            provider,
            manifest.chunks,
            source_duration_ms=source.duration_ms,
            output_dir=attempt_dir / "transcript",
            cache_dir=generation_dir / "transcript" / "asr-cache",
            fallback_cache_dirs=tuple(
                project_dir / _generation_relative(generation, "transcript/asr-cache")
                for generation in range(1, work.generation)
            ),
            language="zh",
            vocabulary_prompt=work.config.asr_vocabulary_prompt,
            concurrency=work.config.asr_concurrency,
            cancel_requested=cancel_requested,
            on_chunk_outcome=record_outcome,
        )
        transcript = transcript_run.document
        _check_cancel(cancel_requested)
        publish_file_no_clobber(
            attempt_dir / "transcript" / "transcript.json",
            generation_dir / "transcript" / "transcript.json",
        )
        publish_file_no_clobber(
            attempt_dir / "transcript" / "transcript.srt",
            generation_dir / "transcript" / "transcript.srt",
        )
        committed = (
            self._commit(
                lease,
                reservations[0],
                project_dir=project_dir,
                validation={
                    "schema_version": "1",
                    "segment_count": len(transcript.segments),
                    "word_timing_status": transcript.word_timing_status.value,
                },
            ),
            self._commit(
                lease,
                reservations[1],
                project_dir=project_dir,
                validation={"schema_version": "1", "timeline": "source_absolute_ms"},
            ),
        )
        assert committed[0].sha256 is not None
        transcript_id = self._state.save_transcript(
            _mutation_fence(work, lease),
            transcript=transcript,
            transcript_asset_id=committed[0].asset_id,
            fingerprint=committed[0].sha256,
            provider=provider.provider_name,
            model=provider.model_name,
        )
        cleanup_attempt_worktree(
            project_dir,
            task_id=lease.task_id,
            lease_token=lease.lease_token,
            preserve_diagnostics=False,
        )
        return self._result(
            work.stage,
            committed,
            {"transcript_id": transcript_id, "segment_count": len(transcript.segments)},
        )

    def _candidates(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        cancel_requested: Callable[[], bool],
    ) -> StageExecutionResult:
        project_dir = project_directory(self._data_dir, work.project_id)
        generation_dir = _generation_directory(project_dir, work.generation)
        transcript = TranscriptDocument.model_validate_json(
            self._committed_asset_bytes(
                work,
                project_dir=project_dir,
                kind="transcript_json",
                relative_path=_generation_relative(work.generation, "transcript/transcript.json"),
                max_bytes=64 * 1024 * 1024,
            )
        )
        manifest = AudioChunkManifest.model_validate_json(
            self._committed_asset_bytes(
                work,
                project_dir=project_dir,
                kind="audio_manifest",
                relative_path=_generation_relative(work.generation, "audio/chunk-manifest.json"),
                max_bytes=8 * 1024 * 1024,
            )
        )
        reservation = self._reserve(
            work,
            lease,
            kind="rough_candidates",
            relative_path=_generation_relative(work.generation, "candidates/rough-candidates.json"),
            mime_type="application/json",
        )
        _check_cancel(cancel_requested)
        semantic_global_payload: dict[str, object] | None = None
        artifact_config: dict[str, object]
        if work.config.clipping_algorithm in {"semantic_global", "semantic_windowed"}:
            semantic_config = _semantic_global_config(work)
            discovery_prompt = (
                load_semantic_windowed_discovery_prompt(work.config.semantic_profile)
                if work.config.clipping_algorithm == "semantic_windowed"
                else load_semantic_global_prompt("discovery", work.config.semantic_profile)
            )
            _assert_semantic_global_prompt(work, discovery_prompt)
            planner = (
                plan_semantic_windowed_input
                if work.config.clipping_algorithm == "semantic_windowed"
                else plan_semantic_input
            )
            input_plan = planner(
                transcript,
                prompt=discovery_prompt.instructions,
                config=semantic_config,
            )
            discovery_provider = self._structured_provider(work, discovery_prompt)
            fence = _mutation_fence(work, lease)
            discovery_outputs: list[DiscoveryOutput] = []
            discovery_cache_hits: list[bool] = []
            discovery_validation_events: list[dict[str, str]] = []

            def normalize_discovery(
                raw: DiscoveryOutput,
                unit: SemanticInputUnit,
            ) -> DiscoveryOutput:
                normalized, notes = namespace_discovery_output(raw, unit=unit)
                discovery_validation_events.extend(
                    {"input_unit_id": unit.unit_id, "normalization": note} for note in notes
                )
                return normalized

            model_settings = _semantic_model_settings(work)
            discovery_cache_dir = generation_dir / "candidates/semantic-cache/discovery"
            fallback_discovery_cache_dirs = tuple(
                project_dir
                / _generation_relative(generation, "candidates/semantic-cache/discovery")
                for generation in range(1, work.generation)
            )
            prefetched_discovery: dict[str, StructuredCallResult[DiscoveryOutput]] = {}
            if work.config.clipping_algorithm == "semantic_windowed":
                uncached_requests: list[tuple[str, dict[str, object]]] = []
                for unit in input_plan.units:
                    request_payload = discovery_request_payload(
                        unit,
                        source_id=work.project_id,
                        mode=input_plan.mode,
                        config=semantic_config,
                    )
                    cache_key = semantic_stage_cache_key(
                        stage="discovery",
                        payload=request_payload,
                        provider=discovery_provider,
                        model_settings=model_settings,
                        output_model=DiscoveryOutput,
                    )
                    cached = load_semantic_stage_cache(
                        cache_dirs=(discovery_cache_dir, *fallback_discovery_cache_dirs),
                        cache_key=cache_key,
                        stage="discovery",
                        payload=request_payload,
                        provider=discovery_provider,
                        model_settings=model_settings,
                        output_model=DiscoveryOutput,
                    )
                    if cached is None:
                        uncached_requests.append((unit.unit_id, request_payload))
                first_prefetch_error: StructuredProviderError | None = None
                with ThreadPoolExecutor(
                    max_workers=min(
                        semantic_config.window_discovery_concurrency,
                        max(1, len(uncached_requests)),
                    ),
                    thread_name_prefix="semantic-windowed-discovery",
                ) as executor:
                    pending = {
                        executor.submit(
                            discovery_provider.generate,
                            subject_id=f"{work.run_id}.{unit_id}",
                            payload=request_payload,
                            response_model=DiscoveryOutput,
                            cancel_requested=cancel_requested,
                        ): unit_id
                        for unit_id, request_payload in uncached_requests
                    }
                    for future in as_completed(pending):
                        unit_id = pending[future]
                        try:
                            result = future.result()
                        except StructuredProviderError as exc:
                            self._state.record_provider_calls(
                                fence,
                                exc.call_records,
                                cache_hit=False,
                            )
                            first_prefetch_error = first_prefetch_error or exc
                            continue
                        self._state.record_provider_calls(
                            fence,
                            result.call_records,
                            cache_hit=False,
                        )
                        prefetched_discovery[unit_id] = result
                if first_prefetch_error is not None:
                    raise first_prefetch_error
            for unit in input_plan.units:
                _check_cancel(cancel_requested)
                request_payload = discovery_request_payload(
                    unit,
                    source_id=work.project_id,
                    mode=input_plan.mode,
                    config=semantic_config,
                )
                cache_key = semantic_stage_cache_key(
                    stage="discovery",
                    payload=request_payload,
                    provider=discovery_provider,
                    model_settings=model_settings,
                    output_model=DiscoveryOutput,
                )
                cached = load_semantic_stage_cache(
                    cache_dirs=(discovery_cache_dir, *fallback_discovery_cache_dirs),
                    cache_key=cache_key,
                    stage="discovery",
                    payload=request_payload,
                    provider=discovery_provider,
                    model_settings=model_settings,
                    output_model=DiscoveryOutput,
                )
                if cached is not None:
                    output = validate_discovery_output(
                        normalize_discovery(cached, unit),
                        unit=unit,
                        config=semantic_config,
                    )
                    discovery_outputs.append(output)
                    discovery_cache_hits.append(True)
                    continue
                prefetched_result = (
                    prefetched_discovery.pop(unit.unit_id)
                    if unit.unit_id in prefetched_discovery
                    else None
                )
                if prefetched_result is None:
                    try:
                        result = discovery_provider.generate(
                            subject_id=f"{work.run_id}.{unit.unit_id}",
                            payload=request_payload,
                            response_model=DiscoveryOutput,
                            cancel_requested=cancel_requested,
                        )
                    except StructuredProviderError as exc:
                        self._state.record_provider_calls(
                            fence,
                            exc.call_records,
                            cache_hit=False,
                        )
                        raise
                    self._state.record_provider_calls(
                        fence,
                        result.call_records,
                        cache_hit=False,
                    )
                else:
                    result = prefetched_result
                normalized_output = normalize_discovery(result.output, unit)
                try:
                    output = validate_discovery_output(
                        normalized_output,
                        unit=unit,
                        config=semantic_config,
                    )
                except ValueError as exc:
                    discovery_validation_events.append(
                        {"input_unit_id": unit.unit_id, "error": str(exc)[:500]}
                    )
                    if result.repaired:
                        raise ValueError(
                            "semantic Discovery remained invalid after one repair"
                        ) from exc
                    try:
                        repaired = discovery_provider.repair(
                            subject_id=f"{work.run_id}.{unit.unit_id}",
                            payload=semantic_repair_payload(
                                request_payload,
                                normalized_output,
                                validation_errors=(str(exc)[:500],),
                            ),
                            response_model=DiscoveryOutput,
                            validation_errors=(str(exc)[:240],),
                            cancel_requested=cancel_requested,
                        )
                    except StructuredProviderError as repair_exc:
                        self._state.record_provider_calls(
                            fence,
                            repair_exc.call_records,
                            cache_hit=False,
                        )
                        raise
                    self._state.record_provider_calls(
                        fence,
                        repaired.call_records,
                        cache_hit=False,
                    )
                    output = validate_discovery_output(
                        normalize_discovery(repaired.output, unit),
                        unit=unit,
                        config=semantic_config,
                    )
                write_semantic_stage_cache(
                    cache_dir=discovery_cache_dir,
                    cache_key=cache_key,
                    stage="discovery",
                    payload=request_payload,
                    provider=discovery_provider,
                    model_settings=model_settings,
                    output=output,
                )
                discovery_outputs.append(output)
                discovery_cache_hits.append(False)
            boundary_bridge_units: tuple[SemanticInputUnit, ...] = ()
            if work.config.clipping_algorithm == "semantic_windowed":
                boundary_bridge_units = plan_boundary_bridge_units(
                    transcript,
                    input_plan=input_plan,
                    discovery_outputs=tuple(discovery_outputs),
                    config=semantic_config,
                )
                for unit in boundary_bridge_units:
                    _check_cancel(cancel_requested)
                    request_payload = discovery_request_payload(
                        unit,
                        source_id=work.project_id,
                        mode=SemanticInputMode.BOUNDARY_BRIDGE,
                        config=semantic_config,
                    )
                    cache_key = semantic_stage_cache_key(
                        stage="discovery",
                        payload=request_payload,
                        provider=discovery_provider,
                        model_settings=model_settings,
                        output_model=DiscoveryOutput,
                    )
                    cached = load_semantic_stage_cache(
                        cache_dirs=(discovery_cache_dir, *fallback_discovery_cache_dirs),
                        cache_key=cache_key,
                        stage="discovery",
                        payload=request_payload,
                        provider=discovery_provider,
                        model_settings=model_settings,
                        output_model=DiscoveryOutput,
                    )
                    if cached is not None:
                        output = validate_discovery_output(
                            normalize_discovery(cached, unit),
                            unit=unit,
                            config=semantic_config,
                        )
                        discovery_outputs.append(output)
                        discovery_cache_hits.append(True)
                        continue
                    try:
                        result = discovery_provider.generate(
                            subject_id=f"{work.run_id}.{unit.unit_id}",
                            payload=request_payload,
                            response_model=DiscoveryOutput,
                            cancel_requested=cancel_requested,
                        )
                    except StructuredProviderError as exc:
                        self._state.record_provider_calls(
                            fence,
                            exc.call_records,
                            cache_hit=False,
                        )
                        raise
                    self._state.record_provider_calls(
                        fence,
                        result.call_records,
                        cache_hit=False,
                    )
                    normalized_output = normalize_discovery(result.output, unit)
                    try:
                        output = validate_discovery_output(
                            normalized_output,
                            unit=unit,
                            config=semantic_config,
                        )
                    except ValueError as exc:
                        discovery_validation_events.append(
                            {"input_unit_id": unit.unit_id, "error": str(exc)[:500]}
                        )
                        if result.repaired:
                            raise ValueError(
                                "semantic boundary bridge remained invalid after one repair"
                            ) from exc
                        repaired = discovery_provider.repair(
                            subject_id=f"{work.run_id}.{unit.unit_id}",
                            payload=semantic_repair_payload(
                                request_payload,
                                normalized_output,
                                validation_errors=(str(exc)[:500],),
                            ),
                            response_model=DiscoveryOutput,
                            validation_errors=(str(exc)[:240],),
                            cancel_requested=cancel_requested,
                        )
                        self._state.record_provider_calls(
                            fence,
                            repaired.call_records,
                            cache_hit=False,
                        )
                        output = validate_discovery_output(
                            normalize_discovery(repaired.output, unit),
                            unit=unit,
                            config=semantic_config,
                        )
                    write_semantic_stage_cache(
                        cache_dir=discovery_cache_dir,
                        cache_key=cache_key,
                        stage="discovery",
                        payload=request_payload,
                        provider=discovery_provider,
                        model_settings=model_settings,
                        output=output,
                    )
                    discovery_outputs.append(output)
                    discovery_cache_hits.append(False)
            candidates = semantic_global_output_slots(
                transcript,
                max_clips=work.config.top_n,
                minimum_duration_ms=work.config.minimum_clip_ms,
            )
            artifact_config = {
                "algorithm": work.config.clipping_algorithm,
                "profile": work.config.semantic_profile,
                "minimum_clip_ms": work.config.minimum_clip_ms,
                "target_clip_ms": work.config.semantic_target_clip_ms,
                "maximum_clip_ms": work.config.maximum_clip_ms,
                "score_threshold_exclusive": work.config.semantic_score_threshold,
                "max_clips": work.config.top_n,
            }
            semantic_global_payload = {
                "input_plan": input_plan.model_dump(mode="json"),
                "discovery_outputs": [
                    output.model_dump(mode="json") for output in discovery_outputs
                ],
                "prompt_debug": {
                    "stage": discovery_prompt.stage,
                    "profile": discovery_prompt.profile,
                    "version": f"{discovery_prompt.version}.discovery",
                    "sha256": discovery_prompt.sha256,
                    "loaded_files": list(discovery_prompt.loaded_files),
                    "tokenizer": input_plan.tokenizer_name,
                    "mode": input_plan.mode.value,
                    "prompt_tokens": input_plan.prompt_tokens,
                    "transcript_tokens": input_plan.transcript_tokens,
                    "budget_tokens": input_plan.budget_tokens,
                    "cache_hits": discovery_cache_hits,
                    "validation_events": discovery_validation_events,
                    "boundary_bridge_count": len(boundary_bridge_units),
                    "discovery_concurrency": (
                        semantic_config.window_discovery_concurrency
                        if work.config.clipping_algorithm == "semantic_windowed"
                        else 1
                    ),
                },
            }
        elif work.config.clipping_algorithm in {"b", "b_v2_experimental"}:
            target_clip_ms = (
                work.config.semantic_target_clip_ms
                if work.config.semantic_continuous_merge_enabled
                else None
            )
            candidates = generate_semantic_analysis_windows(
                transcript,
                maximum_clip_ms=work.config.maximum_clip_ms,
                minimum_clip_ms=work.config.minimum_clip_ms,
                target_clip_ms=target_clip_ms,
            )
            analysis_stride_ms = target_clip_ms or work.config.maximum_clip_ms
            artifact_config = {
                "algorithm": work.config.clipping_algorithm,
                "analysis_window_ms": work.config.maximum_clip_ms + analysis_stride_ms,
                "analysis_stride_ms": analysis_stride_ms,
                "target_clip_ms": work.config.semantic_target_clip_ms,
                "maximum_clip_ms": work.config.maximum_clip_ms,
                "minimum_clip_ms": work.config.minimum_clip_ms,
                "skill_version": work.config.semantic_skill_version,
                "skill_sha256": work.config.semantic_skill_sha256,
                "continuous_merge_enabled": work.config.semantic_continuous_merge_enabled,
                "consolidation_skill_version": (work.config.semantic_consolidation_skill_version),
                "consolidation_skill_sha256": (work.config.semantic_consolidation_skill_sha256),
            }
        else:
            config = CandidateGenerationConfig(
                minimum_duration_ms=work.config.minimum_clip_ms,
                maximum_duration_ms=work.config.maximum_clip_ms,
                rough_limit=min(200, max(40, work.config.top_n * 3)),
                top_n=work.config.top_n,
                context_ms=5_000,
                boundary_pause_ms=900,
            )
            candidates = generate_candidates(
                transcript,
                config=config,
                silence_intervals=manifest.silences,
            )
            artifact_config = {"algorithm": "a", **config.model_dump(mode="json")}
        if not candidates:
            raise ValueError("candidate analysis produced no complete transcript windows")
        artifact_payload: dict[str, object] = {
            "schema_version": "1",
            "config": artifact_config,
            "candidates": [item.model_dump(mode="json") for item in candidates],
        }
        if semantic_global_payload is not None:
            artifact_payload["semantic_global"] = semantic_global_payload
        write_json_no_clobber(
            project_dir / reservation.relative_path,
            artifact_payload,
        )
        committed = self._commit(
            lease,
            reservation,
            project_dir=project_dir,
            validation={"schema_version": "1", "candidate_count": len(candidates)},
        )
        persisted = self._state.save_candidates(
            _mutation_fence(work, lease),
            candidates=candidates,
        )
        return self._result(
            work.stage,
            (committed,),
            {"candidate_count": len(persisted)},
        )

    def _edit(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        cancel_requested: Callable[[], bool],
    ) -> StageExecutionResult:
        project_dir = project_directory(self._data_dir, work.project_id)
        generation_dir = _generation_directory(project_dir, work.generation)
        source = self._load_verified_source(work, project_dir=project_dir)
        transcript = TranscriptDocument.model_validate_json(
            self._committed_asset_bytes(
                work,
                project_dir=project_dir,
                kind="transcript_json",
                relative_path=_generation_relative(work.generation, "transcript/transcript.json"),
                max_bytes=64 * 1024 * 1024,
            )
        )
        candidates = self._state.load_candidates(run_id=work.run_id)
        by_key = {item.candidate.candidate_id: item for item in candidates}
        reservation = self._reserve(
            work,
            lease,
            kind="edit_plans",
            relative_path=_generation_relative(work.generation, "editing/edit-plans.json"),
            mime_type="application/json",
        )
        artifact_path = project_dir / reservation.relative_path
        if reservation.status == AssetStatus.COMMITTED:
            prepared = _load_prepared_revisions(
                self._committed_asset_bytes(
                    work,
                    project_dir=project_dir,
                    kind="edit_plans",
                    relative_path=reservation.relative_path,
                    max_bytes=32 * 1024 * 1024,
                )
            )
        elif artifact_path.exists() or artifact_path.is_symlink():
            try:
                pending_payload = read_regular_file_no_follow(
                    artifact_path,
                    max_bytes=32 * 1024 * 1024,
                )
            except SecureFileError as exc:
                raise ValueError("pending EditPlan artifact is symbolic or unstable") from exc
            prepared = _load_prepared_revisions(pending_payload)
        else:
            fence = _mutation_fence(work, lease)
            artifact_extra: dict[str, object] = {}
            if work.config.clipping_algorithm in {"semantic_global", "semantic_windowed"}:
                rough_payload = json.loads(
                    self._committed_asset_bytes(
                        work,
                        project_dir=project_dir,
                        kind="rough_candidates",
                        relative_path=_generation_relative(
                            work.generation,
                            "candidates/rough-candidates.json",
                        ),
                        max_bytes=64 * 1024 * 1024,
                    )
                )
                if not isinstance(rough_payload, dict) or not isinstance(
                    rough_payload.get("semantic_global"),
                    dict,
                ):
                    raise ValueError("semantic global Discovery artifact is missing")
                global_artifact = rough_payload["semantic_global"]
                input_plan = SemanticInputPlan.model_validate_json(
                    json.dumps(global_artifact.get("input_plan"), ensure_ascii=False)
                )
                raw_discovery = global_artifact.get("discovery_outputs")
                if not isinstance(raw_discovery, list):
                    raise ValueError("semantic global Discovery outputs are missing")
                discovery_outputs = tuple(
                    DiscoveryOutput.model_validate_json(json.dumps(value, ensure_ascii=False))
                    for value in raw_discovery
                )
                semantic_config = _semantic_global_config(work)
                global_prompt = load_semantic_global_prompt(
                    "global_review",
                    work.config.semantic_profile,
                )
                _assert_semantic_global_prompt(work, global_prompt)
                global_payload = build_global_review_payload(
                    transcript,
                    input_plan=input_plan,
                    discovery_outputs=discovery_outputs,
                    config=semantic_config,
                    prompt=global_prompt.instructions,
                )
                global_input_tokens = semantic_request_tokens(
                    global_prompt.instructions,
                    global_payload,
                    config=semantic_config,
                )
                global_provider = self._structured_provider(work, global_prompt)
                global_validation_events: list[dict[str, str]] = []
                model_settings = _semantic_model_settings(work)
                global_cache_dir = generation_dir / "editing/semantic-cache/global_review"
                global_cache_key = semantic_stage_cache_key(
                    stage="global_review",
                    payload=global_payload,
                    provider=global_provider,
                    model_settings=model_settings,
                    output_model=GlobalReviewOutput,
                )
                cached_global = load_semantic_stage_cache(
                    cache_dirs=(
                        global_cache_dir,
                        *(
                            project_dir
                            / _generation_relative(
                                generation,
                                "editing/semantic-cache/global_review",
                            )
                            for generation in range(1, work.generation)
                        ),
                    ),
                    cache_key=global_cache_key,
                    stage="global_review",
                    payload=global_payload,
                    provider=global_provider,
                    model_settings=model_settings,
                    output_model=GlobalReviewOutput,
                )
                global_cache_hit = cached_global is not None
                if cached_global is not None:
                    global_output = cached_global
                    validated = validate_global_review(
                        global_output,
                        transcript=transcript,
                        discovery_outputs=discovery_outputs,
                        config=semantic_config,
                        input_mode=input_plan.mode,
                    )
                else:
                    try:
                        result = global_provider.generate(
                            subject_id=work.run_id,
                            payload=global_payload,
                            response_model=GlobalReviewOutput,
                            cancel_requested=cancel_requested,
                        )
                    except StructuredProviderError as exc:
                        self._state.record_provider_calls(
                            fence,
                            exc.call_records,
                            cache_hit=False,
                        )
                        raise
                    self._state.record_provider_calls(
                        fence,
                        result.call_records,
                        cache_hit=False,
                    )
                    try:
                        global_output = result.output
                        validated = validate_global_review(
                            global_output,
                            transcript=transcript,
                            discovery_outputs=discovery_outputs,
                            config=semantic_config,
                            input_mode=input_plan.mode,
                        )
                    except ValueError as exc:
                        global_validation_events.append(
                            {"stage": "global_review", "error": str(exc)[:500]}
                        )
                        if result.repaired:
                            raise ValueError(
                                "semantic Global Review remained invalid after one repair"
                            ) from exc
                        try:
                            repaired = global_provider.repair(
                                subject_id=work.run_id,
                                payload=semantic_repair_payload(
                                    global_payload,
                                    result.output,
                                    validation_errors=(str(exc)[:500],),
                                ),
                                response_model=GlobalReviewOutput,
                                validation_errors=(str(exc)[:240],),
                                cancel_requested=cancel_requested,
                            )
                        except StructuredProviderError as repair_exc:
                            self._state.record_provider_calls(
                                fence,
                                repair_exc.call_records,
                                cache_hit=False,
                            )
                            raise
                        self._state.record_provider_calls(
                            fence,
                            repaired.call_records,
                            cache_hit=False,
                        )
                        global_output = repaired.output
                        validated = validate_global_review(
                            global_output,
                            transcript=transcript,
                            discovery_outputs=discovery_outputs,
                            config=semantic_config,
                            input_mode=input_plan.mode,
                        )
                    write_semantic_stage_cache(
                        cache_dir=global_cache_dir,
                        cache_key=global_cache_key,
                        stage="global_review",
                        payload=global_payload,
                        provider=global_provider,
                        model_settings=model_settings,
                        output=global_output,
                    )
                if len(validated.selected) > len(candidates):
                    raise ValueError(
                        "semantic global selected more clips than persisted output slots"
                    )
                prepared_values: list[PreparedRevision] = []
                created_at = datetime.now(UTC)
                for rank, (selected, slot) in enumerate(
                    zip(validated.selected, candidates, strict=False),
                    start=1,
                ):
                    _check_cancel(cancel_requested)
                    plan = EditPlan(
                        candidate_id=slot.candidate.candidate_id,
                        source_start_ms=selected.start_ms,
                        source_end_ms=selected.end_ms,
                        score=float(selected.final_score),
                        title=selected.clip.title,
                        hook=selected.clip.hook[:80],
                        reason=selected.clip.review_reason[:240],
                        layout=Layout.CENTER_CROP,
                        caption_template=CaptionTemplate.CLEAN_ZH_V1,
                        effect=Effect.NONE,
                        risk_flags=tuple(
                            dict.fromkeys(risk.type.value for risk in selected.clip.risks)
                        ),
                        prompt_version=f"{global_prompt.version}.global_review",
                        model=global_provider.model_name,
                        degraded=False,
                    )
                    captions = captions_for_clip(
                        transcript.segments,
                        source_start_ms=plan.source_start_ms,
                        source_end_ms=plan.source_end_ms,
                    )
                    prepared_values.append(
                        PreparedRevision(
                            candidate_id=slot.candidate_id,
                            rank=rank,
                            revision=EditPlanRevision(
                                clip_id=slot.candidate_id,
                                revision=1,
                                origin=RevisionOrigin.AI,
                                plan=plan,
                                captions=captions,
                                created_at=created_at,
                            ),
                        )
                    )
                prepared = tuple(prepared_values)
                artifact_extra = {
                    "semantic_global": {
                        "raw_global_review": global_output.model_dump(mode="json"),
                        "validated": {
                            "selected": [
                                _validated_global_clip_payload(value)
                                for value in validated.selected
                            ],
                            "manual_review": [
                                _validated_global_clip_payload(value)
                                for value in validated.manual_review
                            ],
                            "rejected": [
                                _validated_global_clip_payload(value)
                                for value in validated.rejected
                            ],
                            "rejected_candidates": [
                                value.model_dump(mode="json")
                                for value in validated.rejected_candidates
                            ],
                            "coverage_decisions": [
                                value.model_dump(mode="json")
                                for value in validated.coverage_decisions
                            ],
                            "global_review_summary": (
                                validated.global_review_summary.model_dump(mode="json")
                            ),
                            "validation_notes": list(validated.validation_notes),
                        },
                        "prompt_debug": {
                            "stage": global_prompt.stage,
                            "profile": global_prompt.profile,
                            "version": f"{global_prompt.version}.global_review",
                            "sha256": global_prompt.sha256,
                            "loaded_files": list(global_prompt.loaded_files),
                            "input_mode": str(global_payload["mode"]),
                            "estimated_total_tokens": global_input_tokens,
                            "cache_hit": global_cache_hit,
                            "validation_events": global_validation_events,
                        },
                    }
                }
            else:
                editor = self._llm_provider(work)
                if work.config.clipping_algorithm in {"b", "b_v2_experimental"}:
                    consolidation_editor = (
                        self._llm_provider(
                            work,
                            semantic_prompts=load_semantic_continuous_skill(),
                            enforce_persisted_prompt=False,
                        )
                        if work.config.semantic_continuous_merge_enabled
                        else None
                    )
                    semantic_selection = select_semantic_clips(
                        editor,
                        tuple(item.candidate for item in candidates),
                        transcript=transcript,
                        source_duration_ms=source.duration_ms,
                        minimum_duration_ms=work.config.minimum_clip_ms,
                        maximum_duration_ms=work.config.maximum_clip_ms,
                        top_n=work.config.top_n,
                        score_threshold=work.config.semantic_score_threshold,
                        cache_dir=generation_dir / "editing" / "semantic-cache",
                        target_duration_ms=work.config.semantic_target_clip_ms,
                        continuous_merge_enabled=work.config.semantic_continuous_merge_enabled,
                        consolidation_provider=consolidation_editor,
                        consolidation_cache_dir=(
                            generation_dir / "editing" / "continuous-cache"
                            if consolidation_editor is not None
                            else None
                        ),
                        cancel_requested=cancel_requested,
                        on_call_records=lambda records, cache_hit: (
                            self._state.record_provider_calls(
                                fence,
                                records,
                                cache_hit=cache_hit,
                            )
                        ),
                    )
                    selected_edits = semantic_selection.selected
                else:
                    classic_editing = edit_and_rank_candidates(
                        editor,
                        tuple(item.candidate for item in candidates),
                        source_duration_ms=source.duration_ms,
                        minimum_duration_ms=work.config.minimum_clip_ms,
                        maximum_duration_ms=work.config.maximum_clip_ms,
                        top_n=work.config.top_n,
                        cache_dir=generation_dir / "editing" / "cache",
                        cancel_requested=cancel_requested,
                        on_call_records=lambda records, cache_hit: (
                            self._state.record_provider_calls(
                                fence,
                                records,
                                cache_hit=cache_hit,
                            )
                        ),
                    )
                    selected_edits = classic_editing.selected
                prepared_values = []
                created_at = datetime.now(UTC)
                for rank, edited in enumerate(selected_edits, start=1):
                    _check_cancel(cancel_requested)
                    item = by_key[edited.candidate.candidate_id]
                    plan = edited.result.plan
                    captions = captions_for_clip(
                        transcript.segments,
                        source_start_ms=plan.source_start_ms,
                        source_end_ms=plan.source_end_ms,
                    )
                    prepared_values.append(
                        PreparedRevision(
                            candidate_id=item.candidate_id,
                            rank=rank,
                            revision=EditPlanRevision(
                                clip_id=item.candidate_id,
                                revision=1,
                                origin=(
                                    RevisionOrigin.DETERMINISTIC
                                    if plan.degraded
                                    else RevisionOrigin.AI
                                ),
                                plan=plan,
                                captions=captions,
                                created_at=created_at,
                            ),
                        )
                    )
                prepared = tuple(prepared_values)
            write_json_no_clobber(
                artifact_path,
                {
                    "schema_version": "1",
                    "revisions": [_prepared_payload(value) for value in prepared],
                    **artifact_extra,
                },
            )
        prepared_ids = [item.candidate_id for item in prepared]
        expected_count = (
            len(prepared)
            if work.config.clipping_algorithm
            in {
                "b",
                "b_v2_experimental",
                "semantic_global",
                "semantic_windowed",
            }
            else min(work.config.top_n, len(candidates))
        )
        if (
            len(prepared_ids) != expected_count
            or len(set(prepared_ids)) != len(prepared_ids)
            or not set(prepared_ids).issubset({item.candidate_id for item in candidates})
            or sorted(item.rank for item in prepared) != list(range(1, expected_count + 1))
        ):
            raise ValueError("persisted edit selection differs from current rough candidate set")
        committed = self._commit(
            lease,
            reservation,
            project_dir=project_dir,
            validation={"schema_version": "1", "selected_count": len(prepared)},
        )
        revisions = self._state.save_revisions(_mutation_fence(work, lease), prepared)
        return self._result(
            work.stage,
            (committed,),
            {
                "clip_ids": [item.candidate_id for item in revisions],
                "selected_count": len(revisions),
            },
        )

    def _asr_provider(
        self, work: StageWork
    ) -> MockASRProvider | OpenAIASRProvider | OpenRouterASRProvider:
        if work.config.provider in {"mock", "mock-codex"}:
            provider: MockASRProvider | OpenAIASRProvider | OpenRouterASRProvider = MockASRProvider(
                model_name=work.config.transcription_model
            )
        elif work.config.provider == "openrouter-codex":
            provider = OpenRouterASRProvider(
                api_key=self._openrouter_api_key,
                model_name=work.config.transcription_model,
                base_url=self._openrouter_base_url,
                timeout_seconds=work.config.openai_request_timeout_seconds,
                retry_policy=_retry_policy(work),
            )
        else:
            provider = OpenAIASRProvider(
                api_key=self._openai_api_key,
                model_name=work.config.transcription_model,
                timeout_seconds=work.config.openai_request_timeout_seconds,
                retry_policy=_retry_policy(work),
            )
        if provider.contract_version != work.config.asr_contract_version:
            raise ProviderConfigurationError(
                "persisted ASR contract no longer matches the installed provider"
            )
        return provider

    def _llm_provider(
        self,
        work: StageWork,
        *,
        semantic_prompts: EditingPromptBundle | None = None,
        enforce_persisted_prompt: bool = True,
    ) -> MockLLMProvider | OpenAILLMProvider | CodexCLILLMProvider:
        if semantic_prompts is None and work.config.clipping_algorithm in {
            "b",
            "b_v2_experimental",
        }:
            semantic_prompts = load_semantic_discovery_skill(work.config.semantic_skill_version)
        if (
            semantic_prompts is not None
            and enforce_persisted_prompt
            and (
                semantic_prompts.version,
                semantic_prompts.sha256,
            )
            != (
                work.config.semantic_skill_version,
                work.config.semantic_skill_sha256,
            )
        ):
            raise ProviderConfigurationError(
                "persisted semantic clipping Skill no longer matches the installed Skill"
            )
        if (
            semantic_prompts is not None
            and not enforce_persisted_prompt
            and (
                semantic_prompts.version,
                semantic_prompts.sha256,
            )
            != (
                work.config.semantic_consolidation_skill_version,
                work.config.semantic_consolidation_skill_sha256,
            )
        ):
            raise ProviderConfigurationError(
                "persisted semantic consolidation Skill no longer matches the installed Skill"
            )
        if work.config.provider == "mock":
            provider: MockLLMProvider | OpenAILLMProvider | CodexCLILLMProvider = MockLLMProvider(
                model_name=work.config.llm_model,
                prompt_version=(semantic_prompts.version if semantic_prompts else "editing_v1"),
                prompt_sha256=(semantic_prompts.sha256 if semantic_prompts else None),
            )
        elif work.config.provider in {"mock-codex", "openai-codex", "openrouter-codex"}:
            provider = CodexCLILLMProvider(
                model_name=work.config.llm_model,
                codex_executable=self._codex_executable,
                timeout_seconds=work.config.openai_request_timeout_seconds,
                contract_version=work.config.llm_contract_version,
                prompts=semantic_prompts,
            )
        else:
            provider = OpenAILLMProvider(
                api_key=self._openai_api_key,
                model_name=work.config.llm_model,
                timeout_seconds=work.config.openai_request_timeout_seconds,
                retry_policy=_retry_policy(work),
                input_price_per_million=work.config.llm_input_price_per_million,
                output_price_per_million=work.config.llm_output_price_per_million,
                prompts=semantic_prompts,
            )
        expected = (
            provider.contract_version,
            provider.prompt_version,
            provider.prompt_sha256,
            EDITORIAL_SUGGESTION_SCHEMA_VERSION,
            EDIT_PLAN_PIPELINE_CONTRACT_VERSION,
        )
        persisted = (
            work.config.llm_contract_version,
            work.config.editing_prompt_version,
            work.config.editing_prompt_sha256,
            work.config.editorial_schema_version,
            work.config.edit_plan_schema_version,
        )
        if enforce_persisted_prompt and expected != persisted:
            raise ProviderConfigurationError(
                "persisted editing contract no longer matches the installed provider"
            )
        if not enforce_persisted_prompt and (
            provider.contract_version,
            EDITORIAL_SUGGESTION_SCHEMA_VERSION,
            EDIT_PLAN_PIPELINE_CONTRACT_VERSION,
        ) != (
            work.config.llm_contract_version,
            work.config.editorial_schema_version,
            work.config.edit_plan_schema_version,
        ):
            raise ProviderConfigurationError(
                "persisted consolidation contract no longer matches the installed provider"
            )
        return provider

    def _structured_provider(
        self,
        work: StageWork,
        prompts: SemanticGlobalPromptBundle,
    ) -> StructuredLLMProvider:
        if work.config.provider == "mock":
            return MockStructuredLLMProvider(
                prompts=prompts,
                model_name=work.config.llm_model,
            )
        if work.config.provider in {"mock-codex", "openai-codex", "openrouter-codex"}:
            return CodexStructuredLLMProvider(
                prompts=prompts,
                model_name=work.config.llm_model,
                codex_executable=self._codex_executable,
                timeout_seconds=work.config.openai_request_timeout_seconds,
                contract_version=work.config.llm_contract_version,
            )
        return OpenAIStructuredLLMProvider(
            prompts=prompts,
            model_name=work.config.llm_model,
            api_key=self._openai_api_key,
            timeout_seconds=work.config.openai_request_timeout_seconds,
            retry_policy=_retry_policy(work),
        )

    def _proxy_render(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        cancel_requested: Callable[[], bool],
    ) -> StageExecutionResult:
        project_dir = project_directory(self._data_dir, work.project_id)
        attempt_dir = attempt_directory(project_dir, lease)
        source = self._load_verified_source(work, project_dir=project_dir)
        revisions = self._state.load_current_revisions(run_id=work.run_id)
        prepared = _load_prepared_revisions(
            self._committed_asset_bytes(
                work,
                project_dir=project_dir,
                kind="edit_plans",
                relative_path=_generation_relative(work.generation, "editing/edit-plans.json"),
                max_bytes=32 * 1024 * 1024,
            )
        )
        if tuple((item.candidate_id, item.revision) for item in prepared) != tuple(
            (item.candidate_id, item.revision) for item in revisions
        ):
            raise ValueError("persisted revisions differ from their committed EditPlan Asset")
        if (
            work.config.clipping_algorithm in {"semantic_global", "semantic_windowed"}
            and work.config.semantic_no_render
        ):
            reservation = self._reserve(
                work,
                lease,
                # A zero-render proxy checkpoint already has a stable repository
                # contract: one ``no_review_clips`` manifest and no RenderJob rows.
                # Reuse that artifact kind while recording the explicit dry-run
                # reason inside the immutable manifest.
                kind="no_review_clips",
                relative_path=_generation_relative(
                    work.generation,
                    "renders/no-render-plan.json",
                ),
                mime_type="application/json",
            )
            write_json_no_clobber(
                project_dir / reservation.relative_path,
                {
                    "schema_version": "1",
                    "algorithm": work.config.clipping_algorithm,
                    "reason": "explicit_no_render",
                    "selected_plan_count": len(revisions),
                },
            )
            committed = self._commit(
                lease,
                reservation,
                project_dir=project_dir,
                validation={
                    "schema_version": "1",
                    "selected_plan_count": len(revisions),
                },
            )
            return self._result(
                work.stage,
                (committed,),
                {"render_ids": [], "proxy_count": 0},
            )
        if not revisions:
            if work.config.clipping_algorithm not in {
                "b",
                "b_v2_experimental",
                "semantic_global",
                "semantic_windowed",
            }:
                raise ValueError("proxy rendering has no selected EditPlan revisions")
            reservation = self._reserve(
                work,
                lease,
                kind="no_review_clips",
                relative_path=_generation_relative(
                    work.generation,
                    "renders/no-review-clips.json",
                ),
                mime_type="application/json",
            )
            write_json_no_clobber(
                project_dir / reservation.relative_path,
                {
                    "schema_version": "1",
                    "algorithm": work.config.clipping_algorithm,
                    "selected_count": 0,
                    "reason": "no_agent_proposal_above_threshold",
                    "score_threshold_exclusive": work.config.semantic_score_threshold,
                },
            )
            committed = self._commit(
                lease,
                reservation,
                project_dir=project_dir,
                validation={"schema_version": "1", "selected_count": 0},
            )
            return self._result(
                work.stage,
                (committed,),
                {"render_ids": [], "proxy_count": 0},
            )
        try:
            with open_pinned_regular_file(source.resolved_path) as pinned:
                _validate_pinned_pipeline_source(
                    source,
                    pinned,
                    cancel_requested=cancel_requested,
                )
                result = self._proxy_render_with_source(
                    work,
                    lease,
                    cancel_requested,
                    project_dir=project_dir,
                    attempt_dir=attempt_dir,
                    source=source,
                    revisions=revisions,
                    pinned=pinned,
                )
                _validate_pinned_pipeline_source_binding(
                    source,
                    pinned,
                    cancel_requested=cancel_requested,
                )
                return result
        except InterruptedError as exc:
            raise StageCancelled("proxy source validation was cancelled") from exc
        except SecureFileError as exc:
            raise ValueError("source media changed before proxy publication") from exc

    def _proxy_render_with_source(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        cancel_requested: Callable[[], bool],
        *,
        project_dir: Path,
        attempt_dir: Path,
        source: SourceMediaMetadata,
        revisions: tuple[PersistedRevision, ...],
        pinned: PinnedRegularFile,
    ) -> StageExecutionResult:
        all_assets: list[AssetReservation] = []
        render_ids: list[str] = []
        attempt_diagnostics: list[dict[str, object]] = []
        for item in revisions:
            _check_cancel(cancel_requested)
            spec_fingerprint = _render_spec_fingerprint(
                item.revision,
                width=work.config.preview_width,
                height=work.config.preview_height,
                encoder=work.config.video_encoder,
                video_stream_index=source.video_stream_index,
                audio_stream_index=source.audio_stream_index,
            )
            render_id = self._state.start_proxy_render(
                _mutation_fence(work, lease),
                ProxyRenderIntent(
                    candidate_id=item.candidate_id,
                    edit_plan_revision_id=item.edit_plan_revision_id,
                    edit_plan_revision=item.revision.revision,
                    revision_epoch=work.revision_epoch,
                    width=work.config.preview_width,
                    height=work.config.preview_height,
                    spec_fingerprint=spec_fingerprint,
                ),
            )
            base_relative = _generation_relative(
                work.generation,
                f"renders/proxies/{item.candidate_id}/r{item.revision.revision:03d}",
            )
            video_relative = f"{base_relative}/review.mp4"
            subtitle_relative = f"{base_relative}/review.srt"
            quality_relative = f"{base_relative}/review-quality/quality-report.json"
            contact_relative = f"{base_relative}/review-quality/contact-sheet.png"
            video_reservation = self._reserve(
                work,
                lease,
                kind="review_proxy",
                relative_path=video_relative,
                mime_type="video/mp4",
                input_fingerprint=spec_fingerprint,
                candidate_id=item.candidate_id,
                edit_plan_revision=item.revision.revision,
                revision_epoch=work.revision_epoch,
            )
            subtitle_reservation = self._reserve(
                work,
                lease,
                kind="clip_subtitle_srt",
                relative_path=subtitle_relative,
                mime_type="application/x-subrip",
                input_fingerprint=spec_fingerprint,
                candidate_id=item.candidate_id,
                edit_plan_revision=item.revision.revision,
                revision_epoch=work.revision_epoch,
            )
            quality_reservation = self._reserve(
                work,
                lease,
                kind="render_quality_report",
                relative_path=quality_relative,
                mime_type="application/json",
                input_fingerprint=spec_fingerprint,
                candidate_id=item.candidate_id,
                edit_plan_revision=item.revision.revision,
                revision_epoch=work.revision_epoch,
            )
            contact_reservation = self._reserve(
                work,
                lease,
                kind="render_contact_sheet",
                relative_path=contact_relative,
                mime_type="image/png",
                input_fingerprint=spec_fingerprint,
                candidate_id=item.candidate_id,
                edit_plan_revision=item.revision.revision,
                revision_epoch=work.revision_epoch,
            )
            canonical_video = project_dir / video_relative
            canonical_subtitle = project_dir / subtitle_relative
            canonical_quality = project_dir / quality_relative
            canonical_contact = project_dir / contact_relative
            if not canonical_video.is_file():
                attempt_video = attempt_dir / video_relative
                _validate_pinned_pipeline_source_binding(
                    source,
                    pinned,
                    cancel_requested=cancel_requested,
                )
                artifact = render_edit_plan_revision(
                    source_path=pinned.process_path,
                    revision=item.revision,
                    output_path=attempt_video,
                    width=work.config.preview_width,
                    height=work.config.preview_height,
                    encoder=work.config.video_encoder,
                    text_mode=RenderTextMode.NONE,
                    video_stream_index=source.video_stream_index,
                    audio_stream_index=source.audio_stream_index,
                    source_pass_fds=pinned.pass_fds,
                    cancel_requested=cancel_requested,
                )
                _validate_pinned_pipeline_source_binding(
                    source,
                    pinned,
                    cancel_requested=cancel_requested,
                )
                report_payload = artifact.quality.as_dict()
                attempt_diagnostics.append(
                    {
                        "candidate_id": item.candidate_id,
                        "renderer": artifact.diagnostic_payload,
                    }
                )
                validated_video_sha256 = publish_file_no_clobber(
                    artifact.output_path,
                    canonical_video,
                    expected_sha256=artifact.sha256,
                )
                validated_contact_sha256 = publish_file_no_clobber(
                    artifact.contact_sheet_path,
                    canonical_contact,
                    expected_sha256=artifact.contact_sheet_sha256,
                )
                validated_quality_sha256 = _write_canonical_quality_report(
                    canonical_quality,
                    report_payload,
                    media_path=canonical_video,
                    contact_sheet=canonical_contact,
                )
            else:
                _check_cancel(cancel_requested)
                _validate_pinned_pipeline_source_binding(
                    source,
                    pinned,
                    cancel_requested=cancel_requested,
                )
                recovery_root = attempt_dir / base_relative / "recovery"
                overlays = render_revision_overlays_for_mode(
                    revision=item.revision,
                    output_dir=recovery_root / "overlays",
                    width=work.config.preview_width,
                    height=work.config.preview_height,
                    text_mode=RenderTextMode.NONE,
                )
                quality = validate_rendered_media(
                    media_path=canonical_video,
                    expected_width=work.config.preview_width,
                    expected_height=work.config.preview_height,
                    expected_duration_ms=item.revision.plan.duration_ms,
                    output_dir=recovery_root / "quality",
                    safe_bounds=tuple(value.safe_bounds for value in overlays),
                    cancel_requested=cancel_requested,
                )
                recovery_contact = Path(quality.contact_sheet)
                try:
                    recovery_contact_sha256, _contact_size = hash_regular_file_no_follow(
                        recovery_contact
                    )
                except SecureFileError as exc:
                    raise ValueError("proxy recovery contact sheet changed") from exc
                validated_video_sha256 = quality.media_sha256
                validated_contact_sha256 = publish_file_no_clobber(
                    recovery_contact,
                    canonical_contact,
                    expected_sha256=recovery_contact_sha256,
                )
                attempt_diagnostics.append(
                    {
                        "candidate_id": item.candidate_id,
                        "renderer": {
                            "schema_version": "1",
                            "attempt_count": 0,
                            "recovery": "validated_existing_immutable_video",
                        },
                    }
                )
                validated_quality_sha256 = _write_canonical_quality_report(
                    canonical_quality,
                    quality.as_dict(),
                    media_path=canonical_video,
                    contact_sheet=canonical_contact,
                )
            validated_subtitle_sha256 = write_text_no_clobber(
                canonical_subtitle,
                captions_to_srt(item.revision.captions),
            )
            committed_video = self._commit(
                lease,
                video_reservation,
                project_dir=project_dir,
                validation={
                    "schema_version": "1",
                    "width": work.config.preview_width,
                    "height": work.config.preview_height,
                    "full_decode": "passed",
                },
                expected_sha256=validated_video_sha256,
            )
            committed_subtitle = self._commit(
                lease,
                subtitle_reservation,
                project_dir=project_dir,
                validation={
                    "schema_version": "1",
                    "timeline": "clip_relative_ms",
                    "cue_count": len(item.revision.captions),
                },
                expected_sha256=validated_subtitle_sha256,
            )
            committed_quality = self._commit(
                lease,
                quality_reservation,
                project_dir=project_dir,
                validation={"schema_version": "1", "automatic_status": "passed"},
                expected_sha256=validated_quality_sha256,
            )
            committed_contact = self._commit(
                lease,
                contact_reservation,
                project_dir=project_dir,
                validation={"schema_version": "1", "frames": 3},
                expected_sha256=validated_contact_sha256,
            )
            render_ids.append(
                self._state.save_proxy_render(
                    _mutation_fence(work, lease),
                    render_id,
                    ProxyRenderPersistence(
                        candidate_id=item.candidate_id,
                        edit_plan_revision_id=item.edit_plan_revision_id,
                        edit_plan_revision=item.revision.revision,
                        revision_epoch=work.revision_epoch,
                        width=work.config.preview_width,
                        height=work.config.preview_height,
                        spec_fingerprint=spec_fingerprint,
                        video_asset_id=committed_video.asset_id,
                        subtitle_asset_id=committed_subtitle.asset_id,
                        quality_report_asset_id=committed_quality.asset_id,
                        contact_sheet_asset_id=committed_contact.asset_id,
                    ),
                )
            )
            all_assets.extend(
                (committed_video, committed_subtitle, committed_quality, committed_contact)
            )
        diagnostic_relative_path = _write_stage_render_diagnostic(
            project_dir=project_dir,
            attempt_dir=attempt_dir,
            status="succeeded",
            renderers=attempt_diagnostics,
        )
        cleanup_attempt_worktree(
            project_dir,
            task_id=lease.task_id,
            lease_token=lease.lease_token,
            preserve_diagnostics=True,
        )
        return self._result(
            work.stage,
            tuple(all_assets),
            {"proxy_count": len(render_ids), "render_ids": render_ids},
            diagnostic_relative_path=diagnostic_relative_path,
        )

    def _committed_assets(
        self,
        work: StageWork,
        *,
        kinds: tuple[str, ...],
    ) -> tuple[CommittedStageAsset, ...]:
        return self._state.load_committed_assets(
            project_id=work.project_id,
            run_id=work.run_id,
            generation=work.generation,
            kinds=kinds,
        )

    def _committed_asset_bytes(
        self,
        work: StageWork,
        *,
        project_dir: Path,
        kind: str,
        relative_path: str,
        max_bytes: int,
    ) -> bytes:
        assets = self._committed_assets(work, kinds=(kind,))
        if len(assets) != 1 or assets[0].relative_path != relative_path:
            raise ValueError(f"committed {kind} dependency does not match its canonical path")
        return _read_verified_committed_asset(
            project_dir=project_dir,
            asset=assets[0],
            max_bytes=max_bytes,
        )

    def _load_verified_source(
        self,
        work: StageWork,
        *,
        project_dir: Path,
    ) -> SourceMediaMetadata:
        relative_path = _generation_relative(work.generation, "source/source-media.json")
        source_from_asset = SourceMediaMetadata.model_validate_json(
            self._committed_asset_bytes(
                work,
                project_dir=project_dir,
                kind="source_metadata",
                relative_path=relative_path,
                max_bytes=1024 * 1024,
            )
        )
        source = self._state.load_source(project_id=work.project_id)
        if source != source_from_asset:
            raise ValueError("source database state differs from its committed metadata asset")
        return source

    def _reserve(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        *,
        kind: str,
        relative_path: str,
        mime_type: str,
        input_fingerprint: str | None = None,
        candidate_id: str | None = None,
        edit_plan_revision: int | None = None,
        revision_epoch: int | None = None,
    ) -> AssetReservation:
        return self._assets.reserve(
            lease,
            project_id=work.project_id,
            kind=kind,
            relative_path=relative_path,
            mime_type=mime_type,
            input_fingerprint=input_fingerprint or work.input_fingerprint,
            generation=work.generation,
            candidate_id=candidate_id,
            edit_plan_revision=edit_plan_revision,
            revision_epoch=revision_epoch,
        )

    def _commit(
        self,
        lease: LeaseIdentity,
        reservation: AssetReservation,
        *,
        project_dir: Path,
        validation: dict[str, object],
        expected_sha256: str | None = None,
    ) -> AssetReservation:
        return self._assets.commit(
            lease,
            reservation,
            project_dir=project_dir,
            validation=validation,
            expected_sha256=expected_sha256,
        )

    @staticmethod
    def _result(
        stage: PipelineStage,
        assets: tuple[AssetReservation, ...],
        checkpoint: dict[str, object],
        *,
        diagnostic_relative_path: str | None = None,
    ) -> StageExecutionResult:
        asset_ids = [asset.asset_id for asset in assets]
        hashes = tuple(asset.sha256 for asset in assets if asset.sha256 is not None)
        if len(hashes) != len(assets):
            raise ValueError("stage result contains an uncommitted asset")
        return StageExecutionResult(
            output_fingerprint=stage_output_fingerprint(stage, hashes),
            checkpoint={**checkpoint, "asset_ids": asset_ids},
            diagnostic_relative_path=diagnostic_relative_path,
        )


def _read_verified_committed_asset(
    *,
    project_dir: Path,
    asset: CommittedStageAsset,
    max_bytes: int,
) -> bytes:
    relative = PurePosixPath(asset.relative_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError("committed asset path is unsafe")
    if asset.size_bytes > max_bytes:
        raise ValueError("committed dependency exceeds its bounded read limit")
    path = project_dir.joinpath(*relative.parts)
    try:
        payload = read_regular_file_no_follow(path, max_bytes=max_bytes)
    except SecureFileError as exc:
        raise ValueError("committed dependency is missing, symbolic, or unstable") from exc
    if len(payload) != asset.size_bytes or hashlib.sha256(payload).hexdigest() != asset.sha256:
        raise ValueError("committed dependency bytes differ from their Asset SHA-256")
    return payload


def _validate_audio_chunk_assets(
    *,
    project_dir: Path,
    manifest: AudioChunkManifest,
    assets: tuple[CommittedStageAsset, ...],
    cancel_requested: Callable[[], bool],
) -> None:
    if len(assets) != len(manifest.chunks):
        raise ValueError("audio chunk Asset count differs from its committed manifest")
    by_path: dict[Path, CommittedStageAsset] = {}
    for asset in assets:
        relative = PurePosixPath(asset.relative_path)
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise ValueError("audio chunk Asset path is unsafe")
        path = project_dir.joinpath(*relative.parts)
        if path in by_path:
            raise ValueError("audio chunk Assets contain a duplicate path")
        by_path[path] = asset
    consumed: set[Path] = set()
    for chunk in manifest.chunks:
        _check_cancel(cancel_requested)
        bound_asset = by_path.get(chunk.path)
        if bound_asset is None or chunk.path in consumed:
            raise ValueError("audio manifest path is not a committed chunk Asset")
        if chunk.size_bytes != bound_asset.size_bytes or chunk.sha256 != bound_asset.sha256:
            raise ValueError("audio manifest metadata differs from its committed chunk Asset")
        try:
            observed_sha256, observed_size = hash_regular_file_no_follow(
                chunk.path,
                cancel_requested=cancel_requested,
            )
        except InterruptedError as exc:
            raise StageCancelled("audio chunk integrity verification was cancelled") from exc
        except SecureFileError as exc:
            raise ValueError("audio chunk is missing, symbolic, or unstable") from exc
        if observed_size != bound_asset.size_bytes or observed_sha256 != bound_asset.sha256:
            raise ValueError("audio chunk bytes differ from their committed Asset SHA-256")
        consumed.add(chunk.path)
    if consumed != set(by_path):
        raise ValueError("audio manifest did not consume every committed chunk Asset")


def _check_cancel(cancel_requested: Callable[[], bool]) -> None:
    if cancel_requested():
        raise StageCancelled("stage cancellation was requested")


def _safe_exception_site(error: BaseException) -> str:
    """Return code-location evidence without logging model or media payloads."""

    frames = traceback.extract_tb(error.__traceback__)
    if not frames:
        return "unavailable"
    frame = frames[-1]
    return f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"[:200]


def _persist_stage_validation_diagnostic(
    *,
    data_dir: Path | None,
    work: StageWork,
    lease: LeaseIdentity,
    error: BaseException,
) -> str | None:
    """Persist payload-free debugging evidence for deterministic local rejection."""

    if data_dir is None:
        return None
    try:
        project_dir = project_directory(data_dir, work.project_id)
        diagnostic_path = (
            attempt_directory(project_dir, lease) / "diagnostics" / "stage-validation.json"
        )
        write_json_no_clobber(
            diagnostic_path,
            {
                "schema_version": "1",
                "stage": work.stage.value,
                "error_class": type(error).__name__,
                "error_site": _safe_exception_site(error),
            },
            max_bytes=16 * 1024,
        )
        return diagnostic_path.relative_to(project_dir).as_posix()
    except (ArtifactPublicationError, OSError, ValueError) as persistence_error:
        logger.warning(
            "stage validation diagnostic persistence failed error_class=%s",
            type(persistence_error).__name__,
        )
        return None


def _validate_pinned_pipeline_source(
    source: SourceMediaMetadata,
    pinned: PinnedRegularFile,
    *,
    cancel_requested: Callable[[], bool],
) -> None:
    _check_cancel(cancel_requested)
    metadata = pinned.metadata
    observed = (
        pinned.path,
        metadata.st_size,
        metadata.st_mtime_ns,
        getattr(metadata, "st_ino", None),
        getattr(metadata, "st_dev", None),
    )
    expected = (
        source.resolved_path,
        source.size_bytes,
        source.mtime_ns,
        source.inode,
        source.device,
    )
    if observed != expected or pinned.sha256(cancel_requested=cancel_requested) != source.sha256:
        raise ValueError("source media changed after import")
    pinned.validate_binding()


def _validate_pinned_pipeline_source_binding(
    source: SourceMediaMetadata,
    pinned: PinnedRegularFile,
    *,
    cancel_requested: Callable[[], bool],
) -> None:
    _check_cancel(cancel_requested)
    metadata = pinned.metadata
    observed = (
        pinned.path,
        metadata.st_size,
        metadata.st_mtime_ns,
        getattr(metadata, "st_ino", None),
        getattr(metadata, "st_dev", None),
    )
    expected = (
        source.resolved_path,
        source.size_bytes,
        source.mtime_ns,
        source.inode,
        source.device,
    )
    if observed != expected:
        raise ValueError("source media identity changed during proxy render")
    pinned.validate_binding()


def _retry_policy(work: StageWork) -> OpenAIRetryPolicy:
    return OpenAIRetryPolicy(
        max_retries=work.config.openai_max_request_retries,
        base_delay_seconds=work.config.openai_retry_base_seconds,
        max_delay_seconds=work.config.openai_retry_max_seconds,
    )


def _generation_relative(generation: int, relative_path: str) -> str:
    if generation <= 0:
        raise ValueError("pipeline generation must be positive")
    if relative_path.startswith("/") or ".." in Path(relative_path).parts:
        raise ValueError("generation artifact path must be safe and relative")
    return f"runs/g{generation:03d}/{relative_path}"


def _generation_directory(project_dir: Path, generation: int) -> Path:
    if generation <= 0:
        raise ValueError("pipeline generation must be positive")
    return project_dir / "runs" / f"g{generation:03d}"


def _mutation_fence(work: StageWork, lease: LeaseIdentity) -> StageMutationFence:
    return StageMutationFence(
        lease=lease,
        project_id=work.project_id,
        run_id=work.run_id,
        stage_run_id=work.stage_run_id,
        generation=work.generation,
    )


def _prepared_payload(value: PreparedRevision) -> dict[str, object]:
    return {
        "candidate_id": value.candidate_id,
        "rank": value.rank,
        "revision": value.revision.model_dump(mode="json"),
    }


def _semantic_global_config(work: StageWork) -> SemanticGlobalConfig:
    return SemanticGlobalConfig(
        minimum_duration_ms=work.config.minimum_clip_ms,
        target_duration_ms=work.config.semantic_target_clip_ms,
        maximum_duration_ms=work.config.maximum_clip_ms,
        score_threshold_exclusive=work.config.semantic_score_threshold,
        max_clips=work.config.top_n,
        full_context_budget_ratio=work.config.semantic_full_context_budget_ratio,
        model_context_tokens=work.config.semantic_model_context_tokens,
        tokenizer_name=work.config.semantic_tokenizer_name,
        output_reserve_tokens=work.config.semantic_output_reserve_tokens,
        safety_margin_tokens=work.config.semantic_safety_margin_tokens,
        fallback_target_duration_ms=work.config.semantic_fallback_target_ms,
        fallback_minimum_duration_ms=work.config.semantic_fallback_minimum_ms,
        fallback_maximum_duration_ms=work.config.semantic_fallback_maximum_ms,
        fallback_context_guard_ms=work.config.semantic_fallback_context_guard_ms,
        global_context_ms=work.config.semantic_global_context_ms,
    )


def _semantic_model_settings(work: StageWork) -> dict[str, object]:
    """Return non-secret model settings that materially affect structured output."""

    return {
        "llm_model": work.config.llm_model,
        "request_timeout_seconds": work.config.openai_request_timeout_seconds,
        "max_request_retries": work.config.openai_max_request_retries,
        "retry_base_seconds": work.config.openai_retry_base_seconds,
        "retry_max_seconds": work.config.openai_retry_max_seconds,
        "tokenizer_name": work.config.semantic_tokenizer_name,
        "model_context_tokens": work.config.semantic_model_context_tokens,
        "output_reserve_tokens": work.config.semantic_output_reserve_tokens,
        "safety_margin_tokens": work.config.semantic_safety_margin_tokens,
    }


def _assert_semantic_global_prompt(
    work: StageWork,
    prompt: SemanticGlobalPromptBundle,
) -> None:
    expected = (f"{prompt.version}.{prompt.stage}", prompt.sha256)
    persisted = (
        (
            work.config.semantic_discovery_skill_version,
            work.config.semantic_discovery_skill_sha256,
        )
        if prompt.stage == "discovery"
        else (
            work.config.semantic_global_review_skill_version,
            work.config.semantic_global_review_skill_sha256,
        )
    )
    if expected != persisted:
        raise ProviderConfigurationError(
            "persisted semantic global Skill no longer matches the installed bundle"
        )


def _validated_global_clip_payload(value: ValidatedGlobalClip) -> dict[str, object]:
    return {
        "clip": value.clip.model_dump(mode="json"),
        "decision": value.decision.value,
        "start_ms": value.start_ms,
        "end_ms": value.end_ms,
        "duration_ms": value.duration_ms,
        "final_score": value.final_score,
        "validation_notes": list(value.validation_notes),
    }


def _load_prepared_revisions(serialized: bytes) -> tuple[PreparedRevision, ...]:
    payload = json.loads(serialized)
    if not isinstance(payload, dict) or payload.get("schema_version") != "1":
        raise ValueError("edit plan artifact schema is invalid")
    raw_revisions = payload.get("revisions")
    if not isinstance(raw_revisions, list):
        raise ValueError("edit plan artifact revisions are missing")
    values = [
        PreparedRevision(
            candidate_id=str(item["candidate_id"]),
            rank=int(item["rank"]),
            revision=EditPlanRevision.model_validate_json(
                json.dumps(item["revision"], ensure_ascii=False)
            ),
        )
        for item in raw_revisions
        if isinstance(item, dict)
    ]
    if len(values) != len(raw_revisions):
        raise ValueError("edit plan artifact contains an invalid revision")
    return tuple(values)


def _render_spec_fingerprint(
    revision: EditPlanRevision,
    *,
    width: int,
    height: int,
    encoder: str,
    video_stream_index: int,
    audio_stream_index: int,
) -> str:
    payload = json.dumps(
        {
            "encoder": encoder,
            "height": height,
            "renderer": FFMPEG_RENDERER_CONTRACT_VERSION,
            "text_mode": RenderTextMode.NONE.value,
            "video_stream_index": video_stream_index,
            "audio_stream_index": audio_stream_index,
            "revision": revision.model_dump(mode="json"),
            "width": width,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _write_canonical_quality_report(
    path: Path,
    raw_payload: object,
    *,
    media_path: Path,
    contact_sheet: Path,
) -> str:
    if not isinstance(raw_payload, dict):
        raise ValueError("render quality report is not an object")
    payload = {str(key): value for key, value in raw_payload.items()}
    payload["media_path"] = str(media_path.absolute())
    payload["contact_sheet"] = str(contact_sheet.absolute())
    return write_json_no_clobber(path, payload)


def _persist_stage_ffmpeg_diagnostic(
    *,
    data_dir: Path | None,
    work: StageWork,
    lease: LeaseIdentity,
    error: FFmpegRenderError,
) -> str | None:
    if data_dir is None or not error.diagnostics:
        return None
    try:
        project_dir = project_directory(data_dir, work.project_id)
        attempt_dir = attempt_directory(project_dir, lease)
        return _write_stage_render_diagnostic(
            project_dir=project_dir,
            attempt_dir=attempt_dir,
            status="failed",
            renderers=[{"renderer": render_error_diagnostics_payload(error)}],
        )
    except (ArtifactPublicationError, ValueError) as exc:
        logger.warning(
            "stage render diagnostic persistence failed error_class=%s",
            type(exc).__name__,
        )
        return None


def _write_stage_render_diagnostic(
    *,
    project_dir: Path,
    attempt_dir: Path,
    status: str,
    renderers: list[dict[str, object]],
) -> str:
    if status not in {"succeeded", "failed"} or not renderers:
        raise ValueError("stage render diagnostic is incomplete")
    diagnostic_path = attempt_dir / "diagnostics" / "ffmpeg-render.json"
    retained: list[dict[str, object]] = []
    dropped = 0
    for renderer in renderers:
        candidate = {
            "schema_version": "1",
            "status": status,
            "records_dropped": dropped,
            "renderers": [*retained, renderer],
        }
        if len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) > 224 * 1024:
            dropped += 1
            continue
        retained.append(renderer)
    write_json_no_clobber(
        diagnostic_path,
        {
            "schema_version": "1",
            "status": status,
            "records_dropped": dropped,
            "renderers": retained,
        },
        max_bytes=256 * 1024,
    )
    try:
        return diagnostic_path.relative_to(project_dir).as_posix()
    except ValueError as exc:
        raise ValueError("stage render diagnostic escaped its project") from exc
