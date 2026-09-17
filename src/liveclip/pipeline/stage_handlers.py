from __future__ import annotations

import hashlib
import json
import logging
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TypeVar, cast

from pydantic import BaseModel, ValidationError

from liveclip.application.assets import AssetReservation, AssetStore
from liveclip.application.pipeline import (
    ActionNotReady,
    ActionReadiness,
    ActionReadinessCheck,
    LeaseIdentity,
    PipelineCapability,
    PipelineRunConfigV9,
    StageWork,
)
from liveclip.application.semantic_units import SemanticUnitConflict
from liveclip.application.stage_execution import (
    CommittedStageAsset,
    PersistedCandidate,
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
from liveclip.clipping_skills.semantic_global_v2 import (
    SEMANTIC_GLOBAL_REVIEW_V3,
    candidate_assessments_required,
    load_installed_global_review_prompt,
)
from liveclip.clipping_skills.semantic_global_v3 import (
    load_semantic_global_v3_boundary_prompt,
)
from liveclip.clipping_skills.semantic_topic_chain_v1 import (
    load_semantic_topic_chain_prompt,
)
from liveclip.clipping_skills.semantic_topic_chain_v2 import (
    load_semantic_topic_chain_prompt as load_lineage_prompt,
)
from liveclip.clipping_skills.semantic_windowed_v2 import (
    load_installed_semantic_windowed_discovery_prompt,
)
from liveclip.domain.candidate import CandidateClip
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.edit_plan import (
    EDIT_PLAN_PIPELINE_CONTRACT_VERSION,
    CaptionTemplate,
    EditPlan,
    Effect,
    Layout,
    captions_to_srt,
)
from liveclip.domain.review import EditPlanRevision, RevisionOrigin
from liveclip.domain.semantic_validation import uses_current_semantic_validation
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
    cross_launch_source_stat_matches,
    hash_regular_file_no_follow,
    open_pinned_regular_file,
    read_regular_file_no_follow,
)
from liveclip.observability import redact_value
from liveclip.pipeline.candidates import CandidateGenerationConfig, generate_candidates
from liveclip.pipeline.editing import edit_and_rank_candidates
from liveclip.pipeline.semantic_cache import (
    load_semantic_stage_cache,
    semantic_stage_cache_key,
    semantic_validation_cache_settings,
    write_semantic_stage_cache,
)
from liveclip.pipeline.semantic_clipping import (
    generate_semantic_analysis_windows,
    select_semantic_clips,
)
from liveclip.pipeline.semantic_executor import SemanticUnitRequest
from liveclip.pipeline.semantic_global import (
    BoundaryReviewOutputV3,
    DiscoveryOutput,
    GlobalReviewOutput,
    GlobalReviewOutputV3,
    ReviewDecision,
    SemanticGlobalConfig,
    SemanticInputMode,
    SemanticInputPlan,
    SemanticInputUnit,
    SemanticPlanningBudgetError,
    ValidatedCandidateReviewV3,
    ValidatedGlobalClip,
    ValidatedGlobalReview,
    ValidatedGlobalReviewV3,
    build_boundary_review_payload_v3,
    build_global_review_payload,
    build_global_review_payload_v3,
    discovery_request_payload,
    namespace_discovery_output,
    plan_boundary_bridge_units,
    plan_semantic_input,
    plan_semantic_windowed_input,
    semantic_global_output_slots,
    semantic_repair_payload,
    semantic_request_tokens,
    transcript_cues,
    validate_boundary_review_v3,
    validate_discovery_output,
    validate_global_review,
    validate_global_review_v3,
)
from liveclip.pipeline.semantic_lineage import (
    LINEAGE_CONTRACT,
    BoundaryAuthorityV5,
    BoundaryReviewV5,
    ChainCandidateV5,
    DiscoveryBatchOutputV5,
    LineageValidationError,
    LogicalWindowAuthorityV5,
    TopicChainReviewV5,
    build_boundary_payload_v5,
    build_discovery_payload_v5,
    build_lineage_ledger_v5,
    build_topic_chain_payload_v5,
    collect_response_errors_v5,
    namespace_discovery_batch_v5,
    routes_for_chain_v5,
    validate_boundary_review_v5,
    validate_discovery_batch_v5,
    validate_graph_v5,
)
from liveclip.pipeline.semantic_profiles import (
    BoundaryReviewV4,
    ChainCandidateV4,
    CoverageDecisionV4,
    DiscoveryBatchOutputV4,
    GlobalReviewOutputV4,
    LinkReviewRequestV4,
    LinkReviewV4,
    ProfileStatisticsV4,
    TimeRangeV4,
    TopicChainReviewV4,
    TopicChainV4,
    UnifiedSemanticResultV4,
    ValidatedProfileResultV4,
    assemble_topic_chains_v4,
    build_boundary_review_payload_v4,
    build_discovery_payload_v4,
    build_global_review_payload_v4,
    build_link_review_payload_v4,
    build_topic_chain_review_payload_v4,
    namespace_discovery_batch_v4,
    plan_followup_link_review_requests_v4,
    plan_link_review_requests_v4,
    validate_boundary_review_v4,
    validate_discovery_batch_v4,
    validate_link_review_v4,
    validate_profile_global_review_v4,
    validate_topic_chain_review_v4,
)
from liveclip.pipeline.semantic_runtime_v5 import (
    MiniLessonArtifactConfigV5,
    MiniLessonRoughArtifactV5,
    RoughLineageStateV5,
    UnifiedSemanticResultV5,
    discovery_for_links_v4,
    final_partition_v5,
    lineage_profile_v5,
    project_quality_v4,
)
from liveclip.pipeline.semantic_unit_runtime import (
    SemanticBatchFailure,
    SemanticRecoveryError,
    run_persisted_semantic_units,
)
from liveclip.pipeline.transcript import transcribe_chunks_detailed
from liveclip.prompts import EditingPromptBundle
from liveclip.providers.asr.base import AudioChunkLike
from liveclip.providers.asr.mlx import MLXASRProvider
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
    boundary_review_response_model_v3,
    global_review_response_model,
    global_review_response_model_v3,
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

# A dense Global Review can legitimately spend almost five minutes before it
# begins emitting its bounded structured result.  The general request timeout
# remains configurable for ASR, Discovery and ordinary editing calls, while
# this one aggregation stage gets enough wall-clock headroom to finish once
# instead of being killed and blindly restarted at the observed 300s edge.
CODEX_GLOBAL_REVIEW_TIMEOUT_FLOOR_SECONDS = 600.0
V4Output = TypeVar("V4Output", bound=BaseModel)


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
        mlx_asr_model_path: Path | None = None,
        codex_executable: str = "codex",
        runtime_provider: str | None = None,
        readiness_check: ActionReadinessCheck | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._allowed_media_roots = allowed_media_roots
        self._assets = assets
        self._state = state
        self._openai_api_key = openai_api_key or None
        self._openrouter_api_key = openrouter_api_key or None
        self._openrouter_base_url = openrouter_base_url
        self._mlx_asr_model_path = mlx_asr_model_path
        self._codex_executable = codex_executable
        self._runtime_provider = runtime_provider
        self._readiness_check = readiness_check

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
                and getattr(work.config, "semantic_execution_contract", None) is None
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
            raise StageCancelled("provider work was cancelled") from exc
        except (SemanticRecoveryError, SemanticUnitConflict, ActionNotReady) as exc:
            raise StageExecutionError(
                failure_class=FailureClass.DETERMINISTIC,
                error_code=(
                    exc.code
                    if isinstance(exc, SemanticRecoveryError)
                    else "ACTION_NOT_READY"
                    if isinstance(exc, ActionNotReady)
                    else "SEMANTIC_UNIT_EVIDENCE_INVALID"
                ),
                safe_message=(
                    str(exc)
                    if not isinstance(exc, SemanticUnitConflict)
                    else "Semantic execution evidence is invalid; inspect this run."
                ),
            ) from exc
        except StructuredProviderError as exc:
            repair_budget_exceeded = exc.code == "STRUCTURED_REPAIR_BUDGET_EXCEEDED"
            input_budget_exceeded = exc.code == "STRUCTURED_INPUT_BUDGET_EXCEEDED"
            budget_exceeded = input_budget_exceeded or repair_budget_exceeded
            diagnostic = exc.diagnostic_relative_path
            if (
                budget_exceeded
                and diagnostic is None
                and getattr(work.config, "semantic_transport_contract", None) is not None
            ):
                diagnostic = self._persist_semantic_budget_audit(work, lease, exc)
            output_invalid = exc.code in {
                "STRUCTURED_OUTPUT_INVALID",
                "STRUCTURED_OUTPUT_MISSING",
            }
            retryable = not (output_invalid or budget_exceeded) and exc.code not in {
                "STRUCTURED_TOOL_EVENT",
                "CODEX_CLI_APP_SERVER_PERMISSION_DENIED",
            }
            if isinstance(exc, SemanticBatchFailure):
                retryable = not exc.deterministic
            permission_denied = exc.code == "CODEX_CLI_APP_SERVER_PERMISSION_DENIED"
            raise StageExecutionError(
                failure_class=(FailureClass.TRANSIENT if retryable else FailureClass.DETERMINISTIC),
                error_code=(
                    f"{work.stage.value.upper()}_INPUT_BUDGET_EXCEEDED"
                    if input_budget_exceeded
                    else f"{work.stage.value.upper()}_REPAIR_BUDGET_EXCEEDED"
                    if repair_budget_exceeded
                    else f"{work.stage.value.upper()}_CODEX_NESTED_SESSION"
                    if permission_denied
                    else (
                        f"{work.stage.value.upper()}_PROVIDER_OUTPUT_INVALID"
                        if output_invalid
                        else (
                            f"{work.stage.value.upper()}_PROVIDER_TEMPORARY"
                            if retryable
                            else f"{work.stage.value.upper()}_PROVIDER_INVALID"
                        )
                    )
                ),
                diagnostic_relative_path=diagnostic,
                safe_message=(
                    "A semantic request exceeds its context budget; "
                    "no model call ran for that request"
                    if input_budget_exceeded
                    else (
                        "A semantic repair exceeds its context budget; "
                        "no repair call ran for that request"
                    )
                    if repair_budget_exceeded
                    else (
                        f"The {work.stage.value} model output remained invalid after bounded repair"
                    )
                    if output_invalid
                    else (
                        f"The {work.stage.value} structured model request failed temporarily"
                        if retryable
                        else "Semantic unit exhausted; unchanged recovery cannot repeat its calls"
                        if isinstance(exc, SemanticBatchFailure)
                        else (
                            "Codex CLI cannot be nested inside an active Codex app-server session"
                            if permission_denied
                            else (
                                f"The {work.stage.value} structured model violated its tool "
                                "boundary"
                            )
                        )
                    )
                ),
            ) from exc
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
            if (
                isinstance(exc, SemanticPlanningBudgetError)
                and getattr(work.config, "semantic_transport_contract", None) is not None
            ):
                budget_error = StructuredProviderError(
                    "STRUCTURED_INPUT_BUDGET_EXCEEDED",
                    (),
                    repair_attempts=(dict(exc.diagnostics),),
                )
                raise StageExecutionError(
                    failure_class=FailureClass.DETERMINISTIC,
                    error_code=f"{work.stage.value.upper()}_INPUT_BUDGET_EXCEEDED",
                    safe_message=(
                        "A semantic planning input exceeds its budget; "
                        "no model call ran for that request"
                    ),
                    diagnostic_relative_path=self._persist_semantic_budget_audit(
                        work, lease, budget_error
                    ),
                ) from exc
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

    def _persist_semantic_budget_audit(
        self, work: StageWork, lease: LeaseIdentity, error: StructuredProviderError
    ) -> str:
        """Keep local zero-call diagnostics on legacy stage paths with new transport."""
        project_dir = project_directory(self._data_dir, work.project_id)
        relative = (
            (
                attempt_directory(project_dir, lease)
                / "diagnostics"
                / f"{work.stage.value}-semantic-budget.json"
            )
            .relative_to(project_dir)
            .as_posix()
        )
        reservation = self._reserve(
            work,
            lease,
            kind="semantic_budget_audit",
            relative_path=relative,
            mime_type="application/json",
        )
        payload = {
            "schema_version": "1",
            "audit_contract": "semantic-budget-audit-v1",
            "project_id": work.project_id,
            "run_id": work.run_id,
            "stage_run_id": work.stage_run_id,
            "generation": work.generation,
            "stage": work.stage.value,
            "config_fingerprint": work.config.fingerprint,
            "input_fingerprint": work.input_fingerprint,
            "failure_code": error.code,
            "provider_attempts": list(error.repair_attempts),
            "call_ids": [record.call_id for record in error.call_records],
        }
        digest = write_json_no_clobber(
            project_dir / relative,
            _redact_semantic_failure_audit(
                payload,
                tuple(value for value in (self._openai_api_key, self._openrouter_api_key) if value),
            ),
        )
        self._commit(
            lease,
            reservation,
            project_dir=project_dir,
            validation={"schema_version": "1", "audit_contract": "semantic-budget-audit-v1"},
            expected_sha256=digest,
        )
        return relative

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
        if work.config.clip_profile == ClipProfile.MINI_LESSON:
            mini_candidates = (
                self._mini_lesson_candidates_v5
                if isinstance(work.config, PipelineRunConfigV9)
                else self._mini_lesson_candidates
            )
            return mini_candidates(
                work,
                lease=lease,
                cancel_requested=cancel_requested,
                project_dir=project_dir,
                generation_dir=generation_dir,
                transcript=transcript,
                source_hash=manifest.source_sha256,
                reservation=reservation,
            )
        semantic_global_payload: dict[str, object] | None = None
        artifact_config: dict[str, object]
        if work.config.clipping_algorithm in {"semantic_global", "semantic_windowed"}:
            semantic_config = _semantic_global_config(work)
            discovery_prompt = (
                load_installed_semantic_windowed_discovery_prompt(
                    work.config.semantic_discovery_skill_version,
                    work.config.semantic_profile,
                )
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
                structured_budget_errors=getattr(work.config, "semantic_transport_contract", None)
                is not None,
            )
            discovery_provider = self._structured_provider(work, discovery_prompt)
            fence = _mutation_fence(work, lease)
            discovery_outputs: list[DiscoveryOutput] = []
            discovery_cache_hits: list[bool] = []
            discovery_call_records: list[ProviderCallRecord] = []
            discovery_validation_events: list[dict[str, str]] = []
            discovery_agent_outputs: list[dict[str, object]] = []

            def discovery_failure(
                failures: list[StructuredProviderError],
            ) -> StructuredProviderError:
                if getattr(work.config, "semantic_transport_contract", None) is None:
                    return failures[0]
                aggregate = _aggregate_semantic_failures(failures, tuple(discovery_call_records))
                return StructuredProviderError(
                    aggregate.code,
                    aggregate.call_records,
                    repair_attempts=(
                        *aggregate.repair_attempts,
                        {
                            "phase": "stage_validation",
                            "agent_outputs": discovery_agent_outputs,
                            "validation_events": discovery_validation_events,
                        },
                    ),
                )

            def normalize_discovery(
                raw: DiscoveryOutput,
                unit: SemanticInputUnit,
            ) -> DiscoveryOutput:
                normalized, notes = namespace_discovery_output(raw, unit=unit)
                discovery_validation_events.extend(
                    {"input_unit_id": unit.unit_id, "normalization": note} for note in notes
                )
                return normalized

            model_settings = _semantic_model_settings(work, discovery_provider)
            discovery_cache_dir = generation_dir / "candidates/semantic-cache/discovery"
            fallback_discovery_cache_dirs = tuple(
                project_dir
                / _generation_relative(generation, "candidates/semantic-cache/discovery")
                for generation in range(1, work.generation)
            )

            def validate_and_cache_discovery(
                *,
                unit: SemanticInputUnit,
                request_payload: dict[str, object],
                cache_key: str,
                result: StructuredCallResult[DiscoveryOutput],
            ) -> DiscoveryOutput:
                self._state.record_provider_calls(
                    fence,
                    result.call_records,
                    cache_hit=False,
                )
                discovery_call_records.extend(result.call_records)
                discovery_agent_outputs.append(
                    {
                        "input_unit_id": unit.unit_id,
                        "phase": "initial_or_schema_repaired",
                        "repaired": result.repaired,
                        "repair_attempts": list(result.repair_attempts),
                        "output": result.output.model_dump(mode="json"),
                    }
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
                        {
                            "input_unit_id": unit.unit_id,
                            "error": _semantic_error_detail(work, exc, legacy_limit=500),
                        }
                    )
                    if result.repaired:
                        raise StructuredProviderError(
                            "STRUCTURED_OUTPUT_INVALID",
                            (),
                            repair_attempts=result.repair_attempts,
                        ) from exc
                    try:
                        repaired = discovery_provider.repair(
                            subject_id=f"{work.run_id}.{unit.unit_id}",
                            payload=_semantic_repair_request(
                                work,
                                request_payload,
                                normalized_output,
                                validation_errors=(
                                    _semantic_error_detail(work, exc, legacy_limit=500),
                                ),
                            ),
                            response_model=DiscoveryOutput,
                            validation_errors=(
                                _semantic_error_detail(work, exc, legacy_limit=240),
                            ),
                            cancel_requested=cancel_requested,
                        )
                    except StructuredProviderError as repair_exc:
                        self._state.record_provider_calls(
                            fence,
                            repair_exc.call_records,
                            cache_hit=False,
                        )
                        discovery_call_records.extend(repair_exc.call_records)
                        raise
                    self._state.record_provider_calls(
                        fence,
                        repaired.call_records,
                        cache_hit=False,
                    )
                    discovery_call_records.extend(repaired.call_records)
                    discovery_agent_outputs.append(
                        {
                            "input_unit_id": unit.unit_id,
                            "phase": "domain_repair",
                            "repaired": True,
                            "repair_attempts": list(repaired.repair_attempts),
                            "output": repaired.output.model_dump(mode="json"),
                        }
                    )
                    try:
                        output = validate_discovery_output(
                            normalize_discovery(repaired.output, unit),
                            unit=unit,
                            config=semantic_config,
                        )
                    except ValueError as repair_validation_error:
                        discovery_validation_events.append(
                            {
                                "input_unit_id": unit.unit_id,
                                "error": _semantic_error_detail(
                                    work, repair_validation_error, legacy_limit=500
                                ),
                            }
                        )
                        raise StructuredProviderError(
                            "STRUCTURED_OUTPUT_INVALID",
                            (),
                            repair_attempts=repaired.repair_attempts,
                        ) from repair_validation_error
                write_semantic_stage_cache(
                    cache_dir=discovery_cache_dir,
                    cache_key=cache_key,
                    stage="discovery",
                    payload=request_payload,
                    provider=discovery_provider,
                    model_settings=model_settings,
                    output=output,
                )
                return output

            if getattr(work.config, "semantic_execution_contract", None) is not None:

                def run_discovery_units(
                    units: tuple[SemanticInputUnit, ...],
                    mode: SemanticInputMode,
                ) -> None:
                    def make_request(unit: SemanticInputUnit) -> SemanticUnitRequest:
                        def validate(raw: BaseModel) -> BaseModel:
                            return validate_discovery_output(
                                namespace_discovery_output(cast(DiscoveryOutput, raw), unit=unit)[
                                    0
                                ],
                                unit=unit,
                                config=semantic_config,
                            )

                        def repair_payload(
                            original: dict[str, object],
                            output: BaseModel,
                            errors: tuple[str, ...],
                        ) -> dict[str, object]:
                            return _semantic_repair_request(
                                work,
                                original,
                                namespace_discovery_output(
                                    cast(DiscoveryOutput, output), unit=unit
                                )[0],
                                validation_errors=errors,
                            )

                        return SemanticUnitRequest.snapshot(
                            subject_id=unit.unit_id,
                            payload=discovery_request_payload(
                                unit,
                                source_id=work.project_id,
                                mode=mode,
                                config=semantic_config,
                                include_final_gates=(
                                    work.config.semantic_discovery_skill_version
                                    != "semantic_windowed_v2.discovery"
                                ),
                            ),
                            response_model=DiscoveryOutput,
                            validate=validate,
                            repair_payload=repair_payload,
                        )

                    requests = tuple(make_request(unit) for unit in units)
                    resolved, audit = self._run_semantic_units(
                        work,
                        fence=fence,
                        project_dir=project_dir,
                        stage="discovery",
                        provider=discovery_provider,
                        model_settings=model_settings,
                        requests=requests,
                        cancel_requested=cancel_requested,
                    )
                    hits = cast(dict[str, bool], audit["cache_hits"])
                    for unit in units:
                        discovery_outputs.append(cast(DiscoveryOutput, resolved[unit.unit_id]))
                        discovery_cache_hits.append(hits[unit.unit_id])
                    discovery_agent_outputs.extend(
                        {**item, "input_unit_id": item["subject_id"]}
                        for item in cast(list[dict[str, object]], audit["agent_outputs"])
                    )
                    discovery_validation_events.extend(
                        {str(key): str(value) for key, value in item.items()}
                        for item in cast(list[dict[str, object]], audit["validation_events"])
                    )

                run_discovery_units(input_plan.units, input_plan.mode)
                boundary_bridge_units = (
                    plan_boundary_bridge_units(
                        transcript,
                        input_plan=input_plan,
                        discovery_outputs=tuple(discovery_outputs),
                        config=semantic_config,
                        structured_budget_errors=True,
                    )
                    if work.config.clipping_algorithm == "semantic_windowed"
                    else ()
                )
                run_discovery_units(boundary_bridge_units, SemanticInputMode.BOUNDARY_BRIDGE)
            else:
                prefetched_discovery: dict[str, DiscoveryOutput] = {}
                if work.config.clipping_algorithm == "semantic_windowed":
                    uncached_requests: list[tuple[SemanticInputUnit, dict[str, object], str]] = []
                    for unit in input_plan.units:
                        request_payload = discovery_request_payload(
                            unit,
                            source_id=work.project_id,
                            mode=input_plan.mode,
                            config=semantic_config,
                            include_final_gates=(
                                work.config.semantic_discovery_skill_version
                                != "semantic_windowed_v2.discovery"
                            ),
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
                            uncached_requests.append((unit, request_payload, cache_key))
                    prefetch_failures: list[StructuredProviderError] = []
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
                                subject_id=f"{work.run_id}.{unit.unit_id}",
                                payload=request_payload,
                                response_model=DiscoveryOutput,
                                cancel_requested=cancel_requested,
                            ): (unit, request_payload, cache_key)
                            for unit, request_payload, cache_key in uncached_requests
                        }
                        for future in as_completed(pending):
                            unit, request_payload, cache_key = pending[future]
                            try:
                                result = future.result()
                            except StructuredProviderError as exc:
                                self._state.record_provider_calls(
                                    fence,
                                    exc.call_records,
                                    cache_hit=False,
                                )
                                discovery_call_records.extend(exc.call_records)
                                prefetch_failures.append(exc)
                                continue
                            try:
                                prefetched_discovery[unit.unit_id] = validate_and_cache_discovery(
                                    unit=unit,
                                    request_payload=request_payload,
                                    cache_key=cache_key,
                                    result=result,
                                )
                            except StructuredProviderError as exc:
                                prefetch_failures.append(exc)
                    if prefetch_failures:
                        raise discovery_failure(prefetch_failures)
                for unit in input_plan.units:
                    _check_cancel(cancel_requested)
                    request_payload = discovery_request_payload(
                        unit,
                        source_id=work.project_id,
                        mode=input_plan.mode,
                        config=semantic_config,
                        include_final_gates=(
                            work.config.semantic_discovery_skill_version
                            != "semantic_windowed_v2.discovery"
                        ),
                    )
                    cache_key = semantic_stage_cache_key(
                        stage="discovery",
                        payload=request_payload,
                        provider=discovery_provider,
                        model_settings=model_settings,
                        output_model=DiscoveryOutput,
                    )
                    prefetched_output = prefetched_discovery.pop(unit.unit_id, None)
                    if prefetched_output is not None:
                        discovery_outputs.append(prefetched_output)
                        discovery_cache_hits.append(False)
                        continue
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
                        discovery_call_records.extend(exc.call_records)
                        if getattr(work.config, "semantic_transport_contract", None) is not None:
                            raise discovery_failure([exc]) from exc
                        raise
                    try:
                        output = validate_and_cache_discovery(
                            unit=unit,
                            request_payload=request_payload,
                            cache_key=cache_key,
                            result=result,
                        )
                    except StructuredProviderError as exc:
                        if getattr(work.config, "semantic_transport_contract", None) is not None:
                            raise discovery_failure([exc]) from exc
                        raise
                    discovery_outputs.append(output)
                    discovery_cache_hits.append(False)
                boundary_bridge_units = ()
                if work.config.clipping_algorithm == "semantic_windowed":
                    boundary_bridge_units = plan_boundary_bridge_units(
                        transcript,
                        input_plan=input_plan,
                        discovery_outputs=tuple(discovery_outputs),
                        config=semantic_config,
                        structured_budget_errors=getattr(
                            work.config, "semantic_transport_contract", None
                        )
                        is not None,
                    )
                    resolved_bridges: dict[str, tuple[DiscoveryOutput, bool]] = {}
                    uncached_bridge_requests: list[
                        tuple[SemanticInputUnit, dict[str, object], str]
                    ] = []
                    for unit in boundary_bridge_units:
                        _check_cancel(cancel_requested)
                        request_payload = discovery_request_payload(
                            unit,
                            source_id=work.project_id,
                            mode=SemanticInputMode.BOUNDARY_BRIDGE,
                            config=semantic_config,
                            include_final_gates=(
                                work.config.semantic_discovery_skill_version
                                != "semantic_windowed_v2.discovery"
                            ),
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
                            resolved_bridges[unit.unit_id] = (output, True)
                            continue
                        uncached_bridge_requests.append((unit, request_payload, cache_key))
                    bridge_failures: list[StructuredProviderError] = []
                    with ThreadPoolExecutor(
                        max_workers=min(
                            semantic_config.window_discovery_concurrency,
                            max(1, len(uncached_bridge_requests)),
                        ),
                        thread_name_prefix="semantic-windowed-bridge",
                    ) as executor:
                        pending_bridges = {
                            executor.submit(
                                discovery_provider.generate,
                                subject_id=f"{work.run_id}.{unit.unit_id}",
                                payload=request_payload,
                                response_model=DiscoveryOutput,
                                cancel_requested=cancel_requested,
                            ): (unit, request_payload, cache_key)
                            for unit, request_payload, cache_key in uncached_bridge_requests
                        }
                        for future in as_completed(pending_bridges):
                            unit, request_payload, cache_key = pending_bridges[future]
                            try:
                                result = future.result()
                            except StructuredProviderError as exc:
                                self._state.record_provider_calls(
                                    fence,
                                    exc.call_records,
                                    cache_hit=False,
                                )
                                discovery_call_records.extend(exc.call_records)
                                bridge_failures.append(exc)
                                continue
                            try:
                                output = validate_and_cache_discovery(
                                    unit=unit,
                                    request_payload=request_payload,
                                    cache_key=cache_key,
                                    result=result,
                                )
                            except StructuredProviderError as exc:
                                bridge_failures.append(exc)
                                continue
                            resolved_bridges[unit.unit_id] = (output, False)
                    if bridge_failures:
                        raise discovery_failure(bridge_failures)
                    for unit in boundary_bridge_units:
                        output, cache_hit = resolved_bridges[unit.unit_id]
                        discovery_outputs.append(output)
                        discovery_cache_hits.append(cache_hit)
            discovered_candidate_count = sum(len(output.candidates) for output in discovery_outputs)
            output_slot_count = (
                discovered_candidate_count
                if work.config.semantic_global_review_skill_version == SEMANTIC_GLOBAL_REVIEW_V3
                else max(work.config.top_n, discovered_candidate_count)
            )
            candidates = semantic_global_output_slots(
                transcript,
                max_clips=output_slot_count,
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
                    "agent_outputs": sorted(
                        discovery_agent_outputs,
                        key=lambda value: (
                            str(value["input_unit_id"]),
                            str(value["phase"]),
                        ),
                    ),
                    "discovery_concurrency": (
                        semantic_config.window_discovery_concurrency
                        if work.config.clipping_algorithm == "semantic_windowed"
                        else 1
                    ),
                    "boundary_bridge_concurrency": (
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

    def _validate_mini_rough_v5(
        self,
        work: StageWork,
        artifact: MiniLessonRoughArtifactV5,
        *,
        transcript: TranscriptDocument,
        source_hash: str,
        input_plan: SemanticInputPlan,
    ) -> None:
        if not isinstance(work.config, PipelineRunConfigV9):
            raise ValueError("V5 rough artifact requires a V9 run")
        semantic = artifact.semantic_v5
        if (
            (
                semantic.run_id,
                semantic.project_id,
                semantic.config_fingerprint,
                semantic.source_hash,
            )
            != (work.run_id, work.project_id, work.config.fingerprint, source_hash)
            or semantic.input_plan != input_plan
            or artifact.config.top_n != work.config.top_n
        ):
            raise ValueError("V5 rough artifact identity or immutable input plan differs")
        for batch, unit in zip(semantic.local_discovery_outputs, input_plan.units, strict=True):
            payload = build_discovery_payload_v5(
                unit,
                source_id=work.project_id,
                source_hash=source_hash,
                prompt_hash=work.config.semantic_discovery_skill_sha256,
                semantic_profile=work.config.semantic_profile,
            )
            validate_discovery_batch_v5(
                batch,
                expected_batch_id=unit.unit_id,
                expected_context=TimeRangeV4.model_validate(payload["batch_context"]),
                expected_ownership=TimeRangeV4.model_validate(payload["ownership_interval"]),
                expected_windows=tuple(
                    LogicalWindowAuthorityV5.model_validate_json(json.dumps(value))
                    for value in cast(list[object], payload["logical_windows"])
                ),
                transcript=transcript,
                available_cue_ids=tuple(cue.cue_id for cue in unit.cues),
            )
        discovery_views = tuple(
            discovery_for_links_v4(batch) for batch in semantic.discovery_outputs
        )
        requests = list(plan_link_review_requests_v4(discovery_views))
        pending = tuple(requests)
        by_id = {value.link_review_id: value for value in semantic.link_reviews}
        if len(by_id) != len(semantic.link_reviews):
            raise ValueError("V5 rough artifact repeats a Link Review")
        completed: list[LinkReviewV4] = []
        while pending:
            for request in pending:
                if request.link_review_id not in by_id:
                    raise ValueError("V5 rough artifact is missing a required Link Review")
                completed.append(
                    validate_link_review_v4(
                        by_id[request.link_review_id], request=request, transcript=transcript
                    )
                )
            pending = plan_followup_link_review_requests_v4(
                discovery_views,
                existing_requests=tuple(requests),
                completed_reviews=tuple(completed),
            )
            requests.extend(pending)
        if (
            tuple(requests) != semantic.link_review_requests
            or tuple(completed) != semantic.link_reviews
        ):
            raise ValueError("V5 rough artifact contains an inconsistent Link graph")
        fragments = tuple(
            fragment for batch in semantic.discovery_outputs for fragment in batch.topic_fragments
        )
        if assemble_topic_chains_v4(fragments, semantic.link_reviews) != semantic.topic_chains:
            raise ValueError("V5 rough chains differ from the validated Link graph")
        validate_graph_v5(
            tuple(
                original for batch in semantic.discovery_outputs for original in batch.candidates
            ),
            semantic.topic_chains,
            fragments,
            semantic.topic_chain_reviews,
            transcript=transcript,
        )
        units = tuple(unit for review in semantic.topic_chain_reviews for unit in review.candidates)
        slots, mapping = _candidate_slots_from_v4(transcript, units, lineage=True)
        if slots != artifact.candidates or mapping != semantic.candidate_slot_map:
            raise ValueError("V5 rough slots differ from their source units")

    def _load_mini_rough_v5(
        self,
        work: StageWork,
        *,
        project_dir: Path,
        transcript: TranscriptDocument,
        source_hash: str,
    ) -> MiniLessonRoughArtifactV5:
        prompt = load_lineage_prompt(
            "discovery", work.config.semantic_profile, ClipProfile.MINI_LESSON
        )
        _assert_semantic_global_prompt(work, prompt)
        plan = plan_semantic_windowed_input(
            transcript,
            prompt=prompt.instructions,
            config=_semantic_global_config(work),
            structured_budget_errors=getattr(work.config, "semantic_transport_contract", None)
            is not None,
        )
        artifact = MiniLessonRoughArtifactV5.model_validate_json(
            self._committed_asset_bytes(
                work,
                project_dir=project_dir,
                kind="rough_candidates",
                relative_path=_generation_relative(
                    work.generation, "candidates/rough-candidates.json"
                ),
                max_bytes=128 * 1024 * 1024,
            )
        )
        self._validate_mini_rough_v5(
            work, artifact, transcript=transcript, source_hash=source_hash, input_plan=plan
        )
        return artifact

    def _validate_saved_mini_edit_v5(
        self,
        work: StageWork,
        *,
        serialized: bytes,
        project_dir: Path,
        transcript: TranscriptDocument,
        source_hash: str,
        candidates: tuple[PersistedCandidate, ...],
        prepared: tuple[PreparedRevision, ...],
    ) -> None:
        payload = json.loads(serialized)
        final = UnifiedSemanticResultV5.model_validate_json(json.dumps(payload.get("semantic_v5")))
        rough = self._load_mini_rough_v5(
            work, project_dir=project_dir, transcript=transcript, source_hash=source_hash
        )
        semantic = rough.semantic_v5
        if (final.run_id, final.project_id, final.config_fingerprint, final.source_hash) != (
            work.run_id,
            work.project_id,
            work.config.fingerprint,
            source_hash,
        ) or final.candidate_slot_map != semantic.candidate_slot_map:
            raise ValueError("saved V5 edit identity differs from the current run")
        if any(
            final.run_metadata.get(key) != expected
            for key, expected in (
                ("run_id", work.run_id),
                ("source_hash", source_hash),
                ("validation_contract", work.config.semantic_validation_contract),
                ("lineage_contract", LINEAGE_CONTRACT),
            )
        ):
            raise ValueError("saved V5 edit provenance differs from the current run")
        units = tuple(unit for review in semantic.topic_chain_reviews for unit in review.candidates)
        boundaries = tuple(outcome.boundary for outcome in final.lineage.outcomes)
        ledger = build_lineage_ledger_v5(
            batches=semantic.discovery_outputs,
            chains=semantic.topic_chains,
            reviews=semantic.topic_chain_reviews,
            boundaries=boundaries,
            partition=final.lineage.partition,
            transcript=transcript,
        )
        if ledger != final.lineage:
            raise ValueError("saved V5 lineage differs from the committed rough graph")
        if final.global_review is not None:
            quality = validate_profile_global_review_v4(
                final.global_review,
                candidates=tuple(project_quality_v4(ChainCandidateV4, unit) for unit in units),
                boundary_reviews=tuple(
                    project_quality_v4(BoundaryReviewV4, review) for review in boundaries
                ),
                transcript=transcript,
                profile=ClipProfile.MINI_LESSON,
                top_n=work.config.top_n,
                score_threshold_exclusive=work.config.semantic_score_threshold,
                validation_contract=work.config.semantic_validation_contract,
            )
        else:
            quality = ValidatedProfileResultV4(
                statistics=ProfileStatisticsV4(
                    discovery_candidate_count=0,
                    boundary_candidate_count=0,
                    qualified_before_top_n=0,
                    selected_count=0,
                    manual_count=0,
                    blocked_count=0,
                    rejected_count=0,
                    top_n_excluded_count=0,
                )
            )
        if lineage_profile_v5(quality, ledger) != final.profiles[ClipProfile.MINI_LESSON]:
            raise ValueError("saved V5 outcome differs from the actual quality gates")
        by_slot = {item.candidate.candidate_id: item for item in candidates}
        if {key: item.candidate for key, item in by_slot.items()} != {
            item.candidate_id: item for item in rough.candidates
        }:
            raise ValueError("saved V5 edit uses a changed persisted candidate")
        expected_ids = {
            unit.candidate_id: by_slot[semantic.candidate_slot_map[unit.candidate_id]].candidate_id
            for unit in units
        }
        if expected_ids != final.persistent_candidate_ids or len(prepared) != len(quality.selected):
            raise ValueError("saved V5 edit selected IDs differ from the persisted candidates")
        for rank, (item, selected) in enumerate(zip(prepared, quality.selected, strict=True), 1):
            review = selected.review
            slot = semantic.candidate_slot_map[review.candidate_id]
            expected_plan = EditPlan(
                candidate_id=slot,
                source_start_ms=selected.start_ms,
                source_end_ms=selected.end_ms,
                score=float(review.total_score),
                title=review.title,
                hook=review.learning_outcome[:80],
                reason=review.review_reason[:240],
                layout=Layout.CENTER_CROP,
                caption_template=CaptionTemplate.CLEAN_ZH_V1,
                effect=Effect.NONE,
                risk_flags=tuple(value.value for value in review.risk_flags)[:8],
                prompt_version="semantic_topic_chain_v1.global_review",
                model=work.config.llm_model,
                degraded=False,
            )
            if (
                item.candidate_id != expected_ids[review.candidate_id]
                or item.rank != rank
                or item.revision.clip_id != item.candidate_id
                or item.revision.revision != 1
                or item.revision.origin != RevisionOrigin.AI
                or item.revision.plan != expected_plan
                or item.revision.captions
                != captions_for_clip(
                    transcript.segments,
                    source_start_ms=selected.start_ms,
                    source_end_ms=selected.end_ms,
                )
            ):
                raise ValueError("saved V5 revision differs from the selected source span")

    def _mini_lesson_candidates_v5(
        self,
        work: StageWork,
        *,
        lease: LeaseIdentity,
        cancel_requested: Callable[[], bool],
        project_dir: Path,
        generation_dir: Path,
        transcript: TranscriptDocument,
        source_hash: str,
        reservation: AssetReservation,
    ) -> StageExecutionResult:
        """Discover and semantically connect cross-window mini-lesson topics."""

        profile = ClipProfile.MINI_LESSON
        semantic_config = _semantic_global_config(work)
        fence = _mutation_fence(work, lease)
        discovery_prompt = load_lineage_prompt("discovery", work.config.semantic_profile, profile)
        _assert_semantic_global_prompt(work, discovery_prompt)
        input_plan = plan_semantic_windowed_input(
            transcript,
            prompt=discovery_prompt.instructions,
            config=semantic_config,
            structured_budget_errors=getattr(work.config, "semantic_transport_contract", None)
            is not None,
        )
        artifact_path = project_dir / reservation.relative_path
        if (
            reservation.status == AssetStatus.COMMITTED
            or artifact_path.exists()
            or artifact_path.is_symlink()
        ):
            serialized = (
                self._committed_asset_bytes(
                    work,
                    project_dir=project_dir,
                    kind="rough_candidates",
                    relative_path=reservation.relative_path,
                    max_bytes=128 * 1024 * 1024,
                )
                if reservation.status == AssetStatus.COMMITTED
                else read_regular_file_no_follow(artifact_path, max_bytes=128 * 1024 * 1024)
            )
            artifact = MiniLessonRoughArtifactV5.model_validate_json(serialized)
            self._validate_mini_rough_v5(
                work,
                artifact,
                transcript=transcript,
                source_hash=source_hash,
                input_plan=input_plan,
            )
            committed = self._commit(
                lease,
                reservation,
                project_dir=project_dir,
                validation={"schema_version": "5", "candidate_count": len(artifact.candidates)},
            )
            persisted = self._state.save_candidates(fence, candidates=artifact.candidates)
            return self._result(work.stage, (committed,), {"candidate_count": len(persisted)})
        discovery_requests: list[
            tuple[
                str,
                dict[str, object],
                Callable[[DiscoveryBatchOutputV5], DiscoveryBatchOutputV5],
            ]
        ] = []
        for unit in input_plan.units:
            payload = build_discovery_payload_v5(
                unit,
                source_id=work.project_id,
                source_hash=source_hash,
                semantic_profile=work.config.semantic_profile,
                prompt_hash=discovery_prompt.sha256,
            )
            expected_context = TimeRangeV4.model_validate(payload["batch_context"])
            expected_ownership = TimeRangeV4.model_validate(payload["ownership_interval"])
            expected_windows = tuple(
                LogicalWindowAuthorityV5.model_validate_json(json.dumps(value))
                for value in cast(list[object], payload["logical_windows"])
            )

            def validate_discovery(
                value: DiscoveryBatchOutputV5,
                *,
                current_unit: SemanticInputUnit = unit,
                context: TimeRangeV4 = expected_context,
                ownership: TimeRangeV4 = expected_ownership,
                windows: tuple[TimeRangeV4, ...] = expected_windows,
            ) -> DiscoveryBatchOutputV5:
                return validate_discovery_batch_v5(
                    value,
                    expected_batch_id=current_unit.unit_id,
                    expected_context=context,
                    expected_ownership=ownership,
                    expected_windows=windows,
                    transcript=transcript,
                    available_cue_ids=tuple(cue.cue_id for cue in current_unit.cues),
                )

            discovery_requests.append((unit.unit_id, payload, validate_discovery))
        discovery_provider = self._structured_provider(work, discovery_prompt)
        discovered, discovery_audit = self._run_v4_requests(
            work,
            fence=fence,
            project_dir=project_dir,
            generation_dir=generation_dir,
            stage="discovery",
            provider=discovery_provider,
            response_model=DiscoveryBatchOutputV5,
            requests=tuple(discovery_requests),
            cancel_requested=cancel_requested,
        )
        local_discovery_outputs = tuple(discovered[unit.unit_id] for unit in input_plan.units)
        discovery_outputs = tuple(
            namespace_discovery_batch_v5(value) for value in local_discovery_outputs
        )
        link_discovery_outputs = tuple(discovery_for_links_v4(value) for value in discovery_outputs)
        all_fragments = tuple(
            fragment for output in discovery_outputs for fragment in output.topic_fragments
        )
        if len({value.topic_fragment_id for value in all_fragments}) != len(all_fragments):
            raise ValueError("Discovery Topic Fragment IDs are not globally unique")

        link_prompt = load_semantic_topic_chain_prompt(
            "link_review", work.config.semantic_profile, profile
        )
        _assert_semantic_global_prompt(work, link_prompt)
        link_provider = self._structured_provider(work, link_prompt)
        all_link_requests: list[LinkReviewRequestV4] = list(
            plan_link_review_requests_v4(link_discovery_outputs)
        )
        completed_links: dict[str, LinkReviewV4] = {}
        link_round_audits: list[dict[str, object]] = []
        pending_links = tuple(all_link_requests)
        while pending_links:
            link_requests: list[
                tuple[
                    str,
                    dict[str, object],
                    Callable[[LinkReviewV4], LinkReviewV4],
                ]
            ] = []
            for request in pending_links:
                payload = build_link_review_payload_v4(
                    request,
                    transcript=transcript,
                    source_hash=source_hash,
                    profile=profile,
                    prompt_hash=link_prompt.sha256,
                )

                def validate_link(
                    value: LinkReviewV4,
                    *,
                    current_request: LinkReviewRequestV4 = request,
                ) -> LinkReviewV4:
                    return validate_link_review_v4(
                        value, request=current_request, transcript=transcript
                    )

                link_requests.append((request.link_review_id, payload, validate_link))
            linked, link_audit = self._run_v4_requests(
                work,
                fence=fence,
                project_dir=project_dir,
                generation_dir=generation_dir,
                stage="link_review",
                provider=link_provider,
                response_model=LinkReviewV4,
                requests=tuple(link_requests),
                cancel_requested=cancel_requested,
            )
            completed_links.update(linked)
            link_round_audits.append(link_audit)
            followups = plan_followup_link_review_requests_v4(
                link_discovery_outputs,
                existing_requests=tuple(all_link_requests),
                completed_reviews=tuple(completed_links.values()),
            )
            all_link_requests.extend(followups)
            pending_links = followups
        link_outputs = tuple(completed_links[value.link_review_id] for value in all_link_requests)
        topic_chains = assemble_topic_chains_v4(all_fragments, link_outputs)

        chain_prompt = load_lineage_prompt("topic_chain", work.config.semantic_profile, profile)
        _assert_semantic_global_prompt(work, chain_prompt)
        chain_provider = self._structured_provider(work, chain_prompt)
        chain_requests: list[
            tuple[
                str,
                dict[str, object],
                Callable[[TopicChainReviewV5], TopicChainReviewV5],
            ]
        ] = []
        for chain in topic_chains:
            payload = build_topic_chain_payload_v5(
                chain,
                batches=discovery_outputs,
                chains=topic_chains,
                transcript=transcript,
                source_id=work.project_id,
                source_hash=source_hash,
                prompt_hash=chain_prompt.sha256,
                semantic_profile=work.config.semantic_profile,
            )

            def validate_chain(
                value: TopicChainReviewV5,
                *,
                current_chain: TopicChainV4 = chain,
            ) -> TopicChainReviewV5:
                errors = collect_response_errors_v5(
                    TopicChainReviewV5,
                    value.model_dump_json(),
                    chain=current_chain,
                    routes=routes_for_chain_v5(
                        tuple(
                            original for batch in discovery_outputs for original in batch.candidates
                        ),
                        current_chain,
                        all_fragments,
                    ),
                    transcript=transcript,
                )
                if errors:
                    raise LineageValidationError(errors)
                return value

            chain_requests.append((chain.topic_chain_id, payload, validate_chain))
        chain_reviews_by_id: dict[str, TopicChainReviewV5] = {}
        chain_audit: dict[str, object] = {
            "stage": "topic_chain",
            "request_count": 0,
            "cache_hit_count": 0,
            "agent_outputs": [],
            "validation_events": [],
        }
        if chain_requests:
            chain_reviews_by_id, chain_audit = self._run_v4_requests(
                work,
                fence=fence,
                project_dir=project_dir,
                generation_dir=generation_dir,
                stage="topic_chain",
                provider=chain_provider,
                response_model=TopicChainReviewV5,
                requests=tuple(chain_requests),
                cancel_requested=cancel_requested,
            )
        chain_reviews = tuple(chain_reviews_by_id[value.topic_chain_id] for value in topic_chains)
        chain_candidates = tuple(
            candidate for review in chain_reviews for candidate in review.candidates
        )
        if len({value.candidate_id for value in chain_candidates}) != len(chain_candidates):
            raise ValueError("Topic Chain candidate IDs are not globally unique")
        validate_graph_v5(
            tuple(original for batch in discovery_outputs for original in batch.candidates),
            topic_chains,
            all_fragments,
            chain_reviews,
            transcript=transcript,
        )
        candidate_slots, slot_map = _candidate_slots_from_v4(
            transcript, chain_candidates, lineage=True
        )
        artifact = MiniLessonRoughArtifactV5(
            config=MiniLessonArtifactConfigV5(top_n=work.config.top_n),
            candidates=candidate_slots,
            semantic_v5=RoughLineageStateV5(
                run_id=work.run_id,
                project_id=work.project_id,
                config_fingerprint=work.config.fingerprint,
                source_hash=source_hash,
                input_plan=input_plan,
                local_discovery_outputs=local_discovery_outputs,
                discovery_outputs=discovery_outputs,
                link_review_requests=tuple(all_link_requests),
                link_reviews=link_outputs,
                topic_chains=topic_chains,
                topic_chain_reviews=chain_reviews,
                candidate_slot_map=slot_map,
                prompt_files={
                    "discovery": tuple(discovery_prompt.loaded_files),
                    "link_review": tuple(link_prompt.loaded_files),
                    "topic_chain": tuple(chain_prompt.loaded_files),
                },
                stage_audits={
                    "discovery": discovery_audit,
                    "link_review_rounds": link_round_audits,
                    "topic_chain": chain_audit,
                },
            ),
        )
        write_json_no_clobber(
            project_dir / reservation.relative_path, artifact.model_dump(mode="json")
        )
        committed = self._commit(
            lease,
            reservation,
            project_dir=project_dir,
            validation={
                "schema_version": "5",
                "candidate_count": len(candidate_slots),
                "original_candidate_count": sum(
                    len(batch.candidates) for batch in discovery_outputs
                ),
            },
        )
        persisted = self._state.save_candidates(fence, candidates=candidate_slots)
        return self._result(work.stage, (committed,), {"candidate_count": len(persisted)})

    def _mini_lesson_edit_v5(
        self,
        work: StageWork,
        *,
        fence: StageMutationFence,
        project_dir: Path,
        generation_dir: Path,
        transcript: TranscriptDocument,
        source_hash: str,
        persisted_candidates: tuple[PersistedCandidate, ...],
        cancel_requested: Callable[[], bool],
    ) -> tuple[tuple[PreparedRevision, ...], dict[str, object]]:
        """Run candidate-local boundaries and an independent mini-lesson ranking."""

        artifact = self._load_mini_rough_v5(
            work, project_dir=project_dir, transcript=transcript, source_hash=source_hash
        )
        semantic_state = artifact.semantic_v5
        semantic = semantic_state.model_dump(mode="json")
        discovery_outputs = semantic_state.discovery_outputs
        originals = tuple(original for batch in discovery_outputs for original in batch.candidates)
        topic_chains = semantic_state.topic_chains
        chain_reviews = semantic_state.topic_chain_reviews
        chain_candidates = tuple(unit for review in chain_reviews for unit in review.candidates)
        slot_map = semantic_state.candidate_slot_map
        expected_slots = {item.candidate_id: item for item in artifact.candidates}
        if {
            item.candidate.candidate_id: item.candidate for item in persisted_candidates
        } != expected_slots:
            raise ValueError("persisted candidates differ from the complete V5 rough artifact")
        chain_map = {value.topic_chain_id: value for value in topic_chains}

        boundary_prompt = load_lineage_prompt(
            "boundary_review", work.config.semantic_profile, ClipProfile.MINI_LESSON
        )
        _assert_semantic_global_prompt(work, boundary_prompt)
        boundary_provider = self._structured_provider(work, boundary_prompt)
        boundary_requests: list[
            tuple[
                str,
                dict[str, object],
                Callable[[BoundaryReviewV5], BoundaryReviewV5],
            ]
        ] = []
        for candidate in chain_candidates:
            chain = chain_map[candidate.topic_chain_id]
            payload = build_boundary_payload_v5(
                candidate,
                chain=chain,
                originals=originals,
                transcript=transcript,
                source_id=work.project_id,
                source_hash=source_hash,
                prompt_hash=boundary_prompt.sha256,
                semantic_profile=work.config.semantic_profile,
            )
            authority = BoundaryAuthorityV5.model_validate_json(json.dumps(payload["authority"]))

            def validate_boundary(
                value: BoundaryReviewV5,
                *,
                current_candidate: ChainCandidateV5 = candidate,
                current_authority: BoundaryAuthorityV5 = authority,
            ) -> BoundaryReviewV5:
                return validate_boundary_review_v5(
                    value,
                    authority=current_authority,
                    unit=current_candidate,
                    transcript=transcript,
                )

            boundary_requests.append((candidate.candidate_id, payload, validate_boundary))
        boundaries_by_id: dict[str, BoundaryReviewV5] = {}
        boundary_audit: dict[str, object] = {
            "stage": "boundary_review",
            "request_count": 0,
            "cache_hit_count": 0,
            "agent_outputs": [],
            "validation_events": [],
        }
        if boundary_requests:
            boundaries_by_id, boundary_audit = self._run_v4_requests(
                work,
                fence=fence,
                project_dir=project_dir,
                generation_dir=generation_dir,
                stage="boundary_review",
                provider=boundary_provider,
                response_model=BoundaryReviewV5,
                requests=tuple(boundary_requests),
                cancel_requested=cancel_requested,
            )
        boundary_reviews = tuple(boundaries_by_id[value.candidate_id] for value in chain_candidates)

        quality_candidates = tuple(
            project_quality_v4(ChainCandidateV4, value) for value in chain_candidates
        )
        quality_boundaries = tuple(
            project_quality_v4(BoundaryReviewV4, value) for value in boundary_reviews
        )

        global_output: GlobalReviewOutputV4 | None = None
        global_audit: dict[str, object] = {
            "stage": "global_review",
            "request_count": 0,
            "cache_hit_count": 0,
            "agent_outputs": [],
            "validation_events": [],
        }
        validated: ValidatedProfileResultV4 | None = None
        if chain_candidates:
            global_prompt = load_semantic_topic_chain_prompt(
                "global_review", work.config.semantic_profile, ClipProfile.MINI_LESSON
            )
            _assert_semantic_global_prompt(work, global_prompt)
            global_provider = self._structured_provider(work, global_prompt)
            global_payload = build_global_review_payload_v4(
                quality_candidates,
                boundary_reviews=quality_boundaries,
                topic_chains=topic_chains,
                transcript=transcript,
                source_hash=source_hash,
                profile=ClipProfile.MINI_LESSON,
                prompt_hash=global_prompt.sha256,
                top_n=work.config.top_n,
            )

            def validate_global(value: GlobalReviewOutputV4) -> GlobalReviewOutputV4:
                validate_profile_global_review_v4(
                    value,
                    candidates=quality_candidates,
                    boundary_reviews=quality_boundaries,
                    transcript=transcript,
                    profile=ClipProfile.MINI_LESSON,
                    top_n=work.config.top_n,
                    score_threshold_exclusive=work.config.semantic_score_threshold,
                    validation_contract=work.config.semantic_validation_contract,
                )
                return value

            global_outputs, global_audit = self._run_v4_requests(
                work,
                fence=fence,
                project_dir=project_dir,
                generation_dir=generation_dir,
                stage="global_review",
                provider=global_provider,
                response_model=GlobalReviewOutputV4,
                requests=(("mini_lesson", global_payload, validate_global),),
                cancel_requested=cancel_requested,
            )
            global_output = global_outputs["mini_lesson"]
            validated = validate_profile_global_review_v4(
                global_output,
                candidates=quality_candidates,
                boundary_reviews=quality_boundaries,
                transcript=transcript,
                profile=ClipProfile.MINI_LESSON,
                top_n=work.config.top_n,
                score_threshold_exclusive=work.config.semantic_score_threshold,
                validation_contract=work.config.semantic_validation_contract,
            )

        by_slot = {value.candidate.candidate_id: value for value in persisted_candidates}
        prepared_values: list[PreparedRevision] = []
        created_at = datetime.now(UTC)
        if validated is not None:
            for rank, selected in enumerate(validated.selected, start=1):
                _check_cancel(cancel_requested)
                review = selected.review
                persistent_key = slot_map[review.candidate_id]
                persisted = by_slot[persistent_key]
                plan = EditPlan(
                    candidate_id=persistent_key,
                    source_start_ms=selected.start_ms,
                    source_end_ms=selected.end_ms,
                    score=float(review.total_score),
                    title=review.title,
                    hook=review.learning_outcome[:80],
                    reason=review.review_reason[:240],
                    layout=Layout.CENTER_CROP,
                    caption_template=CaptionTemplate.CLEAN_ZH_V1,
                    effect=Effect.NONE,
                    risk_flags=tuple(value.value for value in review.risk_flags)[:8],
                    prompt_version="semantic_topic_chain_v1.global_review",
                    model=work.config.llm_model,
                    degraded=False,
                )
                captions = captions_for_clip(
                    transcript.segments,
                    source_start_ms=selected.start_ms,
                    source_end_ms=selected.end_ms,
                )
                prepared_values.append(
                    PreparedRevision(
                        candidate_id=persisted.candidate_id,
                        rank=rank,
                        revision=EditPlanRevision(
                            clip_id=persisted.candidate_id,
                            revision=1,
                            origin=RevisionOrigin.AI,
                            plan=plan,
                            captions=captions,
                            created_at=created_at,
                        ),
                    )
                )
        prepared = tuple(prepared_values)
        profile_result = validated or ValidatedProfileResultV4(
            statistics=ProfileStatisticsV4(
                discovery_candidate_count=0,
                boundary_candidate_count=0,
                qualified_before_top_n=0,
                selected_count=0,
                manual_count=0,
                blocked_count=0,
                rejected_count=0,
                top_n_excluded_count=0,
            )
        )
        stored_prompt_files = cast(dict[str, object], semantic.get("prompt_files", {}))
        run_metadata = {
            "run_id": work.run_id,
            "source_hash": source_hash,
            "profiles": [ClipProfile.MINI_LESSON.value],
            "validation_contract": work.config.semantic_validation_contract,
            "model": work.config.llm_model,
            "model_settings": _semantic_model_settings(work, boundary_provider),
            "prompt_files": {
                **stored_prompt_files,
                "boundary_review": list(boundary_prompt.loaded_files),
                "global_review": (list(global_prompt.loaded_files) if chain_candidates else []),
            },
            "prompt_hashes": {
                "discovery": work.config.semantic_discovery_skill_sha256,
                "link_review": work.config.semantic_link_review_skill_sha256,
                "topic_chain": work.config.semantic_topic_chain_skill_sha256,
                "boundary_review": work.config.semantic_boundary_review_skill_sha256,
                "global_review": work.config.semantic_global_review_skill_sha256,
            },
            "discovery_call_count": _audit_call_count(semantic, "discovery"),
            "link_review_call_count": _link_audit_call_count(semantic),
            "topic_chain_call_count": _audit_call_count(semantic, "topic_chain"),
            "boundary_review_call_count": len(
                cast(list[object], boundary_audit.get("call_records", []))
            ),
            "global_review_call_count": len(
                cast(list[object], global_audit.get("call_records", []))
            ),
            "repair_call_count": _audit_repair_count(semantic, boundary_audit, global_audit),
            "cache_hit_count": _audit_cache_hit_count(semantic, boundary_audit, global_audit),
            "input_tokens": _audit_metric_total(
                semantic, boundary_audit, global_audit, key="input_tokens"
            ),
            "output_tokens": _audit_metric_total(
                semantic, boundary_audit, global_audit, key="output_tokens"
            ),
            "latency_ms": _audit_metric_total(
                semantic, boundary_audit, global_audit, key="latency_ms"
            ),
        }
        ledger = build_lineage_ledger_v5(
            batches=discovery_outputs,
            chains=topic_chains,
            reviews=chain_reviews,
            boundaries=boundary_reviews,
            partition=final_partition_v5(profile_result),
            transcript=transcript,
        )
        unified = UnifiedSemanticResultV5(
            run_id=work.run_id,
            project_id=work.project_id,
            config_fingerprint=work.config.fingerprint,
            source_hash=source_hash,
            run_metadata={**run_metadata, "lineage_contract": LINEAGE_CONTRACT},
            profiles={ClipProfile.MINI_LESSON: lineage_profile_v5(profile_result, ledger)},
            lineage=ledger,
            candidate_slot_map=slot_map,
            persistent_candidate_ids={
                unit.candidate_id: by_slot[slot_map[unit.candidate_id]].candidate_id
                for unit in chain_candidates
            },
            global_review=global_output,
            stage_audits={"boundary_review": boundary_audit, "global_review": global_audit},
        )
        return prepared, {"semantic_v5": unified.model_dump(mode="json")}

    def _mini_lesson_candidates(
        self,
        work: StageWork,
        *,
        lease: LeaseIdentity,
        cancel_requested: Callable[[], bool],
        project_dir: Path,
        generation_dir: Path,
        transcript: TranscriptDocument,
        source_hash: str,
        reservation: AssetReservation,
    ) -> StageExecutionResult:
        """Discover and semantically connect cross-window mini-lesson topics."""

        profile = ClipProfile.MINI_LESSON
        semantic_config = _semantic_global_config(work)
        fence = _mutation_fence(work, lease)
        discovery_prompt = load_semantic_topic_chain_prompt(
            "discovery", work.config.semantic_profile, profile
        )
        _assert_semantic_global_prompt(work, discovery_prompt)
        input_plan = plan_semantic_windowed_input(
            transcript,
            prompt=discovery_prompt.instructions,
            config=semantic_config,
            structured_budget_errors=getattr(work.config, "semantic_transport_contract", None)
            is not None,
        )
        normalization_events: list[dict[str, str]] = []
        discovery_requests: list[
            tuple[
                str,
                dict[str, object],
                Callable[[DiscoveryBatchOutputV4], DiscoveryBatchOutputV4],
            ]
        ] = []
        for unit in input_plan.units:
            payload = build_discovery_payload_v4(
                unit,
                source_id=work.project_id,
                source_hash=source_hash,
                profile=profile,
                prompt_hash=discovery_prompt.sha256,
            )
            expected_context = TimeRangeV4.model_validate(payload["batch_context"])
            expected_ownership = TimeRangeV4.model_validate(payload["ownership_interval"])
            expected_windows = tuple(
                TimeRangeV4(
                    start_ms=value.start_ms,
                    end_ms=value.end_ms,
                )
                for value in unit.logical_windows_ms
            )

            def validate_discovery(
                value: DiscoveryBatchOutputV4,
                *,
                current_unit: SemanticInputUnit = unit,
                context: TimeRangeV4 = expected_context,
                ownership: TimeRangeV4 = expected_ownership,
                windows: tuple[TimeRangeV4, ...] = expected_windows,
            ) -> DiscoveryBatchOutputV4:
                normalized, notes = namespace_discovery_batch_v4(value)
                normalization_events.extend(
                    {"batch_id": current_unit.unit_id, "normalization": note} for note in notes
                )
                return validate_discovery_batch_v4(
                    normalized,
                    expected_batch_id=current_unit.unit_id,
                    expected_context=context,
                    expected_ownership=ownership,
                    expected_windows=windows,
                    transcript=transcript,
                    available_cue_ids=tuple(cue.cue_id for cue in current_unit.cues),
                )

            discovery_requests.append((unit.unit_id, payload, validate_discovery))
        discovery_provider = self._structured_provider(work, discovery_prompt)
        discovered, discovery_audit = self._run_v4_requests(
            work,
            fence=fence,
            project_dir=project_dir,
            generation_dir=generation_dir,
            stage="discovery",
            provider=discovery_provider,
            response_model=DiscoveryBatchOutputV4,
            requests=tuple(discovery_requests),
            cancel_requested=cancel_requested,
        )
        discovery_outputs = tuple(discovered[unit.unit_id] for unit in input_plan.units)
        all_fragments = tuple(
            fragment for output in discovery_outputs for fragment in output.topic_fragments
        )
        if len({value.topic_fragment_id for value in all_fragments}) != len(all_fragments):
            raise ValueError("Discovery Topic Fragment IDs are not globally unique")

        link_prompt = load_semantic_topic_chain_prompt(
            "link_review", work.config.semantic_profile, profile
        )
        _assert_semantic_global_prompt(work, link_prompt)
        link_provider = self._structured_provider(work, link_prompt)
        all_link_requests: list[LinkReviewRequestV4] = list(
            plan_link_review_requests_v4(discovery_outputs)
        )
        completed_links: dict[str, LinkReviewV4] = {}
        link_round_audits: list[dict[str, object]] = []
        pending_links = tuple(all_link_requests)
        while pending_links:
            link_requests: list[
                tuple[
                    str,
                    dict[str, object],
                    Callable[[LinkReviewV4], LinkReviewV4],
                ]
            ] = []
            for request in pending_links:
                payload = build_link_review_payload_v4(
                    request,
                    transcript=transcript,
                    source_hash=source_hash,
                    profile=profile,
                    prompt_hash=link_prompt.sha256,
                )

                def validate_link(
                    value: LinkReviewV4,
                    *,
                    current_request: LinkReviewRequestV4 = request,
                ) -> LinkReviewV4:
                    return validate_link_review_v4(
                        value, request=current_request, transcript=transcript
                    )

                link_requests.append((request.link_review_id, payload, validate_link))
            linked, link_audit = self._run_v4_requests(
                work,
                fence=fence,
                project_dir=project_dir,
                generation_dir=generation_dir,
                stage="link_review",
                provider=link_provider,
                response_model=LinkReviewV4,
                requests=tuple(link_requests),
                cancel_requested=cancel_requested,
            )
            completed_links.update(linked)
            link_round_audits.append(link_audit)
            followups = plan_followup_link_review_requests_v4(
                discovery_outputs,
                existing_requests=tuple(all_link_requests),
                completed_reviews=tuple(completed_links.values()),
            )
            all_link_requests.extend(followups)
            pending_links = followups
        link_outputs = tuple(completed_links[value.link_review_id] for value in all_link_requests)
        topic_chains = assemble_topic_chains_v4(all_fragments, link_outputs)

        chain_prompt = load_semantic_topic_chain_prompt(
            "topic_chain", work.config.semantic_profile, profile
        )
        _assert_semantic_global_prompt(work, chain_prompt)
        chain_provider = self._structured_provider(work, chain_prompt)
        chain_requests: list[
            tuple[
                str,
                dict[str, object],
                Callable[[TopicChainReviewV4], TopicChainReviewV4],
            ]
        ] = []
        for chain in topic_chains:
            payload = build_topic_chain_review_payload_v4(
                chain,
                transcript=transcript,
                source_hash=source_hash,
                profile=profile,
                prompt_hash=chain_prompt.sha256,
                link_reviews=link_outputs,
            )

            def validate_chain(
                value: TopicChainReviewV4,
                *,
                current_chain: TopicChainV4 = chain,
            ) -> TopicChainReviewV4:
                validated = validate_topic_chain_review_v4(
                    value, chain=current_chain, transcript=transcript
                )
                if any(item.clip_profile != profile for item in validated.candidates):
                    raise ValueError("mini_lesson chain emitted a competing Profile")
                return validated

            chain_requests.append((chain.topic_chain_id, payload, validate_chain))
        chain_reviews_by_id: dict[str, TopicChainReviewV4] = {}
        chain_audit: dict[str, object] = {
            "stage": "topic_chain",
            "request_count": 0,
            "cache_hit_count": 0,
            "agent_outputs": [],
            "validation_events": [],
        }
        if chain_requests:
            chain_reviews_by_id, chain_audit = self._run_v4_requests(
                work,
                fence=fence,
                project_dir=project_dir,
                generation_dir=generation_dir,
                stage="topic_chain",
                provider=chain_provider,
                response_model=TopicChainReviewV4,
                requests=tuple(chain_requests),
                cancel_requested=cancel_requested,
            )
        chain_reviews = tuple(chain_reviews_by_id[value.topic_chain_id] for value in topic_chains)
        chain_candidates = tuple(
            candidate for review in chain_reviews for candidate in review.candidates
        )
        if len({value.candidate_id for value in chain_candidates}) != len(chain_candidates):
            raise ValueError("Topic Chain candidate IDs are not globally unique")
        candidate_slots, slot_map = _candidate_slots_from_v4(transcript, chain_candidates)
        coverage_decisions = [
            {
                "source_id": value.candidate_id,
                "source_kind": "candidate",
                "destination_id": None,
                "disposition": "discovered",
                "reason": "Discovery high-recall candidate retained in the audit ledger.",
            }
            for output in discovery_outputs
            for value in output.candidates
        ]
        coverage_decisions.extend(
            {
                "source_id": value.topic_fragment_id,
                "source_kind": "fragment",
                "destination_id": next(
                    (
                        chain.topic_chain_id
                        for chain in topic_chains
                        if value.topic_fragment_id in chain.fragment_ids
                    ),
                    None,
                ),
                "disposition": "linked",
                "reason": "Fragment retained in its Agent-linked Topic Chain.",
            }
            for value in all_fragments
        )
        coverage_decisions.extend(
            {
                "source_id": value.topic_chain_id,
                "source_kind": "topic_chain",
                "destination_id": (
                    review.candidates[0].candidate_id if review.candidates else None
                ),
                "disposition": "chain_candidate" if review.candidates else "rejected",
                "reason": review.rejection_reason or "Agent produced a complete Profile candidate.",
            }
            for value in topic_chains
            for review in (chain_reviews_by_id[value.topic_chain_id],)
        )
        artifact_payload: dict[str, object] = {
            "schema_version": "4",
            "config": {
                "algorithm": work.config.clipping_algorithm,
                "clip_profile": profile.value,
                "minimum_clip_ms": work.config.minimum_clip_ms,
                "target_clip_ms": work.config.semantic_target_clip_ms,
                "maximum_clip_ms": work.config.maximum_clip_ms,
                "top_n": work.config.top_n,
                "top_n_phase": "after_final_validation",
            },
            "candidates": [value.model_dump(mode="json") for value in candidate_slots],
            "semantic_v4": {
                "source_hash": source_hash,
                "input_plan": input_plan.model_dump(mode="json"),
                "discovery_outputs": [value.model_dump(mode="json") for value in discovery_outputs],
                "link_review_requests": [
                    value.model_dump(mode="json") for value in all_link_requests
                ],
                "link_reviews": [value.model_dump(mode="json") for value in link_outputs],
                "topic_chains": [value.model_dump(mode="json") for value in topic_chains],
                "topic_chain_reviews": [value.model_dump(mode="json") for value in chain_reviews],
                "chain_candidates": [value.model_dump(mode="json") for value in chain_candidates],
                "candidate_slot_map": slot_map,
                "coverage_decisions": coverage_decisions,
                "normalization_events": normalization_events,
                "prompt_files": {
                    "discovery": list(discovery_prompt.loaded_files),
                    "link_review": list(link_prompt.loaded_files),
                    "topic_chain": list(chain_prompt.loaded_files),
                },
                "stage_audits": {
                    "discovery": discovery_audit,
                    "link_review_rounds": link_round_audits,
                    "topic_chain": chain_audit,
                },
            },
        }
        write_json_no_clobber(project_dir / reservation.relative_path, artifact_payload)
        committed = self._commit(
            lease,
            reservation,
            project_dir=project_dir,
            validation={
                "schema_version": "4",
                "clip_profile": profile.value,
                "candidate_count": len(candidate_slots),
                "fragment_count": len(all_fragments),
                "topic_chain_count": len(topic_chains),
                "link_review_count": len(link_outputs),
            },
        )
        persisted = self._state.save_candidates(fence, candidates=candidate_slots)
        return self._result(
            work.stage,
            (committed,),
            {"candidate_count": len(persisted)},
        )

    def _mini_lesson_edit(
        self,
        work: StageWork,
        *,
        fence: StageMutationFence,
        project_dir: Path,
        generation_dir: Path,
        transcript: TranscriptDocument,
        persisted_candidates: tuple[PersistedCandidate, ...],
        cancel_requested: Callable[[], bool],
    ) -> tuple[tuple[PreparedRevision, ...], dict[str, object]]:
        """Run candidate-local boundaries and an independent mini-lesson ranking."""

        rough_payload = json.loads(
            self._committed_asset_bytes(
                work,
                project_dir=project_dir,
                kind="rough_candidates",
                relative_path=_generation_relative(
                    work.generation, "candidates/rough-candidates.json"
                ),
                max_bytes=128 * 1024 * 1024,
            )
        )
        if not isinstance(rough_payload, dict) or not isinstance(
            rough_payload.get("semantic_v4"), dict
        ):
            raise ValueError("mini_lesson Topic Chain artifact is missing")
        semantic = cast(dict[str, object], rough_payload["semantic_v4"])
        source_hash = str(semantic["source_hash"])
        discovery_outputs = tuple(
            DiscoveryBatchOutputV4.model_validate_json(json.dumps(value, ensure_ascii=False))
            for value in cast(list[object], semantic["discovery_outputs"])
        )
        link_reviews = tuple(
            LinkReviewV4.model_validate_json(json.dumps(value, ensure_ascii=False))
            for value in cast(list[object], semantic["link_reviews"])
        )
        topic_chains = tuple(
            TopicChainV4.model_validate_json(json.dumps(value, ensure_ascii=False))
            for value in cast(list[object], semantic["topic_chains"])
        )
        chain_candidates = tuple(
            ChainCandidateV4.model_validate_json(json.dumps(value, ensure_ascii=False))
            for value in cast(list[object], semantic["chain_candidates"])
        )
        raw_slot_map = cast(dict[str, object], semantic["candidate_slot_map"])
        slot_map = {key: str(value) for key, value in raw_slot_map.items()}
        if set(slot_map) != {value.candidate_id for value in chain_candidates}:
            raise ValueError("mini_lesson persistent slot map is incomplete")
        chain_map = {value.topic_chain_id: value for value in topic_chains}

        boundary_prompt = load_semantic_topic_chain_prompt(
            "boundary_review", work.config.semantic_profile, ClipProfile.MINI_LESSON
        )
        _assert_semantic_global_prompt(work, boundary_prompt)
        boundary_provider = self._structured_provider(work, boundary_prompt)
        boundary_requests: list[
            tuple[
                str,
                dict[str, object],
                Callable[[BoundaryReviewV4], BoundaryReviewV4],
            ]
        ] = []
        for candidate in chain_candidates:
            chain = chain_map[candidate.topic_chain_id]
            payload = build_boundary_review_payload_v4(
                candidate,
                chain=chain,
                transcript=transcript,
                source_hash=source_hash,
                prompt_hash=boundary_prompt.sha256,
                discovery_evidence=discovery_outputs,
                link_reviews=link_reviews,
            )

            def validate_boundary(
                value: BoundaryReviewV4,
                *,
                current_candidate: ChainCandidateV4 = candidate,
            ) -> BoundaryReviewV4:
                return validate_boundary_review_v4(
                    value,
                    candidate=current_candidate,
                    transcript=transcript,
                    validation_contract=work.config.semantic_validation_contract,
                )

            boundary_requests.append((candidate.candidate_id, payload, validate_boundary))
        boundaries_by_id: dict[str, BoundaryReviewV4] = {}
        boundary_audit: dict[str, object] = {
            "stage": "boundary_review",
            "request_count": 0,
            "cache_hit_count": 0,
            "agent_outputs": [],
            "validation_events": [],
        }
        if boundary_requests:
            boundaries_by_id, boundary_audit = self._run_v4_requests(
                work,
                fence=fence,
                project_dir=project_dir,
                generation_dir=generation_dir,
                stage="boundary_review",
                provider=boundary_provider,
                response_model=BoundaryReviewV4,
                requests=tuple(boundary_requests),
                cancel_requested=cancel_requested,
            )
        boundary_reviews = tuple(boundaries_by_id[value.candidate_id] for value in chain_candidates)

        global_output: GlobalReviewOutputV4 | None = None
        global_audit: dict[str, object] = {
            "stage": "global_review",
            "request_count": 0,
            "cache_hit_count": 0,
            "agent_outputs": [],
            "validation_events": [],
        }
        validated: ValidatedProfileResultV4 | None = None
        if chain_candidates:
            global_prompt = load_semantic_topic_chain_prompt(
                "global_review", work.config.semantic_profile, ClipProfile.MINI_LESSON
            )
            _assert_semantic_global_prompt(work, global_prompt)
            global_provider = self._structured_provider(work, global_prompt)
            global_payload = build_global_review_payload_v4(
                chain_candidates,
                boundary_reviews=boundary_reviews,
                topic_chains=topic_chains,
                transcript=transcript,
                source_hash=source_hash,
                profile=ClipProfile.MINI_LESSON,
                prompt_hash=global_prompt.sha256,
                top_n=work.config.top_n,
            )

            def validate_global(value: GlobalReviewOutputV4) -> GlobalReviewOutputV4:
                validate_profile_global_review_v4(
                    value,
                    candidates=chain_candidates,
                    boundary_reviews=boundary_reviews,
                    transcript=transcript,
                    profile=ClipProfile.MINI_LESSON,
                    top_n=work.config.top_n,
                    score_threshold_exclusive=work.config.semantic_score_threshold,
                    validation_contract=work.config.semantic_validation_contract,
                )
                return value

            global_outputs, global_audit = self._run_v4_requests(
                work,
                fence=fence,
                project_dir=project_dir,
                generation_dir=generation_dir,
                stage="global_review",
                provider=global_provider,
                response_model=GlobalReviewOutputV4,
                requests=(("mini_lesson", global_payload, validate_global),),
                cancel_requested=cancel_requested,
            )
            global_output = global_outputs["mini_lesson"]
            validated = validate_profile_global_review_v4(
                global_output,
                candidates=chain_candidates,
                boundary_reviews=boundary_reviews,
                transcript=transcript,
                profile=ClipProfile.MINI_LESSON,
                top_n=work.config.top_n,
                score_threshold_exclusive=work.config.semantic_score_threshold,
                validation_contract=work.config.semantic_validation_contract,
            )

        by_slot = {value.candidate.candidate_id: value for value in persisted_candidates}
        prepared_values: list[PreparedRevision] = []
        created_at = datetime.now(UTC)
        if validated is not None:
            for rank, selected in enumerate(validated.selected, start=1):
                _check_cancel(cancel_requested)
                review = selected.review
                persistent_key = slot_map[review.candidate_id]
                persisted = by_slot[persistent_key]
                plan = EditPlan(
                    candidate_id=persistent_key,
                    source_start_ms=selected.start_ms,
                    source_end_ms=selected.end_ms,
                    score=float(review.total_score),
                    title=review.title,
                    hook=review.learning_outcome[:80],
                    reason=review.review_reason[:240],
                    layout=Layout.CENTER_CROP,
                    caption_template=CaptionTemplate.CLEAN_ZH_V1,
                    effect=Effect.NONE,
                    risk_flags=tuple(value.value for value in review.risk_flags)[:8],
                    prompt_version="semantic_topic_chain_v1.global_review",
                    model=work.config.llm_model,
                    degraded=False,
                )
                captions = captions_for_clip(
                    transcript.segments,
                    source_start_ms=selected.start_ms,
                    source_end_ms=selected.end_ms,
                )
                prepared_values.append(
                    PreparedRevision(
                        candidate_id=persisted.candidate_id,
                        rank=rank,
                        revision=EditPlanRevision(
                            clip_id=persisted.candidate_id,
                            revision=1,
                            origin=RevisionOrigin.AI,
                            plan=plan,
                            captions=captions,
                            created_at=created_at,
                        ),
                    )
                )
        prepared = tuple(prepared_values)
        profile_result = validated or ValidatedProfileResultV4(
            statistics=ProfileStatisticsV4(
                discovery_candidate_count=0,
                boundary_candidate_count=0,
                qualified_before_top_n=0,
                selected_count=0,
                manual_count=0,
                blocked_count=0,
                rejected_count=0,
                top_n_excluded_count=0,
            )
        )
        prior_coverage = cast(list[dict[str, object]], semantic["coverage_decisions"])
        final_coverage = [*prior_coverage]
        if validated is not None:
            for disposition, values in (
                ("selected", validated.selected),
                ("manual", validated.manual_review),
                ("blocked", validated.blocked),
                ("rejected", validated.rejected),
                ("top_n_excluded", validated.top_n_excluded),
            ):
                final_coverage.extend(
                    {
                        "source_id": value.review.candidate_id,
                        "source_kind": "candidate",
                        "destination_id": (
                            slot_map[value.review.candidate_id]
                            if disposition == "selected"
                            else None
                        ),
                        "disposition": disposition,
                        "reason": ",".join(value.validation_notes)
                        or "Passed Agent review and deterministic gates.",
                    }
                    for value in values
                )
        stored_prompt_files = cast(dict[str, object], semantic.get("prompt_files", {}))
        run_metadata = {
            "run_id": work.run_id,
            "source_hash": source_hash,
            "profiles": [ClipProfile.MINI_LESSON.value],
            "validation_contract": work.config.semantic_validation_contract,
            "model": work.config.llm_model,
            "model_settings": _semantic_model_settings(work, boundary_provider),
            "prompt_files": {
                **stored_prompt_files,
                "boundary_review": list(boundary_prompt.loaded_files),
                "global_review": (list(global_prompt.loaded_files) if chain_candidates else []),
            },
            "prompt_hashes": {
                "discovery": work.config.semantic_discovery_skill_sha256,
                "link_review": work.config.semantic_link_review_skill_sha256,
                "topic_chain": work.config.semantic_topic_chain_skill_sha256,
                "boundary_review": work.config.semantic_boundary_review_skill_sha256,
                "global_review": work.config.semantic_global_review_skill_sha256,
            },
            "discovery_call_count": _audit_call_count(semantic, "discovery"),
            "link_review_call_count": _link_audit_call_count(semantic),
            "topic_chain_call_count": _audit_call_count(semantic, "topic_chain"),
            "boundary_review_call_count": len(
                cast(list[object], boundary_audit.get("call_records", []))
            ),
            "global_review_call_count": len(
                cast(list[object], global_audit.get("call_records", []))
            ),
            "repair_call_count": _audit_repair_count(semantic, boundary_audit, global_audit),
            "cache_hit_count": _audit_cache_hit_count(semantic, boundary_audit, global_audit),
            "input_tokens": _audit_metric_total(
                semantic, boundary_audit, global_audit, key="input_tokens"
            ),
            "output_tokens": _audit_metric_total(
                semantic, boundary_audit, global_audit, key="output_tokens"
            ),
            "latency_ms": _audit_metric_total(
                semantic, boundary_audit, global_audit, key="latency_ms"
            ),
        }
        coverage_models = tuple(
            CoverageDecisionV4.model_validate_json(json.dumps(value, ensure_ascii=False))
            for value in final_coverage
        )
        review_summary = {
            "profile": ClipProfile.MINI_LESSON.value,
            "top_n_before": profile_result.statistics.qualified_before_top_n,
            "top_n_after": profile_result.statistics.selected_count,
        }
        unified = UnifiedSemanticResultV4(
            run_metadata=run_metadata,
            profiles={ClipProfile.MINI_LESSON: profile_result},
            topic_chains=topic_chains,
            coverage_decisions=coverage_models,
            validation_notes=(),
            global_review_summary=review_summary,
        )
        return prepared, {
            "semantic_v4": {
                **unified.model_dump(mode="json"),
                "final_validated": unified.model_dump(mode="json"),
                "boundary_review_raw": [
                    value.model_dump(mode="json") for value in boundary_reviews
                ],
                "global_review_raw": (
                    global_output.model_dump(mode="json") if global_output is not None else None
                ),
                "stage_audits": {
                    "boundary_review": boundary_audit,
                    "global_review": global_audit,
                },
            }
        }

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
            if isinstance(work.config, PipelineRunConfigV9):
                prepared, artifact_extra = self._mini_lesson_edit_v5(
                    work,
                    fence=fence,
                    project_dir=project_dir,
                    generation_dir=generation_dir,
                    transcript=transcript,
                    source_hash=source.sha256,
                    persisted_candidates=candidates,
                    cancel_requested=cancel_requested,
                )
            elif work.config.clip_profile == ClipProfile.MINI_LESSON:
                prepared, artifact_extra = self._mini_lesson_edit(
                    work,
                    fence=fence,
                    project_dir=project_dir,
                    generation_dir=generation_dir,
                    transcript=transcript,
                    persisted_candidates=candidates,
                    cancel_requested=cancel_requested,
                )
            elif work.config.clipping_algorithm in {"semantic_global", "semantic_windowed"}:
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
                v3_enabled = (
                    work.config.semantic_global_review_skill_version == SEMANTIC_GLOBAL_REVIEW_V3
                )
                boundary_outputs: tuple[BoundaryReviewOutputV3, ...] = ()
                boundary_audit: dict[str, object] | None = None
                if v3_enabled:
                    boundary_outputs, boundary_audit = self._boundary_reviews_v3(
                        work,
                        fence=fence,
                        project_dir=project_dir,
                        generation_dir=generation_dir,
                        transcript=transcript,
                        discovery_outputs=discovery_outputs,
                        semantic_config=semantic_config,
                        cancel_requested=cancel_requested,
                    )
                global_prompt = load_installed_global_review_prompt(
                    work.config.semantic_global_review_skill_version,
                    work.config.semantic_profile,
                )
                require_candidate_assessments = candidate_assessments_required(
                    work.config.semantic_global_review_skill_version
                )
                _assert_semantic_global_prompt(work, global_prompt)
                global_payload = (
                    build_global_review_payload_v3(
                        transcript,
                        input_plan=input_plan,
                        discovery_outputs=discovery_outputs,
                        boundary_outputs=boundary_outputs,
                        config=semantic_config,
                        prompt=global_prompt.instructions,
                        structured_budget_errors=getattr(
                            work.config, "semantic_transport_contract", None
                        )
                        is not None,
                    )
                    if v3_enabled
                    else build_global_review_payload(
                        transcript,
                        input_plan=input_plan,
                        discovery_outputs=discovery_outputs,
                        config=semantic_config,
                        prompt=global_prompt.instructions,
                        require_candidate_assessments=require_candidate_assessments,
                        structured_budget_errors=getattr(
                            work.config, "semantic_transport_contract", None
                        )
                        is not None,
                    )
                )
                global_input_tokens = semantic_request_tokens(
                    global_prompt.instructions,
                    global_payload,
                    config=semantic_config,
                )
                global_provider = self._structured_provider(work, global_prompt)
                global_validation_events: list[dict[str, object]] = []
                global_agent_outputs: list[dict[str, object]] = []
                global_output_model = (
                    global_review_response_model_v3(global_payload)
                    if v3_enabled
                    else global_review_response_model(
                        global_payload,
                        require_candidate_assessments=require_candidate_assessments,
                    )
                )
                model_settings = _semantic_model_settings(work, global_provider)
                if getattr(work.config, "semantic_execution_contract", None) is not None:

                    def validate_global_unit(value: BaseModel) -> BaseModel:
                        if v3_enabled:
                            validate_global_review_v3(
                                cast(GlobalReviewOutputV3, value),
                                transcript=transcript,
                                discovery_outputs=discovery_outputs,
                                boundary_outputs=boundary_outputs,
                                config=semantic_config,
                            )
                        else:
                            validate_global_review(
                                cast(GlobalReviewOutput, value),
                                transcript=transcript,
                                discovery_outputs=discovery_outputs,
                                config=semantic_config,
                                input_mode=input_plan.mode,
                                require_candidate_assessments=require_candidate_assessments,
                            )
                        return value

                    global_units, global_audit = self._run_semantic_units(
                        work,
                        fence=fence,
                        project_dir=project_dir,
                        stage="global_review",
                        provider=global_provider,
                        model_settings=model_settings,
                        requests=(
                            SemanticUnitRequest.snapshot(
                                subject_id="global",
                                payload=global_payload,
                                response_model=global_output_model,
                                validate=validate_global_unit,
                                repair_payload=lambda original, output, errors: (
                                    _semantic_repair_request(
                                        work,
                                        original,
                                        output,
                                        validation_errors=errors,
                                    )
                                ),
                            ),
                        ),
                        cancel_requested=cancel_requested,
                    )
                    global_output = cast(
                        GlobalReviewOutput | GlobalReviewOutputV3, global_units["global"]
                    )
                    global_cache_hit = cast(dict[str, bool], global_audit["cache_hits"])["global"]
                    global_agent_outputs = cast(
                        list[dict[str, object]], global_audit["agent_outputs"]
                    )
                    global_validation_events = cast(
                        list[dict[str, object]], global_audit["validation_events"]
                    )
                    validated = (
                        validate_global_review_v3(
                            cast(GlobalReviewOutputV3, global_output),
                            transcript=transcript,
                            discovery_outputs=discovery_outputs,
                            boundary_outputs=boundary_outputs,
                            config=semantic_config,
                        )
                        if v3_enabled
                        else validate_global_review(
                            cast(GlobalReviewOutput, global_output),
                            transcript=transcript,
                            discovery_outputs=discovery_outputs,
                            config=semantic_config,
                            input_mode=input_plan.mode,
                            require_candidate_assessments=require_candidate_assessments,
                        )
                    )
                else:
                    global_cache_dir = generation_dir / "editing/semantic-cache/global_review"
                    global_cache_key = semantic_stage_cache_key(
                        stage="global_review",
                        payload=global_payload,
                        provider=global_provider,
                        model_settings=model_settings,
                        output_model=global_output_model,
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
                        output_model=global_output_model,
                    )
                    global_cache_hit = cached_global is not None
                    if cached_global is not None:
                        global_output = cached_global
                        validated = (
                            validate_global_review_v3(
                                cast(GlobalReviewOutputV3, global_output),
                                transcript=transcript,
                                discovery_outputs=discovery_outputs,
                                boundary_outputs=boundary_outputs,
                                config=semantic_config,
                            )
                            if v3_enabled
                            else validate_global_review(
                                cast(GlobalReviewOutput, global_output),
                                transcript=transcript,
                                discovery_outputs=discovery_outputs,
                                config=semantic_config,
                                input_mode=input_plan.mode,
                                require_candidate_assessments=require_candidate_assessments,
                            )
                        )
                    else:
                        try:
                            result = global_provider.generate(
                                subject_id=work.run_id,
                                payload=global_payload,
                                response_model=global_output_model,
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
                        global_agent_outputs.append(
                            {
                                "phase": "initial_or_schema_repaired",
                                "repaired": result.repaired,
                                "repair_attempts": list(result.repair_attempts),
                                "output": result.output.model_dump(mode="json"),
                            }
                        )
                        try:
                            global_output = result.output
                            validated = (
                                validate_global_review_v3(
                                    cast(GlobalReviewOutputV3, global_output),
                                    transcript=transcript,
                                    discovery_outputs=discovery_outputs,
                                    boundary_outputs=boundary_outputs,
                                    config=semantic_config,
                                )
                                if v3_enabled
                                else validate_global_review(
                                    cast(GlobalReviewOutput, global_output),
                                    transcript=transcript,
                                    discovery_outputs=discovery_outputs,
                                    config=semantic_config,
                                    input_mode=input_plan.mode,
                                    require_candidate_assessments=require_candidate_assessments,
                                )
                            )
                        except ValueError as exc:
                            global_validation_events.append(
                                {
                                    "stage": "global_review",
                                    "error": _semantic_error_detail(work, exc, legacy_limit=1_000),
                                }
                            )
                            if result.repaired:
                                raise StructuredProviderError(
                                    "STRUCTURED_OUTPUT_INVALID",
                                    (),
                                    repair_attempts=result.repair_attempts,
                                ) from exc
                            try:
                                repaired = global_provider.repair(
                                    subject_id=work.run_id,
                                    payload=_semantic_repair_request(
                                        work,
                                        global_payload,
                                        result.output,
                                        validation_errors=(
                                            _semantic_error_detail(work, exc, legacy_limit=500),
                                        ),
                                    ),
                                    response_model=global_output_model,
                                    validation_errors=(
                                        _semantic_error_detail(work, exc, legacy_limit=240),
                                    ),
                                    cancel_requested=cancel_requested,
                                )
                            except StructuredProviderError as repair_exc:
                                self._state.record_provider_calls(
                                    fence,
                                    repair_exc.call_records,
                                    cache_hit=False,
                                )
                                if (
                                    getattr(work.config, "semantic_transport_contract", None)
                                    is not None
                                ):
                                    aggregate = _aggregate_semantic_failures(
                                        [repair_exc],
                                        (*result.call_records, *repair_exc.call_records),
                                    )
                                    raise StructuredProviderError(
                                        aggregate.code,
                                        aggregate.call_records,
                                        repair_attempts=(
                                            *aggregate.repair_attempts,
                                            {
                                                "phase": "stage_validation",
                                                "semantic_stage": "global_review",
                                                "agent_outputs": global_agent_outputs,
                                                "validation_events": global_validation_events,
                                            },
                                        ),
                                    ) from repair_exc
                                raise
                            self._state.record_provider_calls(
                                fence,
                                repaired.call_records,
                                cache_hit=False,
                            )
                            global_output = repaired.output
                            global_agent_outputs.append(
                                {
                                    "phase": "domain_repair",
                                    "repaired": True,
                                    "repair_attempts": list(repaired.repair_attempts),
                                    "output": repaired.output.model_dump(mode="json"),
                                }
                            )
                            try:
                                validated = (
                                    validate_global_review_v3(
                                        cast(GlobalReviewOutputV3, global_output),
                                        transcript=transcript,
                                        discovery_outputs=discovery_outputs,
                                        boundary_outputs=boundary_outputs,
                                        config=semantic_config,
                                    )
                                    if v3_enabled
                                    else validate_global_review(
                                        cast(GlobalReviewOutput, global_output),
                                        transcript=transcript,
                                        discovery_outputs=discovery_outputs,
                                        config=semantic_config,
                                        input_mode=input_plan.mode,
                                        require_candidate_assessments=(
                                            require_candidate_assessments
                                        ),
                                    )
                                )
                            except ValueError as repair_validation_error:
                                global_validation_events.append(
                                    {
                                        "stage": "global_review_repair",
                                        "error": _semantic_error_detail(
                                            work, repair_validation_error, legacy_limit=1_000
                                        ),
                                    }
                                )
                                raise StructuredProviderError(
                                    "STRUCTURED_OUTPUT_INVALID",
                                    (),
                                    repair_attempts=repaired.repair_attempts,
                                ) from repair_validation_error
                        write_semantic_stage_cache(
                            cache_dir=global_cache_dir,
                            cache_key=global_cache_key,
                            stage="global_review",
                            payload=global_payload,
                            provider=global_provider,
                            model_settings=model_settings,
                            output=global_output,
                        )
                retained_clips = _materialized_global_review_clips(validated)
                if len(retained_clips) > len(candidates):
                    raise ValueError(
                        "semantic global retained more clips than persisted output slots"
                    )
                prepared_values: list[PreparedRevision] = []
                created_at = datetime.now(UTC)
                for rank, (reviewed, slot) in enumerate(
                    zip(retained_clips, candidates, strict=False),
                    start=1,
                ):
                    _check_cancel(cancel_requested)
                    if isinstance(reviewed, ValidatedCandidateReviewV3):
                        title = reviewed.review.title
                        hook = reviewed.review.hook
                        reason = reviewed.review.review_reason
                        risk_flags = _global_review_v3_risk_flags(reviewed)
                    else:
                        title = reviewed.clip.title
                        hook = reviewed.clip.hook
                        reason = reviewed.clip.review_reason
                        risk_flags = _global_review_risk_flags(reviewed)
                    plan = EditPlan(
                        candidate_id=slot.candidate.candidate_id,
                        source_start_ms=reviewed.start_ms,
                        source_end_ms=reviewed.end_ms,
                        score=float(reviewed.final_score),
                        title=title,
                        hook=hook[:80],
                        reason=reason[:240],
                        layout=Layout.CENTER_CROP,
                        caption_template=CaptionTemplate.CLEAN_ZH_V1,
                        effect=Effect.NONE,
                        risk_flags=risk_flags,
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
                if isinstance(validated, ValidatedGlobalReviewV3):
                    validated_payload: dict[str, object] = {
                        "selected": [
                            _validated_global_v3_payload(value) for value in validated.selected
                        ],
                        "manual_review": [
                            _validated_global_v3_payload(value) for value in validated.manual_review
                        ],
                        "blocked": [
                            _validated_global_v3_payload(value) for value in validated.blocked
                        ],
                        "rejected": [
                            _validated_global_v3_payload(value) for value in validated.rejected
                        ],
                        "top_n_excluded": [
                            _validated_global_v3_payload(value)
                            for value in validated.top_n_excluded
                        ],
                        "statistics": validated.statistics.model_dump(mode="json"),
                        "validation_notes": list(validated.validation_notes),
                    }
                else:
                    validated_payload = {
                        "selected": [
                            _validated_global_clip_payload(value) for value in validated.selected
                        ],
                        "manual_review": [
                            _validated_global_clip_payload(value)
                            for value in validated.manual_review
                        ],
                        "rejected": [
                            _validated_global_clip_payload(value) for value in validated.rejected
                        ],
                        "rejected_candidates": [
                            value.model_dump(mode="json") for value in validated.rejected_candidates
                        ],
                        "coverage_decisions": [
                            value.model_dump(mode="json") for value in validated.coverage_decisions
                        ],
                        "global_review_summary": (
                            validated.global_review_summary.model_dump(mode="json")
                        ),
                        "validation_notes": list(validated.validation_notes),
                    }
                raw_trace_candidates = global_payload.get("candidates")
                trace_candidates = (
                    raw_trace_candidates if isinstance(raw_trace_candidates, list) else []
                )
                artifact_extra = {
                    "semantic_global": {
                        "raw_global_review": global_output.model_dump(mode="json"),
                        "validated": validated_payload,
                        "boundary_review": boundary_audit,
                        "boundary_review_outputs": [
                            value.model_dump(mode="json") for value in boundary_outputs
                        ],
                        "global_agent_outputs": global_agent_outputs,
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
                            "model": global_provider.model_name,
                            "candidate_source_traces": [
                                value.get("source_trace")
                                for value in trace_candidates
                                if isinstance(value, dict)
                            ],
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
        if isinstance(work.config, PipelineRunConfigV9):
            self._validate_saved_mini_edit_v5(
                work,
                serialized=read_regular_file_no_follow(artifact_path, max_bytes=32 * 1024 * 1024),
                project_dir=project_dir,
                transcript=transcript,
                source_hash=source.sha256,
                candidates=candidates,
                prepared=prepared,
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

    def _require_action_capabilities(
        self, work: StageWork, required: tuple[PipelineCapability, ...]
    ) -> None:
        if getattr(work.config, "semantic_execution_contract", None) is None:
            return
        runtime_provider = getattr(self, "_runtime_provider", None)
        if runtime_provider is not None and runtime_provider != work.config.provider:
            raise ActionNotReady(ActionReadiness(required, (), ("PERSISTED_PROVIDER_MISMATCH",)))
        readiness_check = getattr(self, "_readiness_check", None)
        if readiness_check is not None:
            readiness_check(work.config, required)

    def _asr_provider(
        self, work: StageWork
    ) -> MockASRProvider | OpenAIASRProvider | OpenRouterASRProvider | MLXASRProvider:
        self._require_action_capabilities(
            work, ("asr", "semantic") if work.config.run_scope == "full" else ("asr",)
        )
        if work.config.provider in {"mock", "mock-codex"}:
            provider: (
                MockASRProvider | OpenAIASRProvider | OpenRouterASRProvider | MLXASRProvider
            ) = MockASRProvider(model_name=work.config.transcription_model)
        elif work.config.provider == "openrouter-codex":
            provider = OpenRouterASRProvider(
                api_key=self._openrouter_api_key,
                model_name=work.config.transcription_model,
                base_url=self._openrouter_base_url,
                timeout_seconds=work.config.openai_request_timeout_seconds,
                retry_policy=_retry_policy(work),
            )
        elif work.config.provider == "mlx-codex":
            if self._mlx_asr_model_path is None:
                raise ProviderConfigurationError("MLX ASR model path is not configured")
            provider = MLXASRProvider(
                model_path=self._mlx_asr_model_path,
                model_name=work.config.transcription_model,
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
        self._require_action_capabilities(work, ("semantic",))
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
        elif work.config.provider in {
            "mock-codex",
            "openai-codex",
            "openrouter-codex",
            "mlx-codex",
        }:
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
        self._require_action_capabilities(work, ("semantic",))
        transport_contract = getattr(work.config, "semantic_transport_contract", None)
        # Request accounting depends only on token budgets, not clip-duration settings.
        semantic_budget = (
            SemanticGlobalConfig(
                full_context_budget_ratio=work.config.semantic_full_context_budget_ratio,
                model_context_tokens=work.config.semantic_model_context_tokens,
                tokenizer_name=work.config.semantic_tokenizer_name,
                output_reserve_tokens=work.config.semantic_output_reserve_tokens,
                safety_margin_tokens=work.config.semantic_safety_margin_tokens,
            )
            if transport_contract is not None
            or uses_current_semantic_validation(work.config.semantic_validation_contract)
            else None
        )
        if work.config.provider == "mock":
            return MockStructuredLLMProvider(
                prompts=prompts,
                model_name=work.config.llm_model,
                semantic_budget=semantic_budget,
                transport_contract=transport_contract,
                execution_contract=getattr(work.config, "semantic_execution_contract", None),
            )
        if work.config.provider in {
            "mock-codex",
            "openai-codex",
            "openrouter-codex",
            "mlx-codex",
        }:
            timeout_seconds = work.config.openai_request_timeout_seconds
            if prompts.stage == "global_review":
                timeout_seconds = max(
                    timeout_seconds,
                    CODEX_GLOBAL_REVIEW_TIMEOUT_FLOOR_SECONDS,
                )
            return CodexStructuredLLMProvider(
                prompts=prompts,
                model_name=work.config.llm_model,
                codex_executable=self._codex_executable,
                timeout_seconds=timeout_seconds,
                contract_version=work.config.llm_contract_version,
                semantic_budget=semantic_budget,
                transport_contract=transport_contract,
                execution_contract=getattr(work.config, "semantic_execution_contract", None),
                reasoning_effort=(
                    "high"
                    if prompts.version in {"semantic_global_v2", "semantic_global_v3"}
                    and prompts.stage == "global_review"
                    else "medium"
                ),
            )
        return OpenAIStructuredLLMProvider(
            prompts=prompts,
            model_name=work.config.llm_model,
            api_key=self._openai_api_key,
            timeout_seconds=work.config.openai_request_timeout_seconds,
            retry_policy=_retry_policy(work),
            semantic_budget=semantic_budget,
            transport_contract=transport_contract,
            execution_contract=getattr(work.config, "semantic_execution_contract", None),
        )

    def _run_v4_requests(
        self,
        work: StageWork,
        *,
        fence: StageMutationFence,
        project_dir: Path,
        generation_dir: Path,
        stage: str,
        provider: StructuredLLMProvider,
        response_model: type[V4Output],
        requests: tuple[tuple[str, dict[str, object], Callable[[V4Output], V4Output]], ...],
        cancel_requested: Callable[[], bool],
    ) -> tuple[dict[str, V4Output], dict[str, object]]:
        """Run independently cached v4 semantic tasks with one local repair each."""

        model_settings = {
            **_semantic_model_settings(work, provider),
            "clip_profile": work.config.clip_profile.value,
            "result_schema_version": work.config.semantic_result_schema_version,
        }
        model_settings = semantic_validation_cache_settings(
            model_settings, stage=stage, contract=work.config.semantic_validation_contract
        )
        if isinstance(work.config, PipelineRunConfigV9):
            model_settings["lineage_contract"] = work.config.semantic_lineage_contract
        if stage in {"boundary_review", "global_review"} and uses_current_semantic_validation(
            work.config.semantic_validation_contract
        ):
            # Include the contract in both cache identity and paid-call provenance.
            requests = tuple(
                (
                    subject,
                    {
                        **payload,
                        "validation_contract": work.config.semantic_validation_contract,
                        **(
                            {"score_threshold_exclusive": work.config.semantic_score_threshold}
                            if stage == "global_review"
                            else {}
                        ),
                    },
                    validator,
                )
                for subject, payload, validator in requests
            )
        if getattr(work.config, "semantic_execution_contract", None) is not None:
            units = tuple(
                SemanticUnitRequest.snapshot(
                    subject_id=subject,
                    payload=payload,
                    response_model=response_model,
                    validate=cast(Callable[[BaseModel], BaseModel], validator),
                    repair_payload=lambda original, output, errors: _semantic_repair_payload_v4(
                        original,
                        output,
                        validation_errors=errors,
                    ),
                )
                for subject, payload, validator in requests
            )
            resolved_units, audit = self._run_semantic_units(
                work,
                fence=fence,
                project_dir=project_dir,
                stage=stage,
                provider=provider,
                model_settings=model_settings,
                requests=units,
                cancel_requested=cancel_requested,
            )
            return cast(dict[str, V4Output], resolved_units), audit
        cache_dir = generation_dir / f"semantic-cache/{stage}"
        fallback_dirs = tuple(
            project_dir / _generation_relative(generation, f"semantic-cache/{stage}")
            for generation in range(1, work.generation)
        )
        resolved: dict[str, V4Output] = {}
        cache_hits: dict[str, bool] = {}
        agent_outputs: list[dict[str, object]] = []
        validation_events: list[dict[str, object]] = []
        call_records: list[ProviderCallRecord] = []
        uncached: list[
            tuple[
                str,
                dict[str, object],
                Callable[[V4Output], V4Output],
                str,
            ]
        ] = []
        for subject_id, payload, validator in requests:
            cache_key = semantic_stage_cache_key(
                stage=stage,
                payload=payload,
                provider=provider,
                model_settings=model_settings,
                output_model=response_model,
            )
            cached = load_semantic_stage_cache(
                cache_dirs=(cache_dir, *fallback_dirs),
                cache_key=cache_key,
                stage=stage,
                payload=payload,
                provider=provider,
                model_settings=model_settings,
                output_model=response_model,
            )
            if cached is not None:
                resolved[subject_id] = validator(cached)
                cache_hits[subject_id] = True
            else:
                uncached.append((subject_id, payload, validator, cache_key))

        failures: list[tuple[str, str, StructuredProviderError]] = []
        subject_call_ids: dict[str, list[str]] = {}
        complete_audit = getattr(
            work.config, "semantic_transport_contract", None
        ) is not None or uses_current_semantic_validation(work.config.semantic_validation_contract)
        first_error: StructuredProviderError | None = None
        with ThreadPoolExecutor(
            max_workers=min(
                _semantic_global_config(work).window_discovery_concurrency,
                max(1, len(uncached)),
            ),
            thread_name_prefix=f"semantic-v4-{stage}",
        ) as executor:
            pending = {
                executor.submit(
                    provider.generate,
                    subject_id=f"{work.run_id}.{stage}.{subject_id}",
                    payload=payload,
                    response_model=response_model,
                    cancel_requested=cancel_requested,
                ): (subject_id, payload, validator, cache_key)
                for subject_id, payload, validator, cache_key in uncached
            }
            for future in as_completed(pending):
                subject_id, payload, validator, cache_key = pending[future]
                try:
                    result = future.result()
                except StructuredProviderError as exc:
                    self._state.record_provider_calls(fence, exc.call_records, cache_hit=False)
                    call_records.extend(exc.call_records)
                    subject_call_ids[subject_id] = [record.call_id for record in exc.call_records]
                    failures.append((subject_id, cache_key, exc))
                    first_error = first_error or exc
                    continue
                self._state.record_provider_calls(fence, result.call_records, cache_hit=False)
                call_records.extend(result.call_records)
                subject_call_ids[subject_id] = [record.call_id for record in result.call_records]
                agent_outputs.append(
                    {
                        "subject_id": subject_id,
                        "phase": "initial_or_schema_repaired",
                        "repaired": result.repaired,
                        "repair_attempts": list(result.repair_attempts),
                        "output": result.output.model_dump(mode="json"),
                    }
                )
                try:
                    validated = validator(result.output)
                except ValueError as exc:
                    detail = (
                        str(exc)
                        if complete_audit
                        else _semantic_error_detail(work, exc, legacy_limit=1_000)
                    )
                    validation_events.append(
                        {"subject_id": subject_id, "phase": "initial", "error": detail}
                    )
                    if result.repaired:
                        failure = StructuredProviderError(
                            "STRUCTURED_OUTPUT_INVALID",
                            (),
                            repair_attempts=result.repair_attempts,
                        )
                        failures.append((subject_id, cache_key, failure))
                        first_error = first_error or failure
                        continue
                    try:
                        repaired = provider.repair(
                            subject_id=f"{work.run_id}.{stage}.{subject_id}",
                            payload=_semantic_repair_payload_v4(
                                payload,
                                result.output,
                                validation_errors=(detail,),
                            ),
                            response_model=response_model,
                            validation_errors=(
                                (
                                    detail
                                    if complete_audit
                                    else _semantic_error_detail(work, exc, legacy_limit=500)
                                ),
                            ),
                            cancel_requested=cancel_requested,
                        )
                    except StructuredProviderError as repair_exc:
                        self._state.record_provider_calls(
                            fence, repair_exc.call_records, cache_hit=False
                        )
                        call_records.extend(repair_exc.call_records)
                        subject_call_ids[subject_id].extend(
                            record.call_id for record in repair_exc.call_records
                        )
                        failures.append((subject_id, cache_key, repair_exc))
                        first_error = first_error or repair_exc
                        continue
                    self._state.record_provider_calls(fence, repaired.call_records, cache_hit=False)
                    call_records.extend(repaired.call_records)
                    subject_call_ids[subject_id].extend(
                        record.call_id for record in repaired.call_records
                    )
                    agent_outputs.append(
                        {
                            "subject_id": subject_id,
                            "phase": "domain_repair",
                            "repaired": True,
                            "repair_attempts": list(repaired.repair_attempts),
                            "output": repaired.output.model_dump(mode="json"),
                        }
                    )
                    try:
                        validated = validator(repaired.output)
                    except ValueError as repair_error:
                        validation_events.append(
                            {
                                "subject_id": subject_id,
                                "phase": "repair",
                                "error": str(repair_error)
                                if complete_audit
                                else str(repair_error)[:1_000],
                            }
                        )
                        failure = StructuredProviderError(
                            "STRUCTURED_OUTPUT_INVALID",
                            (),
                            repair_attempts=repaired.repair_attempts,
                        )
                        failures.append((subject_id, cache_key, failure))
                        first_error = first_error or failure
                        continue
                write_semantic_stage_cache(
                    cache_dir=cache_dir,
                    cache_key=cache_key,
                    stage=stage,
                    payload=payload,
                    provider=provider,
                    model_settings=model_settings,
                    output=validated,
                )
                resolved[subject_id] = validated
                cache_hits[subject_id] = False
        if first_error is not None:
            if getattr(work.config, "semantic_transport_contract", None) is not None:
                first_error = _aggregate_semantic_failures(
                    [error for _, _, error in failures], tuple(call_records)
                )
            if complete_audit:
                diagnostic = self._persist_v4_failure_audit(
                    work,
                    fence=fence,
                    project_dir=project_dir,
                    stage=stage,
                    provider=provider,
                    failures=failures,
                    agent_outputs=agent_outputs,
                    validation_events=validation_events,
                    subject_call_ids=subject_call_ids,
                )
                raise StructuredProviderError(
                    first_error.code,
                    tuple(call_records),
                    repair_attempts=first_error.repair_attempts,
                    diagnostic_relative_path=diagnostic,
                ) from first_error
            raise first_error
        if set(resolved) != {value[0] for value in requests}:
            raise ValueError(f"{stage} did not resolve every local semantic request")
        return resolved, {
            "stage": stage,
            "validation_contract": work.config.semantic_validation_contract,
            "provider": provider.provider_name,
            "model": provider.model_name,
            "prompt_version": provider.prompt_version,
            "prompt_sha256": provider.prompt_sha256,
            "request_count": len(requests),
            "cache_hit_count": sum(cache_hits.values()),
            "cache_hits": cache_hits,
            "agent_outputs": sorted(
                agent_outputs,
                key=lambda value: (str(value["subject_id"]), str(value["phase"])),
            ),
            "validation_events": validation_events,
            "call_records": [value.model_dump(mode="json") for value in call_records],
            "latency_ms": sum(value.latency_ms for value in call_records),
            "input_tokens": sum(_provider_usage_tokens(value, "input") for value in call_records),
            "output_tokens": sum(_provider_usage_tokens(value, "output") for value in call_records),
        }

    def _run_semantic_units(
        self,
        work: StageWork,
        *,
        fence: StageMutationFence,
        project_dir: Path,
        stage: str,
        provider: StructuredLLMProvider,
        model_settings: dict[str, object],
        requests: tuple[SemanticUnitRequest, ...],
        cancel_requested: Callable[[], bool],
    ) -> tuple[dict[str, BaseModel], dict[str, object]]:
        secrets = tuple(v for v in (self._openai_api_key, self._openrouter_api_key) if v)
        batch = run_persisted_semantic_units(
            work=work,
            fence=fence,
            project_dir=project_dir,
            state=self._state,
            assets=self._assets,
            stage=stage,
            source_sha256=self._state.load_source(project_id=work.project_id).sha256,
            provider=provider,
            model_settings=model_settings,
            requests=requests,
            concurrency=_semantic_global_config(work).window_discovery_concurrency,
            cancel_requested=cancel_requested,
            redact=lambda value: _redact_semantic_failure_audit(value, secrets),
        )
        outputs = [
            {**item, "subject_id": subject}
            for subject, outcome in batch.outcomes.items()
            for item in outcome.agent_outputs
        ]
        events = [
            {**item, "subject_id": subject}
            for subject, outcome in batch.outcomes.items()
            for item in outcome.validation_events
        ]
        failures = [
            (
                subject,
                batch.request_keys[subject],
                StructuredProviderError(
                    outcome.failure_code or "SEMANTIC_UNIT_INTERNAL_ERROR",
                    outcome.call_records,
                    repair_attempts=outcome.provider_attempts,
                ),
            )
            for subject, outcome in batch.outcomes.items()
            if outcome.disposition != "succeeded"
        ]
        if failures:
            diagnostic = self._persist_v4_failure_audit(
                work,
                fence=fence,
                project_dir=project_dir,
                stage=stage,
                provider=provider,
                failures=failures,
                agent_outputs=outputs,
                validation_events=events,
                subject_call_ids={
                    subject: [call.call_id for call in outcome.call_records]
                    for subject, outcome in batch.outcomes.items()
                },
            )
            aggregate = _aggregate_semantic_failures(
                [error for _, _, error in failures],
                tuple(call for outcome in batch.outcomes.values() for call in outcome.call_records),
            )
            raise SemanticBatchFailure(
                StructuredProviderError(
                    aggregate.code,
                    aggregate.call_records,
                    repair_attempts=aggregate.repair_attempts,
                    diagnostic_relative_path=diagnostic,
                ),
                deterministic=any(
                    outcome.disposition in {"exhausted", "cancelled"}
                    for outcome in batch.outcomes.values()
                ),
            )
        if set(batch.outputs) != {request.subject_id for request in requests}:
            raise SemanticRecoveryError("SEMANTIC_UNIT_EXECUTION_UNCERTAIN")
        calls = tuple(
            call
            for subject, outcome in batch.outcomes.items()
            if not batch.cache_hits[subject]
            for call in outcome.call_records
        )
        return dict(batch.outputs), {
            "stage": stage,
            "validation_contract": work.config.semantic_validation_contract,
            "execution_contract": getattr(work.config, "semantic_execution_contract", None),
            "provider": provider.provider_name,
            "model": provider.model_name,
            "prompt_version": provider.prompt_version,
            "prompt_sha256": provider.prompt_sha256,
            "request_count": len(requests),
            "cache_hit_count": sum(batch.cache_hits.values()),
            "cache_hits": dict(batch.cache_hits),
            "agent_outputs": outputs,
            "validation_events": events,
            "call_records": [call.model_dump(mode="json") for call in calls],
            "latency_ms": sum(call.latency_ms for call in calls),
            "input_tokens": sum(_provider_usage_tokens(call, "input") for call in calls),
            "output_tokens": sum(_provider_usage_tokens(call, "output") for call in calls),
        }

    def _persist_v4_failure_audit(
        self,
        work: StageWork,
        *,
        fence: StageMutationFence,
        project_dir: Path,
        stage: str,
        provider: StructuredLLMProvider,
        failures: list[tuple[str, str, StructuredProviderError]],
        agent_outputs: list[dict[str, object]],
        validation_events: list[dict[str, object]],
        subject_call_ids: dict[str, list[str]],
    ) -> str:
        if stage not in {
            "discovery",
            "link_review",
            "topic_chain",
            "boundary_review",
            "global_review",
        }:
            raise ValueError("semantic audit stage is invalid")
        if (
            fence.project_id,
            fence.run_id,
            fence.stage_run_id,
            fence.generation,
            fence.lease.task_id,
        ) != (
            work.project_id,
            work.run_id,
            work.stage_run_id,
            work.generation,
            work.task_id,
        ):
            raise ValueError("semantic audit fence does not match stage work")
        identity = hashlib.sha256(
            json.dumps(
                [
                    work.stage_run_id,
                    fence.lease.lease_token,
                    stage,
                    sorted((subject, cache_key) for subject, cache_key, _ in failures),
                ],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        prefix = _generation_relative(work.generation, "semantic-audit")
        known_secrets = tuple(
            value for value in (self._openai_api_key, self._openrouter_api_key) if value
        )
        execution_binding = (
            {
                "config_fingerprint": work.config.fingerprint,
                "stage_input_fingerprint": work.input_fingerprint,
                "execution_contract": getattr(work.config, "semantic_execution_contract", None),
            }
            if getattr(work.config, "semantic_execution_contract", None) is not None
            else {}
        )
        manifest_entries: list[dict[str, object]] = []
        for subject, cache_key, error in sorted(failures, key=lambda value: value[0]):
            attempts = list(error.repair_attempts)
            outputs = []
            for value in agent_outputs:
                if value["subject_id"] != subject:
                    continue
                raw_attempts = value.get("repair_attempts")
                if isinstance(raw_attempts, list):
                    attempts.extend(item for item in raw_attempts if isinstance(item, dict))
                outputs.append(
                    {key: item for key, item in value.items() if key != "repair_attempts"}
                )
            unique_attempts = list(
                {
                    json.dumps(value, sort_keys=True, ensure_ascii=False): value
                    for value in attempts
                }.values()
            )
            payload = {
                "schema_version": "1",
                "audit_contract": "semantic-failure-audit-v1",
                "project_id": work.project_id,
                "run_id": work.run_id,
                "stage_run_id": work.stage_run_id,
                "generation": work.generation,
                "stage": stage,
                "subject_id": subject,
                "request_fingerprint": cache_key,
                "validation_contract": work.config.semantic_validation_contract,
                "provider": provider.provider_name,
                "model": provider.model_name,
                "prompt_version": provider.prompt_version,
                "prompt_sha256": provider.prompt_sha256,
                "failure_code": error.code,
                "provider_attempts": unique_attempts,
                "agent_outputs": outputs,
                "validation_events": [
                    value for value in validation_events if value["subject_id"] == subject
                ],
                "call_ids": subject_call_ids.get(subject, []),
                **execution_binding,
            }
            file_id = hashlib.sha256(f"{identity}:{subject}".encode()).hexdigest()
            relative = f"{prefix}/{stage}-{file_id}.json"
            reservation = self._reserve(
                work,
                fence.lease,
                kind="semantic_failure_audit",
                relative_path=relative,
                mime_type="application/json",
                input_fingerprint=cache_key,
            )
            digest = write_json_no_clobber(
                project_dir / relative,
                _redact_semantic_failure_audit(payload, known_secrets),
            )
            committed = self._commit(
                fence.lease,
                reservation,
                project_dir=project_dir,
                validation={"schema_version": "1", "audit_contract": "semantic-failure-audit-v1"},
                expected_sha256=digest,
            )
            manifest_entries.append(
                {
                    "subject_id": subject,
                    "asset_id": committed.asset_id,
                    "relative_path": relative,
                    "sha256": committed.sha256,
                    "failure_code": error.code,
                }
            )
        relative = (
            (
                attempt_directory(project_dir, fence.lease)
                / "diagnostics"
                / f"{stage}-{identity}-manifest.json"
            )
            .relative_to(project_dir)
            .as_posix()
        )
        reservation = self._reserve(
            work,
            fence.lease,
            kind="semantic_failure_manifest",
            relative_path=relative,
            mime_type="application/json",
            input_fingerprint=identity,
        )
        digest = write_json_no_clobber(
            project_dir / relative,
            _redact_semantic_failure_audit(
                {
                    "schema_version": "1",
                    "audit_contract": "semantic-failure-audit-v1",
                    "run_id": work.run_id,
                    "stage_run_id": work.stage_run_id,
                    "generation": work.generation,
                    "stage": stage,
                    "complete": True,
                    "failed_subjects": manifest_entries,
                    **execution_binding,
                },
                known_secrets,
            ),
        )
        self._commit(
            fence.lease,
            reservation,
            project_dir=project_dir,
            validation={"schema_version": "1", "failed_subject_count": len(manifest_entries)},
            expected_sha256=digest,
        )
        return relative

    def _boundary_reviews_v3(
        self,
        work: StageWork,
        *,
        fence: StageMutationFence,
        project_dir: Path,
        generation_dir: Path,
        transcript: TranscriptDocument,
        discovery_outputs: tuple[DiscoveryOutput, ...],
        semantic_config: SemanticGlobalConfig,
        cancel_requested: Callable[[], bool],
    ) -> tuple[tuple[BoundaryReviewOutputV3, ...], dict[str, object]]:
        prompt = load_semantic_global_v3_boundary_prompt(work.config.semantic_profile)
        _assert_semantic_global_prompt(work, prompt)
        provider = self._structured_provider(work, prompt)
        model_settings = _semantic_model_settings(work, provider)
        if getattr(work.config, "semantic_execution_contract", None) is not None:

            def validator_for(discovery: DiscoveryOutput) -> Callable[[BaseModel], BaseModel]:
                def validate(raw: BaseModel) -> BaseModel:
                    return validate_boundary_review_v3(
                        cast(BoundaryReviewOutputV3, raw),
                        transcript=transcript,
                        discovery=discovery,
                        config=semantic_config,
                    )

                return validate

            units: list[SemanticUnitRequest] = []
            for index, discovery in enumerate(discovery_outputs, start=1):
                payload = build_boundary_review_payload_v3(
                    transcript,
                    discovery=discovery,
                    output_index=index,
                    config=semantic_config,
                )
                if payload is None:
                    continue
                units.append(
                    SemanticUnitRequest.snapshot(
                        subject_id=f"output.{index:03d}",
                        payload=payload,
                        response_model=boundary_review_response_model_v3(payload),
                        validate=validator_for(discovery),
                        repair_payload=lambda original, output, errors: _semantic_repair_request(
                            work,
                            original,
                            output,
                            validation_errors=errors,
                        ),
                    )
                )
            resolved_units, unit_audit = self._run_semantic_units(
                work,
                fence=fence,
                project_dir=project_dir,
                stage="boundary_review",
                provider=provider,
                model_settings=model_settings,
                requests=tuple(units),
                cancel_requested=cancel_requested,
            )
            bounded_outputs = tuple(
                cast(BoundaryReviewOutputV3, resolved_units[unit.subject_id]) for unit in units
            )
            return bounded_outputs, {
                **unit_audit,
                "batch_count": len(bounded_outputs),
                "candidate_count": sum(len(output.reviews) for output in bounded_outputs),
                "prompt": {
                    "version": f"{prompt.version}.{prompt.stage}",
                    "sha256": prompt.sha256,
                    "loaded_files": list(prompt.loaded_files),
                },
            }
        cache_dir = generation_dir / "editing/semantic-cache/boundary_review"
        fallback_cache_dirs = tuple(
            project_dir / _generation_relative(generation, "editing/semantic-cache/boundary_review")
            for generation in range(1, work.generation)
        )
        requests: list[
            tuple[int, DiscoveryOutput, dict[str, object], type[BoundaryReviewOutputV3], str]
        ] = []
        resolved: dict[int, BoundaryReviewOutputV3] = {}
        cache_hits: dict[int, bool] = {}
        validation_events: list[dict[str, object]] = []
        agent_outputs: list[dict[str, object]] = []
        for index, discovery in enumerate(discovery_outputs, start=1):
            payload = build_boundary_review_payload_v3(
                transcript,
                discovery=discovery,
                output_index=index,
                config=semantic_config,
            )
            if payload is None:
                continue
            response_model = boundary_review_response_model_v3(payload)
            cache_key = semantic_stage_cache_key(
                stage="boundary_review",
                payload=payload,
                provider=provider,
                model_settings=model_settings,
                output_model=response_model,
            )
            cached = load_semantic_stage_cache(
                cache_dirs=(cache_dir, *fallback_cache_dirs),
                cache_key=cache_key,
                stage="boundary_review",
                payload=payload,
                provider=provider,
                model_settings=model_settings,
                output_model=response_model,
            )
            if cached is not None:
                resolved[index] = validate_boundary_review_v3(
                    cached,
                    transcript=transcript,
                    discovery=discovery,
                    config=semantic_config,
                )
                cache_hits[index] = True
                continue
            requests.append((index, discovery, payload, response_model, cache_key))

        def generate_one(
            request: tuple[
                int,
                DiscoveryOutput,
                dict[str, object],
                type[BoundaryReviewOutputV3],
                str,
            ],
        ) -> tuple[
            int,
            DiscoveryOutput,
            dict[str, object],
            type[BoundaryReviewOutputV3],
            str,
            StructuredCallResult[BoundaryReviewOutputV3],
        ]:
            index, discovery, payload, response_model, cache_key = request
            result = provider.generate(
                subject_id=f"{work.run_id}.boundary.{index:03d}",
                payload=payload,
                response_model=response_model,
                cancel_requested=cancel_requested,
            )
            return index, discovery, payload, response_model, cache_key, result

        failures: list[StructuredProviderError] = []
        call_records: list[ProviderCallRecord] = []
        with ThreadPoolExecutor(
            max_workers=min(
                semantic_config.window_discovery_concurrency,
                max(1, len(requests)),
            ),
            thread_name_prefix="semantic-boundary-review",
        ) as executor:
            pending = {executor.submit(generate_one, request): request for request in requests}
            for future in as_completed(pending):
                request = pending[future]
                index, discovery, payload, response_model, cache_key = request
                try:
                    _, _, _, _, _, result = future.result()
                except StructuredProviderError as exc:
                    self._state.record_provider_calls(fence, exc.call_records, cache_hit=False)
                    failures.append(exc)
                    call_records.extend(exc.call_records)
                    continue
                self._state.record_provider_calls(fence, result.call_records, cache_hit=False)
                call_records.extend(result.call_records)
                agent_outputs.append(
                    {
                        "discovery_output_index": index,
                        "phase": "initial_or_schema_repaired",
                        "repaired": result.repaired,
                        "repair_attempts": list(result.repair_attempts),
                        "output": result.output.model_dump(mode="json"),
                    }
                )
                try:
                    validated = validate_boundary_review_v3(
                        result.output,
                        transcript=transcript,
                        discovery=discovery,
                        config=semantic_config,
                    )
                except ValueError as exc:
                    validation_events.append(
                        {
                            "discovery_output_index": index,
                            "error": _semantic_error_detail(work, exc, legacy_limit=1_000),
                        }
                    )
                    if result.repaired:
                        failures.append(
                            StructuredProviderError(
                                "STRUCTURED_OUTPUT_INVALID",
                                (),
                                repair_attempts=result.repair_attempts,
                            )
                        )
                        continue
                    try:
                        repaired = provider.repair(
                            subject_id=f"{work.run_id}.boundary.{index:03d}",
                            payload=_semantic_repair_request(
                                work,
                                payload,
                                result.output,
                                validation_errors=(
                                    _semantic_error_detail(work, exc, legacy_limit=1_000),
                                ),
                            ),
                            response_model=response_model,
                            validation_errors=(
                                _semantic_error_detail(work, exc, legacy_limit=500),
                            ),
                            cancel_requested=cancel_requested,
                        )
                    except StructuredProviderError as repair_exc:
                        self._state.record_provider_calls(
                            fence,
                            repair_exc.call_records,
                            cache_hit=False,
                        )
                        failures.append(repair_exc)
                        call_records.extend(repair_exc.call_records)
                        continue
                    self._state.record_provider_calls(
                        fence,
                        repaired.call_records,
                        cache_hit=False,
                    )
                    call_records.extend(repaired.call_records)
                    agent_outputs.append(
                        {
                            "discovery_output_index": index,
                            "phase": "domain_repair",
                            "repaired": True,
                            "repair_attempts": list(repaired.repair_attempts),
                            "output": repaired.output.model_dump(mode="json"),
                        }
                    )
                    try:
                        validated = validate_boundary_review_v3(
                            repaired.output,
                            transcript=transcript,
                            discovery=discovery,
                            config=semantic_config,
                        )
                    except ValueError as repair_validation_error:
                        validation_events.append(
                            {
                                "discovery_output_index": index,
                                "error": _semantic_error_detail(
                                    work, repair_validation_error, legacy_limit=1_000
                                ),
                            }
                        )
                        failures.append(
                            StructuredProviderError(
                                "STRUCTURED_OUTPUT_INVALID",
                                (),
                                repair_attempts=repaired.repair_attempts,
                            )
                        )
                        continue
                write_semantic_stage_cache(
                    cache_dir=cache_dir,
                    cache_key=cache_key,
                    stage="boundary_review",
                    payload=payload,
                    provider=provider,
                    model_settings=model_settings,
                    output=validated,
                )
                resolved[index] = validated
                cache_hits[index] = False
        if failures:
            if getattr(work.config, "semantic_transport_contract", None) is not None:
                aggregate = _aggregate_semantic_failures(failures, tuple(call_records))
                raise StructuredProviderError(
                    aggregate.code,
                    aggregate.call_records,
                    repair_attempts=(
                        *aggregate.repair_attempts,
                        {
                            "phase": "stage_validation",
                            "agent_outputs": agent_outputs,
                            "validation_events": validation_events,
                        },
                    ),
                )
            raise failures[0]
        ordered_indices = [
            index for index, output in enumerate(discovery_outputs, start=1) if output.candidates
        ]
        if set(resolved) != set(ordered_indices):
            raise ValueError("Boundary Review did not resolve every candidate-bearing batch")
        outputs = tuple(resolved[index] for index in ordered_indices)
        return outputs, {
            "prompt": {
                "version": f"{prompt.version}.{prompt.stage}",
                "sha256": prompt.sha256,
                "loaded_files": list(prompt.loaded_files),
            },
            "batch_count": len(outputs),
            "candidate_count": sum(len(value.reviews) for value in outputs),
            "cache_hits": [cache_hits[index] for index in ordered_indices],
            "validation_events": validation_events,
            "agent_outputs": sorted(
                agent_outputs,
                key=lambda value: (
                    int(cast(int, value["discovery_output_index"])),
                    str(value["phase"]),
                ),
            ),
        }

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
            base_relative = _proxy_render_base_relative(work, item)
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
    identity_matches = cross_launch_source_stat_matches(
        pinned.path,
        metadata,
        expected_path=source.resolved_path,
        expected_size_bytes=source.size_bytes,
        expected_mtime_ns=source.mtime_ns,
        expected_inode=source.inode,
    )
    if not identity_matches or pinned.sha256(cancel_requested=cancel_requested) != source.sha256:
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
    if not cross_launch_source_stat_matches(
        pinned.path,
        metadata,
        expected_path=source.resolved_path,
        expected_size_bytes=source.size_bytes,
        expected_mtime_ns=source.mtime_ns,
        expected_inode=source.inode,
    ):
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


def _proxy_render_base_relative(work: StageWork, item: PersistedRevision) -> str:
    """Keep historical short paths stable while isolating mini-lesson output."""

    if work.config.clip_profile == ClipProfile.MINI_LESSON:
        relative_path = f"output/mini_lessons/{item.candidate_id}/r{item.revision.revision:03d}"
    else:
        relative_path = f"renders/proxies/{item.candidate_id}/r{item.revision.revision:03d}"
    return _generation_relative(work.generation, relative_path)


def _candidate_slots_from_v4(
    transcript: TranscriptDocument,
    candidates: tuple[ChainCandidateV4, ...],
    *,
    lineage: bool = False,
) -> tuple[tuple[CandidateClip, ...], dict[str, str]]:
    cues = transcript_cues(transcript)
    cue_map = {value.cue_id: value for value in cues}
    slots: list[CandidateClip] = []
    slot_map: dict[str, str] = {}
    for candidate in sorted(
        candidates,
        key=lambda value: (value.start_cue_id, value.end_cue_id, value.candidate_id),
    ):
        try:
            start = cue_map[candidate.start_cue_id]
            end = cue_map[candidate.end_cue_id]
        except KeyError as exc:
            raise ValueError("Topic Chain candidate references an unknown cue") from exc
        selected = tuple(
            value
            for value in cues
            if candidate.start_cue_id <= value.cue_id <= candidate.end_cue_id
        )
        if not selected:
            raise ValueError("Topic Chain candidate contains no transcript cues")
        text = "".join(value.original_text.strip() for value in selected)
        if not text or len(text) > 24_000:
            raise ValueError("Topic Chain candidate transcript is empty or too large")
        slot_id = candidate.candidate_id
        if len(slot_id) > 64:
            identity = hashlib.sha256(slot_id.encode()).hexdigest()[:24]
            slot_id = f"semantic_v{5 if lineage else 4}_{identity}"
        if slot_id in slot_map.values():
            raise ValueError("Topic Chain candidates map to a duplicate persistent slot")
        before_values = [
            value.original_text.strip()
            for value in cues
            if value.end_ms <= start.start_ms and value.end_ms > start.start_ms - 30_000
        ]
        after_values = [
            value.original_text.strip()
            for value in cues
            if value.start_ms >= end.end_ms and value.start_ms < end.end_ms + 30_000
        ]
        context_before = "".join(before_values)[-4_000:]
        context_after = "".join(after_values)[:4_000]
        slots.append(
            CandidateClip(
                candidate_id=slot_id,
                source_start_ms=start.start_ms,
                source_end_ms=end.end_ms,
                allowed_start_ms=max(0, start.start_ms - 30_000),
                allowed_end_ms=min(transcript.source_duration_ms, end.end_ms + 30_000),
                text=text,
                context_before=context_before,
                context_after=context_after,
                rule_score=0.0,
                reasons=(
                    "semantic_topic_chain_v2" if lineage else "semantic_topic_chain_v1",
                    f"profile:{candidate.clip_profile.value}",
                    f"topic_chain:{candidate.topic_chain_id}",
                ),
                segment_ids=tuple(value.segment_id for value in selected),
            )
        )
        slot_map[candidate.candidate_id] = slot_id
    return tuple(slots), slot_map


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


def _semantic_model_settings(
    work: StageWork,
    provider: StructuredLLMProvider,
) -> dict[str, object]:
    """Return non-secret model settings that materially affect structured output."""

    settings: dict[str, object] = {
        "llm_model": work.config.llm_model,
        "request_timeout_seconds": getattr(
            provider,
            "timeout_seconds",
            work.config.openai_request_timeout_seconds,
        ),
        "reasoning_effort": getattr(provider, "reasoning_effort", "provider_default"),
        "max_request_retries": work.config.openai_max_request_retries,
        "retry_base_seconds": work.config.openai_retry_base_seconds,
        "retry_max_seconds": work.config.openai_retry_max_seconds,
        "tokenizer_name": work.config.semantic_tokenizer_name,
        "model_context_tokens": work.config.semantic_model_context_tokens,
        "output_reserve_tokens": work.config.semantic_output_reserve_tokens,
        "safety_margin_tokens": work.config.semantic_safety_margin_tokens,
    }

    transport_contract = getattr(work.config, "semantic_transport_contract", None)
    if transport_contract is not None:
        settings["semantic_transport_contract"] = transport_contract
        settings["full_context_budget_ratio"] = work.config.semantic_full_context_budget_ratio
    execution_contract = getattr(work.config, "semantic_execution_contract", None)
    if execution_contract is not None:
        settings["semantic_execution_contract"] = execution_contract
    return settings


def _redact_semantic_failure_audit(value: object, sensitive_values: tuple[str, ...]) -> object:
    """Redact durable untrusted business JSON without truncating audit records."""

    def replace(item: object) -> object:
        if isinstance(item, str):
            # Indexed business parts are JSON text. Apply the same key-based
            # redaction inside them; retain original bytes when no redaction occurs.
            try:
                embedded = json.loads(item)
            except (ValueError, TypeError):
                embedded = None
            if isinstance(embedded, (dict, list)):
                redacted_embedded = replace(embedded)
                if redacted_embedded != embedded:
                    item = json.dumps(redacted_embedded, ensure_ascii=False)
            for secret in sorted(sensitive_values, key=len, reverse=True):
                item = item.replace(secret, "[REDACTED]")
            return redact_value(item)
        if isinstance(item, dict):
            result: dict[str, object] = {}
            for key, raw in item.items():
                name = str(key)
                if name in {"budget_tokens", "estimated_total_tokens"} and type(raw) is int:
                    safe: object = raw
                elif redact_value({name: None})[name] == "[REDACTED]" or any(
                    word in name.lower() for word in ("password", "secret", "credential")
                ):
                    safe = "[REDACTED]"
                else:
                    safe = replace(raw)
                result[str(replace(name))] = safe
            return result
        if isinstance(item, (list, tuple)):
            return [replace(raw) for raw in item]
        return item

    return replace(value)


def _aggregate_semantic_failures(
    failures: list[StructuredProviderError],
    call_records: tuple[ProviderCallRecord, ...],
) -> StructuredProviderError:
    """A concurrent timeout cannot make an unchanged overbudget stage retryable."""
    selected = next(
        (
            error
            for code in ("STRUCTURED_INPUT_BUDGET_EXCEEDED", "STRUCTURED_REPAIR_BUDGET_EXCEEDED")
            for error in failures
            if error.code == code
        ),
        failures[0],
    )
    attempts: list[dict[str, object]] = []
    for error in failures:
        attempts.append(
            {"failure_code": error.code, "call_ids": [r.call_id for r in error.call_records]}
        )
        attempts.extend(error.repair_attempts)
    unique_calls: dict[str, ProviderCallRecord] = {}
    for record in call_records:
        previous = unique_calls.get(record.call_id)
        if previous is not None and previous != record:
            raise ValueError("conflicting semantic provider call records")
        unique_calls[record.call_id] = record
    return StructuredProviderError(
        selected.code,
        tuple(unique_calls.values()),
        repair_attempts=tuple(attempts),
    )


def _semantic_error_detail(work: StageWork, error: ValueError, *, legacy_limit: int) -> str:
    detail = str(error)
    return (
        detail
        if getattr(work.config, "semantic_transport_contract", None)
        else detail[:legacy_limit]
    )


def _semantic_repair_request(
    work: StageWork,
    request_payload: dict[str, object],
    invalid_output: BaseModel,
    *,
    validation_errors: tuple[str, ...],
) -> dict[str, object]:
    if getattr(work.config, "semantic_transport_contract", None) is None:
        return semantic_repair_payload(
            request_payload,
            invalid_output,
            validation_errors=validation_errors,
        )
    # New wire budgets require the whole authority and error set before measurement.
    # Historical object repair builders retain their exact bounded representation.
    return {
        **_semantic_repair_payload_v4(
            request_payload,
            invalid_output,
            validation_errors=validation_errors,
        ),
        "schema_version": request_payload.get("schema_version"),
    }


def _semantic_repair_payload_v4(
    request_payload: dict[str, object],
    invalid_output: BaseModel,
    *,
    validation_errors: tuple[str, ...],
) -> dict[str, object]:
    """Repair one failed v4 item without rediscovering any other local task."""

    return {
        "schema_version": "4",
        "repair_only": True,
        "stage": request_payload.get("stage"),
        "source_hash": request_payload.get("source_hash"),
        "clip_profile": request_payload.get("clip_profile"),
        "validation_errors": list(validation_errors),
        "immutable_request": request_payload,
        "invalid_output": invalid_output.model_dump(mode="json"),
        "repair_constraints": (
            "Return only the corrected output for this exact local request. Preserve all valid "
            "IDs, semantic decisions, source cues, and unrelated fields. Do not rerun Discovery, "
            "another link, another chain, or another candidate."
        ),
    }


def _provider_usage_tokens(record: ProviderCallRecord, direction: str) -> int:
    usage = record.usage_json
    if not isinstance(usage, dict):
        return 0
    keys = (
        ("input_tokens", "prompt_tokens")
        if direction == "input"
        else ("output_tokens", "completion_tokens")
    )
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return 0


def _audit_request_count(semantic: dict[str, object], stage: str) -> int:
    audits = semantic.get("stage_audits")
    if not isinstance(audits, dict):
        return 0
    value = audits.get(stage)
    if not isinstance(value, dict):
        return 0
    count = value.get("request_count")
    return count if isinstance(count, int) and not isinstance(count, bool) else 0


def _audit_call_count(semantic: dict[str, object], stage: str) -> int:
    audits = semantic.get("stage_audits")
    if not isinstance(audits, dict):
        return 0
    value = audits.get(stage)
    if not isinstance(value, dict):
        return 0
    records = value.get("call_records")
    return len(records) if isinstance(records, list) else 0


def _link_audit_request_count(semantic: dict[str, object]) -> int:
    audits = semantic.get("stage_audits")
    if not isinstance(audits, dict):
        return 0
    rounds = audits.get("link_review_rounds")
    if not isinstance(rounds, list):
        return 0
    return sum(
        int(value.get("request_count", 0))
        for value in rounds
        if isinstance(value, dict) and isinstance(value.get("request_count", 0), int)
    )


def _link_audit_call_count(semantic: dict[str, object]) -> int:
    audits = semantic.get("stage_audits")
    if not isinstance(audits, dict):
        return 0
    rounds = audits.get("link_review_rounds")
    if not isinstance(rounds, list):
        return 0
    return sum(
        len(records)
        for value in rounds
        if isinstance(value, dict) and isinstance((records := value.get("call_records")), list)
    )


def _audit_repair_count(
    semantic: dict[str, object],
    *current_audits: dict[str, object],
) -> int:
    audits: list[dict[str, object]] = [*current_audits]
    stored = semantic.get("stage_audits")
    if isinstance(stored, dict):
        audits.extend(value for value in stored.values() if isinstance(value, dict))
        rounds = stored.get("link_review_rounds")
        if isinstance(rounds, list):
            audits.extend(value for value in rounds if isinstance(value, dict))
    return sum(
        1
        for audit in audits
        for value in cast(list[dict[str, object]], audit.get("agent_outputs", []))
        if value.get("phase") == "domain_repair"
    )


def _audit_cache_hit_count(
    semantic: dict[str, object],
    *current_audits: dict[str, object],
) -> int:
    audits: list[dict[str, object]] = [*current_audits]
    stored = semantic.get("stage_audits")
    if isinstance(stored, dict):
        audits.extend(value for value in stored.values() if isinstance(value, dict))
        rounds = stored.get("link_review_rounds")
        if isinstance(rounds, list):
            audits.extend(value for value in rounds if isinstance(value, dict))
    return sum(
        value
        for audit in audits
        if isinstance((value := audit.get("cache_hit_count", 0)), int)
        and not isinstance(value, bool)
    )


def _audit_metric_total(
    semantic: dict[str, object],
    *current_audits: dict[str, object],
    key: str,
) -> int:
    audits: list[dict[str, object]] = [*current_audits]
    stored = semantic.get("stage_audits")
    if isinstance(stored, dict):
        audits.extend(value for value in stored.values() if isinstance(value, dict))
        rounds = stored.get("link_review_rounds")
        if isinstance(rounds, list):
            audits.extend(value for value in rounds if isinstance(value, dict))
    return sum(
        value
        for audit in audits
        if isinstance((value := audit.get(key, 0)), int) and not isinstance(value, bool)
    )


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
            work.config.semantic_link_review_skill_version,
            work.config.semantic_link_review_skill_sha256,
        )
        if prompt.stage == "link_review"
        else (
            work.config.semantic_topic_chain_skill_version,
            work.config.semantic_topic_chain_skill_sha256,
        )
        if prompt.stage == "topic_chain"
        else (
            work.config.semantic_boundary_review_skill_version,
            work.config.semantic_boundary_review_skill_sha256,
        )
        if prompt.stage == "boundary_review"
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


def _validated_global_v3_payload(
    value: ValidatedCandidateReviewV3,
) -> dict[str, object]:
    return {
        "review": value.review.model_dump(mode="json"),
        "boundary_review": value.boundary_review.model_dump(mode="json"),
        "discovery_candidate": value.discovery_candidate.model_dump(mode="json"),
        "decision": value.decision.value,
        "publish_status": value.publish_status.value,
        "start_ms": value.start_ms,
        "end_ms": value.end_ms,
        "duration_ms": value.duration_ms,
        "final_score": value.final_score,
        "quality_flags": [item.value for item in value.quality_flags],
        "risk_flags": [item.model_dump(mode="json") for item in value.risk_flags],
        "validation_notes": list(value.validation_notes),
    }


def _retained_global_review_clips(
    value: ValidatedGlobalReview,
) -> tuple[ValidatedGlobalClip, ...]:
    """Materialize every kept clip; manual review is a gate, not a deletion."""

    return (*value.selected, *value.manual_review)


def _materialized_global_review_clips(
    value: ValidatedGlobalReview | ValidatedGlobalReviewV3,
) -> tuple[ValidatedGlobalClip | ValidatedCandidateReviewV3, ...]:
    """v3 automatic delivery excludes manual/blocked audit rows by contract."""

    if isinstance(value, ValidatedGlobalReviewV3):
        return value.selected
    return _retained_global_review_clips(value)


def _global_review_risk_flags(value: ValidatedGlobalClip) -> tuple[str, ...]:
    flags = [risk.type.value for risk in value.clip.risks]
    if value.decision == ReviewDecision.MANUAL_REVIEW:
        flags.insert(0, "manual_review")
    return tuple(dict.fromkeys(flags))


def _global_review_v3_risk_flags(
    value: ValidatedCandidateReviewV3,
) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.type.value for item in value.risk_flags))


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
