from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock
from typing import TypeVar, cast

from pydantic import BaseModel

from liveclip.clipping_skills.dual_profile_v1 import (
    load_dual_profile_prompt,
    load_dual_profile_variant_link_prompt,
)
from liveclip.config.settings import Settings
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.edit_plan import (
    CaptionTemplate,
    EditPlan,
    Effect,
    Layout,
    captions_to_srt,
)
from liveclip.domain.review import EditPlanRevision, RevisionOrigin
from liveclip.domain.transcript import TranscriptDocument
from liveclip.media.ingest import MediaIngestError, run_ffprobe
from liveclip.media.secure_files import (
    SecureFileError,
    SecureFileMissing,
    create_directory_exclusive_no_follow,
    ensure_directory_no_follow,
    hash_regular_file_no_follow,
    read_regular_text_no_follow,
    write_text_immutable_no_follow,
)
from liveclip.pipeline.dual_profile import (
    DUAL_PROFILE_ALGORITHM_VERSION,
    DUAL_PROFILE_ROUTING_POLICY_VERSION,
    AuditCandidatePair,
    AuditPairFallback,
    AuditPairRule,
    AuditPairRuleError,
    AuditPairViolation,
    BoundaryOpeningFallback,
    BoundaryOpeningInvariantError,
    BoundaryReviewItem,
    CrossProfileVariantLinkOutput,
    DiscoveryWindow,
    DualProfileFinalResult,
    DualProfileRunConfig,
    DualProfileRunManifest,
    FinalProfileCandidate,
    FinalProfileResult,
    GlobalReviewItem,
    ProfileBoundaryReviewOutput,
    ProfileDiscoveryOutput,
    ProfileGlobalAuditOutput,
    ProfileGlobalReviewOutput,
    ProfileManifestStats,
    RawProfileCandidate,
    StaleCacheResolution,
    apply_audit_pair_blocks,
    apply_boundary_opening_fallback,
    apply_cross_profile_variant_links,
    assemble_final_profile_result,
    assert_no_cross_profile_dedup,
    audit_candidate_pairs,
    discovery_persisted_flags,
    plan_audit_pair_fallback,
    plan_profile_discovery_windows,
    semantic_cache_key,
    validate_audit_pair_decisions,
    validate_boundary_review_output,
    validate_discovery_output,
)
from liveclip.pipeline.semantic_global import transcript_cues
from liveclip.pipeline.srt import load_srt_transcript
from liveclip.providers.llm.structured import (
    StructuredCallResult,
    StructuredLLMProvider,
    StructuredProviderError,
)
from liveclip.providers.telemetry import ProviderCallRecord
from liveclip.renderer.service import RenderTextMode, render_edit_plan_revision
from liveclip.services.captions import captions_for_clip
from liveclip.services.structured_editorial_provider import (
    StructuredEditorialProviderFactory,
    configured_structured_editorial_provider_factory,
)

OutputModel = TypeVar("OutputModel", bound=BaseModel)
DualProfileProviderFactory = StructuredEditorialProviderFactory


@dataclass(frozen=True, slots=True)
class _ResolvedCall:
    output: BaseModel
    records: tuple[ProviderCallRecord, ...]
    cache_hit: bool
    retry_count: int
    repair_count: int


def configured_dual_profile_provider_factory(
    settings: Settings,
) -> DualProfileProviderFactory:
    return configured_structured_editorial_provider_factory(settings)


def run_dual_profile_evaluation(
    *,
    transcript_path: Path,
    output_dir: Path,
    provider_factory: DualProfileProviderFactory,
    config: DualProfileRunConfig | None = None,
    cache_dir: Path | None = None,
    discovery_concurrency: int = 5,
    cancel_requested: Callable[[], bool] = lambda: False,
    refresh_stale_cache: bool = False,
) -> dict[str, object]:
    """Run independent short and mini semantic tracks over one transcript.

    ``refresh_stale_cache`` is off by default: a cached output that fails current
    validation then fails the run closed. When explicitly enabled, such an entry is
    repaired under a superseding key and recorded in the run manifest.
    """

    if not 1 <= discovery_concurrency <= 8:
        raise ValueError("Discovery concurrency must be between one and eight")
    started = time.monotonic()
    resolved = config or DualProfileRunConfig()
    transcript = load_srt_transcript(transcript_path)
    source_hash, _ = hash_regular_file_no_follow(transcript_path)
    create_directory_exclusive_no_follow(output_dir)
    if cache_dir is not None:
        ensure_directory_no_follow(cache_dir)
    calls: list[ProviderCallRecord] = []
    cache_hits = 0
    retry_count = 0
    repair_count = 0
    resolution_audit = _ResolutionAudit(refresh_stale_cache=refresh_stale_cache)
    prompt_files: dict[str, tuple[str, ...]] = {}
    prompt_hashes: dict[str, str] = {}
    stage_counts = {
        "discovery": 0,
        "boundary_review": 0,
        "global_review": 0,
        "variant_link": 0,
    }
    discoveries_by_profile: dict[ClipProfile, tuple[ProfileDiscoveryOutput, ...]] = {}
    boundaries_by_profile: dict[ClipProfile, ProfileBoundaryReviewOutput] = {}
    global_by_profile: dict[ClipProfile, ProfileGlobalReviewOutput] = {}
    results: dict[ClipProfile, FinalProfileResult] = {}
    model_name = ""
    provider_name = ""

    for profile in resolved.requested_profiles:
        if cancel_requested():
            raise RuntimeError("dual Profile evaluation was cancelled")
        discovery_prompt = load_dual_profile_prompt("discovery", profile)
        discovery_provider = provider_factory(discovery_prompt, "medium")
        provider_name = discovery_provider.provider_name
        model_name = discovery_provider.model_name
        prompt_files[f"{profile.value}.discovery"] = discovery_prompt.loaded_files
        prompt_hashes[f"{profile.value}.discovery"] = discovery_prompt.sha256
        windows = plan_profile_discovery_windows(transcript, profile)
        resolved_discoveries: dict[str, _ResolvedCall] = {}
        discovery_failed = Event()

        def validate_discovery_call(
            output_value: ProfileDiscoveryOutput,
            current_window: DiscoveryWindow,
        ) -> ProfileDiscoveryOutput:
            return validate_discovery_output(
                output_value,
                window=current_window,
                transcript=transcript,
            )

        def discover(
            window: DiscoveryWindow,
            current_provider: StructuredLLMProvider = discovery_provider,
            current_profile: ClipProfile = profile,
            failure_event: Event = discovery_failed,
        ) -> tuple[str, _ResolvedCall]:
            payload = _discovery_payload(source_hash, window)

            def validate_current(
                output_value: ProfileDiscoveryOutput,
            ) -> ProfileDiscoveryOutput:
                return validate_discovery_call(output_value, window)

            response = _resolve_call(
                resolution_audit=resolution_audit,
                stage="discovery",
                subject_id=window.window_id,
                payload=payload,
                response_model=ProfileDiscoveryOutput,
                provider=current_provider,
                profile=current_profile,
                source_hash=source_hash,
                window_start=window.context_start_ms,
                window_end=window.context_end_ms,
                cache_dir=cache_dir,
                validate=validate_current,
                cancel_requested=lambda: cancel_requested() or failure_event.is_set(),
            )
            return window.window_id, response

        with ThreadPoolExecutor(max_workers=discovery_concurrency) as executor:
            futures = {executor.submit(discover, window): window for window in windows}
            try:
                for future in as_completed(futures):
                    identity, response = future.result()
                    resolved_discoveries[identity] = response
            except BaseException:
                discovery_failed.set()
                for future in futures:
                    future.cancel()
                raise
        profile_discoveries = tuple(
            cast(ProfileDiscoveryOutput, resolved_discoveries[window.window_id].output)
            for window in windows
        )
        for response in resolved_discoveries.values():
            calls.extend(response.records)
            cache_hits += int(response.cache_hit)
            retry_count += response.retry_count
            repair_count += response.repair_count
            stage_counts["discovery"] += int(not response.cache_hit)
        base_discoveries = profile_discoveries
        base_by_window = {
            window.window_id: output
            for window, output in zip(windows, base_discoveries, strict=True)
        }
        audit_prompt = load_dual_profile_prompt("coverage_audit", profile)
        audit_provider = provider_factory(audit_prompt, "medium")
        prompt_files[f"{profile.value}.coverage_audit"] = audit_prompt.loaded_files
        prompt_hashes[f"{profile.value}.coverage_audit"] = audit_prompt.sha256
        audit_windows = tuple(
            window for window in windows if base_by_window[window.window_id].candidates
        )
        resolved_audits: dict[str, _ResolvedCall] = {}
        audit_failed = Event()

        def audit_discovery(
            window: DiscoveryWindow,
            current_provider: StructuredLLMProvider = audit_provider,
            current_profile: ClipProfile = profile,
            failure_event: Event = audit_failed,
            current_base: Mapping[str, ProfileDiscoveryOutput] = base_by_window,
        ) -> tuple[str, _ResolvedCall]:
            existing = current_base[window.window_id].candidates
            existing_ids = {value.candidate_id for value in existing}
            payload = {
                **_discovery_payload(source_hash, window),
                "discovery_pass": "coverage_audit",
                "existing_candidates": [value.model_dump(mode="json") for value in existing],
            }

            def validate_audit(output_value: ProfileDiscoveryOutput) -> ProfileDiscoveryOutput:
                validated = validate_discovery_output(
                    output_value,
                    window=window,
                    transcript=transcript,
                )
                if any(
                    not value.candidate_id.startswith("audit_")
                    or value.candidate_id in existing_ids
                    for value in validated.candidates
                ):
                    raise ValueError("Coverage Audit candidate ID is not new and audit-prefixed")
                return validated

            response = _resolve_call(
                resolution_audit=resolution_audit,
                stage="coverage_audit",
                subject_id=f"{window.window_id}.coverage",
                payload=payload,
                response_model=ProfileDiscoveryOutput,
                provider=current_provider,
                profile=current_profile,
                source_hash=source_hash,
                window_start=window.context_start_ms,
                window_end=window.context_end_ms,
                cache_dir=cache_dir,
                validate=validate_audit,
                cancel_requested=lambda: cancel_requested() or failure_event.is_set(),
            )
            return window.window_id, response

        with ThreadPoolExecutor(max_workers=discovery_concurrency) as executor:
            audit_futures = {
                executor.submit(audit_discovery, window): window for window in audit_windows
            }
            try:
                for audit_future in as_completed(audit_futures):
                    audit_identity, audit_response = audit_future.result()
                    resolved_audits[audit_identity] = audit_response
            except BaseException:
                audit_failed.set()
                for audit_future in audit_futures:
                    audit_future.cancel()
                raise
        audit_discoveries = tuple(
            cast(ProfileDiscoveryOutput, resolved_audits[window.window_id].output)
            for window in audit_windows
        )
        for response in resolved_audits.values():
            calls.extend(response.records)
            cache_hits += int(response.cache_hit)
            retry_count += response.retry_count
            repair_count += response.repair_count
            stage_counts["discovery"] += int(not response.cache_hit)
        audit_by_window = {
            window.window_id: output
            for window, output in zip(audit_windows, audit_discoveries, strict=True)
        }
        precision_discoveries: tuple[ProfileDiscoveryOutput, ...] = ()
        precision_by_window: dict[str, ProfileDiscoveryOutput] = {}
        confirmation_discoveries: tuple[ProfileDiscoveryOutput, ...] = ()
        confirmation_by_window: dict[str, ProfileDiscoveryOutput] = {}
        if profile == ClipProfile.MINI_LESSON:
            precision_prompt = load_dual_profile_prompt("precision_audit", profile)
            precision_provider = provider_factory(precision_prompt, "medium")
            prompt_files[f"{profile.value}.precision_audit"] = precision_prompt.loaded_files
            prompt_hashes[f"{profile.value}.precision_audit"] = precision_prompt.sha256
            precision_windows = tuple(
                window
                for window in windows
                if transcript.source_duration_ms - window.ownership_start_ms > 90_000
            )
            resolved_precision: dict[str, _ResolvedCall] = {}
            precision_failed = Event()

            def discover_precise_boundaries(
                window: DiscoveryWindow,
                current_provider: StructuredLLMProvider = precision_provider,
                current_profile: ClipProfile = profile,
                failure_event: Event = precision_failed,
                current_base: Mapping[str, ProfileDiscoveryOutput] = base_by_window,
                current_audit: Mapping[str, ProfileDiscoveryOutput] = audit_by_window,
            ) -> tuple[str, _ResolvedCall]:
                existing = (
                    *current_base[window.window_id].candidates,
                    *current_audit.get(
                        window.window_id,
                        ProfileDiscoveryOutput(profile=current_profile, window_id=window.window_id),
                    ).candidates,
                )
                existing_ids = {value.candidate_id for value in existing}
                payload = {
                    **_discovery_payload(source_hash, window),
                    "discovery_pass": "precision_audit",
                    "existing_candidates": [value.model_dump(mode="json") for value in existing],
                }

                def validate_precision(
                    output_value: ProfileDiscoveryOutput,
                ) -> ProfileDiscoveryOutput:
                    validated = validate_discovery_output(
                        output_value,
                        window=window,
                        transcript=transcript,
                    )
                    if any(
                        not value.candidate_id.startswith("precision_")
                        or value.candidate_id in existing_ids
                        for value in validated.candidates
                    ):
                        raise ValueError(
                            "Precision Audit candidate ID is not new and precision-prefixed"
                        )
                    return validated

                response = _resolve_call(
                    resolution_audit=resolution_audit,
                    stage="precision_audit",
                    subject_id=f"{window.window_id}.precision",
                    payload=payload,
                    response_model=ProfileDiscoveryOutput,
                    provider=current_provider,
                    profile=current_profile,
                    source_hash=source_hash,
                    window_start=window.context_start_ms,
                    window_end=window.context_end_ms,
                    cache_dir=cache_dir,
                    validate=validate_precision,
                    cancel_requested=lambda: cancel_requested() or failure_event.is_set(),
                )
                return window.window_id, response

            with ThreadPoolExecutor(max_workers=discovery_concurrency) as executor:
                precision_futures = {
                    executor.submit(discover_precise_boundaries, window): window
                    for window in precision_windows
                }
                try:
                    for precision_future in as_completed(precision_futures):
                        precision_identity, precision_response = precision_future.result()
                        resolved_precision[precision_identity] = precision_response
                except BaseException:
                    precision_failed.set()
                    for precision_future in precision_futures:
                        precision_future.cancel()
                    raise
            precision_discoveries = tuple(
                cast(ProfileDiscoveryOutput, resolved_precision[window.window_id].output)
                for window in precision_windows
            )
            for response in resolved_precision.values():
                calls.extend(response.records)
                cache_hits += int(response.cache_hit)
                retry_count += response.retry_count
                repair_count += response.repair_count
                stage_counts["discovery"] += int(not response.cache_hit)
            precision_by_window = {
                window.window_id: output
                for window, output in zip(precision_windows, precision_discoveries, strict=True)
            }
            confirmation_prompt = load_dual_profile_prompt("precision_confirmation", profile)
            confirmation_provider = provider_factory(confirmation_prompt, "medium")
            prompt_files[f"{profile.value}.precision_confirmation"] = (
                confirmation_prompt.loaded_files
            )
            prompt_hashes[f"{profile.value}.precision_confirmation"] = confirmation_prompt.sha256
            resolved_confirmations: dict[str, _ResolvedCall] = {}
            confirmation_failed = Event()

            def confirm_precise_boundaries(
                window: DiscoveryWindow,
                current_provider: StructuredLLMProvider = confirmation_provider,
                current_profile: ClipProfile = profile,
                failure_event: Event = confirmation_failed,
                current_base: Mapping[str, ProfileDiscoveryOutput] = base_by_window,
                current_audit: Mapping[str, ProfileDiscoveryOutput] = audit_by_window,
                current_precision: Mapping[str, ProfileDiscoveryOutput] = precision_by_window,
            ) -> tuple[str, _ResolvedCall]:
                existing = (
                    *current_base[window.window_id].candidates,
                    *current_audit.get(
                        window.window_id,
                        ProfileDiscoveryOutput(profile=current_profile, window_id=window.window_id),
                    ).candidates,
                    *current_precision.get(
                        window.window_id,
                        ProfileDiscoveryOutput(profile=current_profile, window_id=window.window_id),
                    ).candidates,
                )
                existing_ids = {value.candidate_id for value in existing}
                payload = {
                    **_discovery_payload(source_hash, window),
                    "discovery_pass": "precision_confirmation",
                    "existing_candidates": [value.model_dump(mode="json") for value in existing],
                }

                def validate_confirmation(
                    output_value: ProfileDiscoveryOutput,
                ) -> ProfileDiscoveryOutput:
                    validated = validate_discovery_output(
                        output_value,
                        window=window,
                        transcript=transcript,
                    )
                    if any(
                        not value.candidate_id.startswith("confirm_")
                        or value.candidate_id in existing_ids
                        for value in validated.candidates
                    ):
                        raise ValueError(
                            "Precision Confirmation candidate ID is not new and confirm-prefixed"
                        )
                    return validated

                response = _resolve_call(
                    resolution_audit=resolution_audit,
                    stage="precision_confirmation",
                    subject_id=f"{window.window_id}.confirmation",
                    payload=payload,
                    response_model=ProfileDiscoveryOutput,
                    provider=current_provider,
                    profile=current_profile,
                    source_hash=source_hash,
                    window_start=window.context_start_ms,
                    window_end=window.context_end_ms,
                    cache_dir=cache_dir,
                    validate=validate_confirmation,
                    cancel_requested=lambda: cancel_requested() or failure_event.is_set(),
                )
                return window.window_id, response

            with ThreadPoolExecutor(max_workers=discovery_concurrency) as executor:
                confirmation_futures = {
                    executor.submit(confirm_precise_boundaries, window): window
                    for window in precision_windows
                }
                try:
                    for confirmation_future in as_completed(confirmation_futures):
                        confirmation_identity, confirmation_response = confirmation_future.result()
                        resolved_confirmations[confirmation_identity] = confirmation_response
                except BaseException:
                    confirmation_failed.set()
                    for confirmation_future in confirmation_futures:
                        confirmation_future.cancel()
                    raise
            confirmation_discoveries = tuple(
                cast(ProfileDiscoveryOutput, resolved_confirmations[window.window_id].output)
                for window in precision_windows
            )
            for response in resolved_confirmations.values():
                calls.extend(response.records)
                cache_hits += int(response.cache_hit)
                retry_count += response.retry_count
                repair_count += response.repair_count
                stage_counts["discovery"] += int(not response.cache_hit)
            confirmation_by_window = {
                window.window_id: output
                for window, output in zip(precision_windows, confirmation_discoveries, strict=True)
            }
        risk_discoveries: tuple[ProfileDiscoveryOutput, ...] = ()
        if profile == ClipProfile.MINI_LESSON:
            risk_prompt = load_dual_profile_prompt("risk_discovery", profile)
            risk_provider = provider_factory(risk_prompt, "medium")
            prompt_files[f"{profile.value}.risk_discovery"] = risk_prompt.loaded_files
            prompt_hashes[f"{profile.value}.risk_discovery"] = risk_prompt.sha256
            resolved_risks: dict[str, _ResolvedCall] = {}
            risk_failed = Event()
            risk_windows = tuple(
                window
                for window in windows
                if transcript.source_duration_ms - window.ownership_start_ms > 90_000
            )

            def discover_risks(
                window: DiscoveryWindow,
                current_provider: StructuredLLMProvider = risk_provider,
                current_profile: ClipProfile = profile,
                failure_event: Event = risk_failed,
                current_base: Mapping[str, ProfileDiscoveryOutput] = base_by_window,
                current_audit: Mapping[str, ProfileDiscoveryOutput] = audit_by_window,
                current_precision: Mapping[str, ProfileDiscoveryOutput] = precision_by_window,
                current_confirmation: Mapping[str, ProfileDiscoveryOutput] = confirmation_by_window,
            ) -> tuple[str, _ResolvedCall]:
                existing = (
                    *current_base[window.window_id].candidates,
                    *current_audit.get(
                        window.window_id,
                        ProfileDiscoveryOutput(profile=current_profile, window_id=window.window_id),
                    ).candidates,
                    *current_precision.get(
                        window.window_id,
                        ProfileDiscoveryOutput(profile=current_profile, window_id=window.window_id),
                    ).candidates,
                    *current_confirmation.get(
                        window.window_id,
                        ProfileDiscoveryOutput(profile=current_profile, window_id=window.window_id),
                    ).candidates,
                )
                existing_ids = {value.candidate_id for value in existing}
                payload = {
                    **_discovery_payload(source_hash, window),
                    "discovery_pass": "risk_discovery",
                }

                def validate_risks(
                    output_value: ProfileDiscoveryOutput,
                ) -> ProfileDiscoveryOutput:
                    validated = validate_discovery_output(
                        output_value,
                        window=window,
                        transcript=transcript,
                    )
                    if any(
                        not value.candidate_id.startswith("risk_")
                        or value.candidate_id in existing_ids
                        or not value.risk_tags
                        for value in validated.candidates
                    ):
                        raise ValueError(
                            "Risk Discovery candidate is not new, risk-tagged and risk-prefixed"
                        )
                    return validated

                response = _resolve_call(
                    resolution_audit=resolution_audit,
                    stage="risk_discovery",
                    subject_id=f"{window.window_id}.risk",
                    payload=payload,
                    response_model=ProfileDiscoveryOutput,
                    provider=current_provider,
                    profile=current_profile,
                    source_hash=source_hash,
                    window_start=window.context_start_ms,
                    window_end=window.context_end_ms,
                    cache_dir=cache_dir,
                    validate=validate_risks,
                    cancel_requested=lambda: cancel_requested() or failure_event.is_set(),
                )
                return window.window_id, response

            with ThreadPoolExecutor(max_workers=discovery_concurrency) as executor:
                risk_futures = {
                    executor.submit(discover_risks, window): window for window in risk_windows
                }
                try:
                    for risk_future in as_completed(risk_futures):
                        risk_identity, risk_response = risk_future.result()
                        resolved_risks[risk_identity] = risk_response
                except BaseException:
                    risk_failed.set()
                    for risk_future in risk_futures:
                        risk_future.cancel()
                    raise
            risk_discoveries = tuple(
                cast(ProfileDiscoveryOutput, resolved_risks[window.window_id].output)
                for window in risk_windows
            )
            for response in resolved_risks.values():
                calls.extend(response.records)
                cache_hits += int(response.cache_hit)
                retry_count += response.retry_count
                repair_count += response.repair_count
                stage_counts["discovery"] += int(not response.cache_hit)
        profile_discoveries = (
            *base_discoveries,
            *audit_discoveries,
            *precision_discoveries,
            *confirmation_discoveries,
            *risk_discoveries,
        )
        # Structural risk-pass membership: taken from the dedicated risk-discovery
        # pass outputs, never inferred from candidate-ID prefixes.
        risk_record_ids = frozenset(
            candidate.candidate_id for output in risk_discoveries for candidate in output.candidates
        )
        # Structural provenance shown to review stages, keyed by the pass that
        # produced each candidate (never inferred from ID prefixes).
        discovery_pass_by_id = {
            candidate.candidate_id: pass_name
            for pass_name, outputs in (
                ("base", base_discoveries),
                ("coverage_audit", audit_discoveries),
                ("precision_audit", precision_discoveries),
                ("precision_confirmation", confirmation_discoveries),
                ("risk_discovery", risk_discoveries),
            )
            for output in outputs
            for candidate in output.candidates
        }
        all_candidate_ids = [
            candidate.candidate_id
            for output in profile_discoveries
            for candidate in output.candidates
        ]
        if len(all_candidate_ids) != len(set(all_candidate_ids)):
            raise ValueError("Profile Discovery candidate IDs are not globally unique")
        discoveries_by_profile[profile] = profile_discoveries
        _write_json(
            output_dir
            / (
                "discovery-short.json"
                if profile == ClipProfile.SHORT_HIGHLIGHT
                else "discovery-long.json"
            ),
            {
                "schema_version": "1",
                "profile": profile.value,
                "windows": [value.model_dump(mode="json") for value in windows],
                "base_output_count": len(base_discoveries),
                "coverage_audit_output_count": len(audit_discoveries),
                "precision_audit_output_count": len(precision_discoveries),
                "precision_confirmation_output_count": len(confirmation_discoveries),
                "risk_discovery_output_count": len(risk_discoveries),
                "outputs": [value.model_dump(mode="json") for value in profile_discoveries],
            },
        )

        raw_candidates = tuple(
            candidate for output in profile_discoveries for candidate in output.candidates
        )
        boundary_prompt = load_dual_profile_prompt("boundary_review", profile)
        boundary_provider = provider_factory(boundary_prompt, "high")
        prompt_files[f"{profile.value}.boundary_review"] = boundary_prompt.loaded_files
        prompt_hashes[f"{profile.value}.boundary_review"] = boundary_prompt.sha256
        boundary_reviews: list[BoundaryReviewItem] = []
        # Keep each structured boundary response small enough for local CLI providers.
        # Long-profile audits can yield more than one hundred candidates; batches of
        # eight repeatedly exhausted the provider timeout during real cold runs.
        candidate_chunks = _chunks(raw_candidates, size=4)
        boundary_calls: dict[int, _ResolvedCall] = {}
        boundary_failed = Event()

        def review_boundary_chunk(
            chunk_index: int,
            candidate_chunk: tuple[RawProfileCandidate, ...],
            current_profile: ClipProfile = profile,
            current_provider: StructuredLLMProvider = boundary_provider,
            failure_event: Event = boundary_failed,
            current_passes: Mapping[str, str] = discovery_pass_by_id,
            current_risk_ids: frozenset[str] = risk_record_ids,
        ) -> tuple[int, _ResolvedCall]:
            boundary_payload = _boundary_payload(
                current_profile, candidate_chunk, transcript, current_passes
            )

            def validate_boundary_call(
                output_value: ProfileBoundaryReviewOutput,
            ) -> ProfileBoundaryReviewOutput:
                return validate_boundary_review_output(
                    output_value,
                    profile=current_profile,
                    candidates=candidate_chunk,
                    transcript=transcript,
                    risk_record_ids=current_risk_ids,
                )

            boundary_subject = f"{current_profile.value}.boundary.{chunk_index:03d}"
            response = _resolve_call(
                resolution_audit=resolution_audit,
                stage="boundary_review",
                subject_id=boundary_subject,
                payload=boundary_payload,
                response_model=ProfileBoundaryReviewOutput,
                provider=current_provider,
                profile=current_profile,
                source_hash=source_hash,
                window_start=0,
                window_end=transcript.source_duration_ms,
                cache_dir=cache_dir,
                validate=validate_boundary_call,
                cancel_requested=lambda: cancel_requested() or failure_event.is_set(),
                conservative_fallback=_boundary_opening_fallback(
                    current_profile, boundary_subject, validate_boundary_call
                ),
            )
            return chunk_index, response

        with ThreadPoolExecutor(max_workers=min(discovery_concurrency, 3)) as executor:
            boundary_futures = {
                executor.submit(review_boundary_chunk, index, candidate_chunk): index
                for index, candidate_chunk in enumerate(candidate_chunks, start=1)
            }
            try:
                for boundary_future in as_completed(boundary_futures):
                    boundary_index, boundary_response = boundary_future.result()
                    boundary_calls[boundary_index] = boundary_response
            except BaseException:
                boundary_failed.set()
                for boundary_future in boundary_futures:
                    boundary_future.cancel()
                raise
        for boundary_index in sorted(boundary_calls):
            boundary_call = boundary_calls[boundary_index]
            boundary_chunk = cast(ProfileBoundaryReviewOutput, boundary_call.output)
            boundary_reviews.extend(boundary_chunk.reviews)
            calls.extend(boundary_call.records)
            cache_hits += int(boundary_call.cache_hit)
            retry_count += boundary_call.retry_count
            repair_count += boundary_call.repair_count
            stage_counts["boundary_review"] += int(not boundary_call.cache_hit)
        boundary = validate_boundary_review_output(
            ProfileBoundaryReviewOutput(profile=profile, reviews=tuple(boundary_reviews)),
            profile=profile,
            candidates=raw_candidates,
            transcript=transcript,
            risk_record_ids=risk_record_ids,
        )
        boundaries_by_profile[profile] = boundary

        global_prompt = load_dual_profile_prompt("global_review", profile)
        global_provider = provider_factory(global_prompt, "high")
        prompt_files[f"{profile.value}.global_review"] = global_prompt.loaded_files
        prompt_hashes[f"{profile.value}.global_review"] = global_prompt.sha256

        def validate_global(
            value: ProfileGlobalReviewOutput,
            current_profile: ClipProfile = profile,
            current_discoveries: tuple[ProfileDiscoveryOutput, ...] = profile_discoveries,
            current_boundary: ProfileBoundaryReviewOutput = boundary,
            current_risk_ids: frozenset[str] = risk_record_ids,
        ) -> ProfileGlobalReviewOutput:
            review = value
            assemble_final_profile_result(
                profile=current_profile,
                discoveries=current_discoveries,
                boundaries=current_boundary,
                global_review=review,
                transcript=transcript,
                top_n=resolved.top_n[current_profile],
                score_threshold_exclusive=resolved.score_threshold_exclusive,
                risk_record_ids=current_risk_ids,
            )
            return review

        # Bound per-call structured output. The full-pool audit below still sees
        # every candidate and owns cross-partition semantic deduplication.
        # Keep structured review responses small enough for reliable schema adherence on
        # real providers. A failed 16-candidate response discards the whole partition;
        # twelve retains useful concurrency while materially reducing repair failures.
        global_chunks = _chunks(raw_candidates, size=12)
        global_calls: dict[int, _ResolvedCall] = {}
        global_failed = Event()

        def review_global_chunk(
            chunk_index: int,
            candidate_chunk: tuple[RawProfileCandidate, ...],
            current_profile: ClipProfile = profile,
            current_provider: StructuredLLMProvider = global_provider,
            failure_event: Event = global_failed,
            current_discoveries: tuple[ProfileDiscoveryOutput, ...] = profile_discoveries,
            current_boundary: ProfileBoundaryReviewOutput = boundary,
            partition_count: int = len(global_chunks),
            current_risk_ids: frozenset[str] = risk_record_ids,
            current_passes: Mapping[str, str] = discovery_pass_by_id,
        ) -> tuple[int, _ResolvedCall]:
            candidate_ids = {candidate.candidate_id for candidate in candidate_chunk}
            chunk_discoveries = tuple(
                output.model_copy(
                    update={
                        "candidates": tuple(
                            candidate
                            for candidate in output.candidates
                            if candidate.candidate_id in candidate_ids
                        )
                    }
                )
                for output in current_discoveries
                if any(candidate.candidate_id in candidate_ids for candidate in output.candidates)
            )
            chunk_boundary = ProfileBoundaryReviewOutput(
                profile=current_profile,
                reviews=tuple(
                    item for item in current_boundary.reviews if item.candidate_id in candidate_ids
                ),
            )
            chunk_payload = {
                **_global_payload(
                    current_profile,
                    candidate_chunk,
                    chunk_boundary,
                    transcript,
                    current_passes,
                ),
                "review_partition": {
                    "index": chunk_index,
                    "count": partition_count,
                    "cross_partition_dedup_deferred_to_global_audit": True,
                },
            }

            def validate_global_chunk(
                review_value: ProfileGlobalReviewOutput,
            ) -> ProfileGlobalReviewOutput:
                assemble_final_profile_result(
                    profile=current_profile,
                    discoveries=chunk_discoveries,
                    boundaries=chunk_boundary,
                    global_review=review_value,
                    transcript=transcript,
                    top_n=resolved.top_n[current_profile],
                    score_threshold_exclusive=resolved.score_threshold_exclusive,
                    risk_record_ids=current_risk_ids,
                )
                return review_value

            response = _resolve_call(
                resolution_audit=resolution_audit,
                stage="global_review",
                subject_id=f"{current_profile.value}.global.{chunk_index:03d}",
                payload=chunk_payload,
                response_model=ProfileGlobalReviewOutput,
                provider=current_provider,
                profile=current_profile,
                source_hash=source_hash,
                window_start=0,
                window_end=transcript.source_duration_ms,
                cache_dir=cache_dir,
                validate=validate_global_chunk,
                cancel_requested=lambda: cancel_requested() or failure_event.is_set(),
            )
            return chunk_index, response

        with ThreadPoolExecutor(max_workers=min(discovery_concurrency, 3)) as executor:
            global_futures = {
                executor.submit(review_global_chunk, index, candidate_chunk): index
                for index, candidate_chunk in enumerate(global_chunks, start=1)
            }
            try:
                for global_future in as_completed(global_futures):
                    global_index, global_response = global_future.result()
                    global_calls[global_index] = global_response
            except BaseException:
                global_failed.set()
                for global_future in global_futures:
                    global_future.cancel()
                raise
        global_review_items: list[GlobalReviewItem] = []
        for global_index in sorted(global_calls):
            global_call = global_calls[global_index]
            global_chunk = cast(ProfileGlobalReviewOutput, global_call.output)
            global_review_items.extend(global_chunk.reviews)
            calls.extend(global_call.records)
            cache_hits += int(global_call.cache_hit)
            retry_count += global_call.retry_count
            repair_count += global_call.repair_count
            stage_counts["global_review"] += int(not global_call.cache_hit)
        review_map = {item.candidate_id: item for item in global_review_items}
        if len(review_map) != len(global_review_items):
            raise ValueError("partitioned Global Review repeated a candidate")
        global_review = ProfileGlobalReviewOutput(
            profile=profile,
            reviews=tuple(review_map[candidate.candidate_id] for candidate in raw_candidates),
        )
        validate_global(global_review)
        global_payload = _global_payload(
            profile, raw_candidates, boundary, transcript, discovery_pass_by_id
        )
        global_audit_prompt = load_dual_profile_prompt("global_audit", profile)
        global_audit_provider = provider_factory(global_audit_prompt, "high")
        prompt_files[f"{profile.value}.global_audit"] = global_audit_prompt.loaded_files
        prompt_hashes[f"{profile.value}.global_audit"] = global_audit_prompt.sha256
        initial_review_map = {value.candidate_id: value for value in global_review.reviews}
        audit_pairs = audit_candidate_pairs(global_review, transcript)
        # Stage 13b: the Discovery gated flags that WILL persist into final routing
        # (no Boundary Review shrink), computed by the same function the routing
        # uses, so the audit's view and the final routing cannot drift.
        boundary_by_id = {value.candidate_id: value for value in boundary.reviews}
        persisted_by_id = {
            candidate.candidate_id: discovery_persisted_flags(
                candidate, boundary_by_id[candidate.candidate_id]
            )
            for candidate in raw_candidates
        }
        persisted_flag_ids = frozenset(key for key, flags in persisted_by_id.items() if flags)

        def validate_global_audit(
            value: ProfileGlobalAuditOutput,
            current_profile: ClipProfile = profile,
            current_initial_ids: frozenset[str] = frozenset(initial_review_map),
            current_global: ProfileGlobalReviewOutput = global_review,
            current_pairs: tuple[AuditCandidatePair, ...] = audit_pairs,
            current_persisted: frozenset[str] = persisted_flag_ids,
        ) -> ProfileGlobalAuditOutput:
            if value.profile != current_profile:
                raise ValueError("Global Audit used the wrong Profile")
            replacement_map = {item.candidate_id: item for item in value.replacements}
            if len(replacement_map) != len(value.replacements):
                raise ValueError("Global Audit replacement candidate IDs are not unique")
            if not set(replacement_map) <= current_initial_ids:
                raise ValueError("Global Audit references an unknown candidate")
            merged = _merge_audit(value, current_global)
            validate_global(merged)
            # Pairs that the audit's own replacements create (for example by
            # promoting a candidate) must be decided as well. Cache hits are
            # re-validated with this same rule: every cached audit under the
            # current audit prompt hash was written and validated under it, and
            # audits cached before the rule carry an older prompt hash, so they
            # can never be cache hits.
            # Nested and overlap pairs alike (Stage 13).
            listed = {pair.members for pair in current_pairs}
            required_pairs = (
                *current_pairs,
                *(
                    pair
                    for pair in audit_candidate_pairs(merged, transcript)
                    if pair.members not in listed
                ),
            )
            # The deterministic pair rules raise AuditPairRuleError, and only after
            # every other check passed, so the audit fallback can tell them apart.
            validate_audit_pair_decisions(
                required_pairs,
                value.nested_pair_decisions,
                merged,
                persisted_flag_ids=current_persisted,
            )
            return value

        def audit_pair_fallback(
            value: ProfileGlobalAuditOutput,
            error: ValueError,
            current_profile: ClipProfile = profile,
            current_global: ProfileGlobalReviewOutput = global_review,
            current_validate: Callable[
                [ProfileGlobalAuditOutput], ProfileGlobalAuditOutput
            ] = validate_global_audit,
            current_persisted: frozenset[str] = persisted_flag_ids,
        ) -> tuple[ProfileGlobalAuditOutput, tuple[str, ...], tuple[BaseModel, ...]] | None:
            return _audit_pair_fallback(
                value,
                error,
                current_profile,
                current_global,
                current_validate,
                transcript,
                current_persisted,
            )

        global_audit_call = _resolve_call(
            resolution_audit=resolution_audit,
            stage="global_audit",
            subject_id=f"{profile.value}.global_audit",
            payload={
                **global_payload,
                # Audit payload only: the Global Review payloads stay unchanged.
                "candidates": [
                    {
                        **entry,
                        "persisted_discovery_gated_flags": [
                            flag.value
                            for flag in persisted_by_id[
                                cast(dict[str, str], entry["candidate"])["candidate_id"]
                            ]
                        ],
                    }
                    for entry in cast(list[dict[str, object]], global_payload["candidates"])
                ],
                "initial_global_review": global_review.model_dump(mode="json"),
                "audit_pairs": [pair.model_dump(mode="json") for pair in audit_pairs],
            },
            response_model=ProfileGlobalAuditOutput,
            provider=global_audit_provider,
            profile=profile,
            source_hash=source_hash,
            window_start=0,
            window_end=transcript.source_duration_ms,
            cache_dir=cache_dir,
            validate=validate_global_audit,
            cancel_requested=cancel_requested,
            conservative_fallback=audit_pair_fallback,
        )
        global_audit = cast(ProfileGlobalAuditOutput, global_audit_call.output)
        replacement_map = {item.candidate_id: item for item in global_audit.replacements}
        global_review = ProfileGlobalReviewOutput(
            profile=profile,
            reviews=tuple(
                replacement_map.get(item.candidate_id, item) for item in global_review.reviews
            ),
        )
        calls.extend(global_audit_call.records)
        cache_hits += int(global_audit_call.cache_hit)
        retry_count += global_audit_call.retry_count
        repair_count += global_audit_call.repair_count
        stage_counts["global_review"] += int(not global_audit_call.cache_hit)
        global_by_profile[profile] = global_review
        results[profile] = assemble_final_profile_result(
            profile=profile,
            discoveries=profile_discoveries,
            boundaries=boundary,
            global_review=global_review,
            transcript=transcript,
            top_n=resolved.top_n[profile],
            score_threshold_exclusive=resolved.score_threshold_exclusive,
            risk_record_ids=risk_record_ids,
        )

    assert_no_cross_profile_dedup(results.values())
    variant_prompt = load_dual_profile_variant_link_prompt()
    variant_provider = provider_factory(variant_prompt, "high")
    prompt_files["cross_profile.variant_link"] = variant_prompt.loaded_files
    prompt_hashes["cross_profile.variant_link"] = variant_prompt.sha256
    variant_candidates = tuple(
        value
        for profile in resolved.requested_profiles
        for values in (results[profile].selected, results[profile].manual_review)
        for value in values
    )
    variant_payload: dict[str, object] = {
        "schema_version": "1",
        "algorithm_version": DUAL_PROFILE_ALGORITHM_VERSION,
        "profile": "cross_profile",
        "candidates": [
            {
                "candidate_id": value.candidate_id,
                "profile": value.profile.value,
                "current_variant_group_id": value.variant_group_id,
                "start_cue_id": value.start_cue_id,
                "end_cue_id": value.end_cue_id,
                "title": value.title,
                "summary": value.summary,
                "evidence_cue_ids": value.evidence_cue_ids,
            }
            for value in variant_candidates
        ],
    }

    def validate_variant_links(
        value: CrossProfileVariantLinkOutput,
    ) -> CrossProfileVariantLinkOutput:
        apply_cross_profile_variant_links(results, value)
        return value

    variant_call = _resolve_call(
        resolution_audit=resolution_audit,
        stage="variant_link",
        subject_id="cross_profile.variant_link",
        payload=variant_payload,
        response_model=CrossProfileVariantLinkOutput,
        provider=variant_provider,
        profile="cross_profile",
        source_hash=source_hash,
        window_start=0,
        window_end=transcript.source_duration_ms,
        cache_dir=cache_dir,
        validate=validate_variant_links,
        cancel_requested=cancel_requested,
    )
    results = apply_cross_profile_variant_links(
        results,
        cast(CrossProfileVariantLinkOutput, variant_call.output),
    )
    calls.extend(variant_call.records)
    cache_hits += int(variant_call.cache_hit)
    retry_count += variant_call.retry_count
    repair_count += variant_call.repair_count
    stage_counts["variant_link"] += int(not variant_call.cache_hit)
    final = DualProfileFinalResult(
        source_hash=source_hash,
        requested_profiles=resolved.requested_profiles,
        executed_profiles=tuple(results),
        profiles=results,
        routing_policy_version=DUAL_PROFILE_ROUTING_POLICY_VERSION,
    )
    elapsed_ms = round((time.monotonic() - started) * 1_000)
    stale_resolutions = resolution_audit.stale_resolutions()
    manifest = DualProfileRunManifest(
        source_hash=source_hash,
        requested_profiles=resolved.requested_profiles,
        executed_profiles=tuple(results),
        profiles={
            profile: ProfileManifestStats(**value.statistics.model_dump())
            for profile, value in results.items()
        },
        provider=provider_name,
        model=model_name,
        prompt_files=prompt_files,
        prompt_hashes=prompt_hashes,
        calls=stage_counts,
        input_tokens=_usage_total(calls, "input_tokens"),
        output_tokens=_usage_total(calls, "output_tokens"),
        latency_ms=sum(value.latency_ms for value in calls) or elapsed_ms,
        cache_hits=cache_hits,
        retry_count=retry_count,
        repair_count=repair_count,
        stale_cache_refresh_enabled=refresh_stale_cache,
        stale_cache_resolution_count=len(stale_resolutions),
        stale_cache_resolutions=stale_resolutions,
        boundary_opening_fallbacks=resolution_audit.opening_fallbacks(),
        audit_pair_fallbacks=resolution_audit.audit_fallbacks(),
    )
    manifest.validate_against(final, boundaries=boundaries_by_profile)
    _write_json(
        output_dir / "boundary-review.json",
        {
            "schema_version": "1",
            "profiles": {
                key.value: value.model_dump(mode="json")
                for key, value in boundaries_by_profile.items()
            },
        },
    )
    _write_json(
        output_dir / "global-review.json",
        {
            "schema_version": "1",
            "profiles": {
                key.value: value.model_dump(mode="json") for key, value in global_by_profile.items()
            },
        },
    )
    _write_json(output_dir / "final-validated.json", final.model_dump(mode="json"))
    _write_json(output_dir / "run-manifest.json", manifest.model_dump(mode="json"))
    _write_json(
        output_dir / "provider-calls.json",
        {
            "schema_version": "1",
            "algorithm_version": DUAL_PROFILE_ALGORITHM_VERSION,
            "calls": [_call_metadata(value) for value in calls],
        },
    )
    return {
        "final": final.model_dump(mode="json"),
        "manifest": manifest.model_dump(mode="json"),
        "output_dir": str(output_dir),
    }


def render_dual_profile_candidates(
    *,
    source_video: Path,
    transcript_path: Path,
    final_result_path: Path,
    output_dir: Path,
    width: int = 1_080,
    height: int = 1_920,
    encoder: str = "auto",
    candidate_ids: Collection[str] | None = None,
    cancel_requested: Callable[[], bool] = lambda: False,
) -> dict[str, object]:
    """Render selected/manual candidates, optionally restricted to an explicit audited subset."""

    if not source_video.is_absolute() or ".." in source_video.parts:
        raise ValueError("source video must be an absolute path without parent traversal")
    resolved_source = source_video.resolve(strict=True)
    if not resolved_source.is_file():
        raise ValueError("source video must be a regular file")
    if width <= 0 or height <= width or width % 2 or height % 2:
        raise ValueError("render dimensions must be even portrait values")
    final = DualProfileFinalResult.model_validate_json(
        read_regular_text_no_follow(final_result_path, max_bytes=128 * 1024 * 1024)
    )
    transcript = load_srt_transcript(transcript_path)
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("render output directory already exists")
    create_directory_exclusive_no_follow(output_dir)
    stream_payload = _source_streams(resolved_source)
    initial_stat = resolved_source.stat()
    candidate_filter = frozenset(candidate_ids) if candidate_ids is not None else None
    eligible_ids = {
        candidate.candidate_id
        for profile in final.executed_profiles
        for candidate in (
            *final.profiles[profile].selected,
            *final.profiles[profile].manual_review,
        )
    }
    if candidate_filter is not None:
        missing = sorted(candidate_filter - eligible_ids)
        if missing:
            raise ValueError(
                "render candidate IDs are not selected/manual final candidates: "
                + ", ".join(missing)
            )
    manifest_clips: list[dict[str, object]] = []
    for profile in final.executed_profiles:
        value = final.profiles[profile]
        candidates = (*value.selected, *value.manual_review)
        if candidate_filter is not None:
            candidates = tuple(
                candidate for candidate in candidates if candidate.candidate_id in candidate_filter
            )
        profile_dir = output_dir / profile.value
        ensure_directory_no_follow(profile_dir)
        for candidate in candidates:
            if cancel_requested():
                raise RuntimeError("dual Profile rendering was cancelled")
            clip_id = _render_clip_id(candidate.candidate_id)
            captions = captions_for_clip(
                transcript.segments,
                source_start_ms=candidate.start_ms,
                source_end_ms=candidate.end_ms,
            )
            plan = EditPlan(
                candidate_id=clip_id,
                source_start_ms=candidate.start_ms,
                source_end_ms=candidate.end_ms,
                score=candidate.score,
                # Model prose (title/hook/review_reason) stays in the final JSON and
                # review package; the guarded EditPlan text is product-generated.
                title=f"Dual-profile {profile.value}",
                hook=f"Dual-profile {candidate.review_status.value} candidate",
                reason=_dual_profile_render_reason(profile, candidate),
                layout=Layout.CENTER_CROP,
                caption_template=CaptionTemplate.CLEAN_ZH_V1,
                effect=Effect.NONE,
                risk_flags=tuple(value.value for value in candidate.risk_tags[:8]),
                prompt_version="dual_profile_v1.global_review",
                model="dual-profile",
                degraded=False,
            )
            revision = EditPlanRevision(
                clip_id=clip_id,
                revision=1,
                origin=RevisionOrigin.AI,
                plan=plan,
                captions=captions,
                created_at=datetime.now(UTC),
            )
            video_path = profile_dir / f"{clip_id}.mp4"
            rendered = render_edit_plan_revision(
                source_path=resolved_source,
                revision=revision,
                output_path=video_path,
                width=width,
                height=height,
                encoder=encoder,
                text_mode=RenderTextMode.NONE,
                video_stream_index=stream_payload["video_stream_index"],
                audio_stream_index=stream_payload["audio_stream_index"],
                cancel_requested=cancel_requested,
            )
            subtitle_path = profile_dir / f"{clip_id}.srt"
            write_text_immutable_no_follow(
                subtitle_path,
                captions_to_srt(captions),
                max_bytes=2 * 1024 * 1024,
            )
            subtitle_hash, _ = hash_regular_file_no_follow(subtitle_path)
            manifest_clips.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "profile": profile.value,
                    "variant_group_id": candidate.variant_group_id,
                    "review_status": candidate.review_status.value,
                    "start_ms": candidate.start_ms,
                    "end_ms": candidate.end_ms,
                    "duration_ms": candidate.duration_ms,
                    "video_path": str(video_path),
                    "video_sha256": rendered.sha256,
                    "subtitle_path": str(subtitle_path),
                    "subtitle_sha256": subtitle_hash,
                    "quality_report_path": str(rendered.quality_report_path),
                    "contact_sheet_path": str(rendered.contact_sheet_path),
                    "contact_sheet_sha256": rendered.contact_sheet_sha256,
                    "encoder": rendered.encoder,
                    "render_attempts": rendered.attempts,
                }
            )
    final_stat = resolved_source.stat()
    if (
        initial_stat.st_size,
        initial_stat.st_mtime_ns,
        initial_stat.st_ino,
    ) != (final_stat.st_size, final_stat.st_mtime_ns, final_stat.st_ino):
        raise ValueError("source video changed during dual Profile rendering")
    manifest: dict[str, object] = {
        "schema_version": "1",
        "algorithm_version": DUAL_PROFILE_ALGORITHM_VERSION,
        "source_video": resolved_source.name,
        "profiles": [value.value for value in final.executed_profiles],
        "candidate_filter": sorted(candidate_filter) if candidate_filter is not None else None,
        "clip_count": len(manifest_clips),
        "clips": manifest_clips,
    }
    _write_json(output_dir / "render-manifest.json", manifest)
    return manifest


def _source_streams(path: Path) -> dict[str, int]:
    try:
        payload = run_ffprobe(path)
    except MediaIngestError as exc:
        raise ValueError("source video could not be inspected") from exc
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise ValueError("source video stream metadata is missing")
    selected: dict[str, int] = {}
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        codec_type = stream.get("codec_type")
        index = stream.get("index")
        if codec_type not in {"video", "audio"}:
            continue
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            continue
        if codec_type == "video":
            disposition = stream.get("disposition")
            if isinstance(disposition, dict) and disposition.get("attached_pic") == 1:
                continue
        selected.setdefault(f"{codec_type}_stream_index", index)
    if "video_stream_index" not in selected or "audio_stream_index" not in selected:
        raise ValueError("source video must contain normal video and audio streams")
    return selected


def _dual_profile_render_reason(profile: ClipProfile, candidate: FinalProfileCandidate) -> str:
    """Deterministic EditPlan reason built only from validated enums and the score."""

    return (
        f"Dual-profile {profile.value} candidate rendered with final status "
        f"{candidate.review_status.value} and score {candidate.score:.2f}."
    )


def _render_clip_id(candidate_id: str) -> str:
    safe = "".join(
        character if character.isascii() and (character.isalnum() or character in "-_") else "-"
        for character in candidate_id
    ).strip("-")
    if safe and len(safe) <= 64:
        return safe
    digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:16]
    return f"dual-{digest}"


# Bound on stale (now-invalid) cache entries chained by superseding keys.
_MAX_SUPERSEDED_CACHE_ENTRIES = 4


class _ResolutionAudit:
    """Run-level record of opt-in stale-cache refreshes and conservative fallbacks."""

    def __init__(self, *, refresh_stale_cache: bool) -> None:
        self.refresh_stale_cache = refresh_stale_cache
        self._lock = Lock()
        self._stale: list[StaleCacheResolution] = []
        self._fallbacks: list[BoundaryOpeningFallback] = []
        self._audit_fallbacks: list[AuditPairFallback] = []

    def record_stale(
        self,
        stage: str,
        profile: str,
        cache_key: str,
        superseding_cache_key: str,
        error: str,
        *,
        reused: bool,
    ) -> None:
        summary = " ".join(error.split())[:500] or "validation failed"
        with self._lock:
            self._stale.append(
                StaleCacheResolution(
                    stage=stage,
                    profile=profile,
                    cache_key=cache_key,
                    superseding_cache_key=superseding_cache_key,
                    error_summary=summary,
                    reused=reused,
                )
            )

    def record_fallbacks(self, records: Sequence[BaseModel]) -> None:
        with self._lock:
            for record in records:
                if isinstance(record, BoundaryOpeningFallback):
                    self._fallbacks.append(record)
                elif isinstance(record, AuditPairFallback):
                    self._audit_fallbacks.append(record)
                else:
                    raise TypeError("unknown conservative fallback record")

    def stale_resolutions(self) -> tuple[StaleCacheResolution, ...]:
        with self._lock:
            return tuple(sorted(self._stale, key=lambda v: (v.stage, v.profile, v.cache_key)))

    def opening_fallbacks(self) -> tuple[BoundaryOpeningFallback, ...]:
        with self._lock:
            return tuple(sorted(self._fallbacks, key=lambda v: (v.profile, v.subject_id)))

    def audit_fallbacks(self) -> tuple[AuditPairFallback, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._audit_fallbacks,
                    key=lambda v: (
                        v.profile,
                        v.rule,
                        v.outer_candidate_id,
                        v.inner_candidate_id,
                        v.blocked_candidate_id or "",
                        v.duplicate_candidate_id or "",
                    ),
                )
            )


@dataclass(frozen=True)
class _GeneratedCall:
    result: StructuredCallResult[BaseModel]
    records: tuple[ProviderCallRecord, ...]
    retry_count: int


def _generate_with_semantic_retry(
    *,
    provider: StructuredLLMProvider,
    subject_id: str,
    payload: dict[str, object],
    response_model: type[BaseModel],
    cancel_requested: Callable[[], bool],
) -> _GeneratedCall:
    """One initial request plus at most one retry after a structured provider failure."""

    try:
        result = provider.generate(
            subject_id=subject_id,
            payload=payload,
            response_model=response_model,
            cancel_requested=cancel_requested,
        )
    except StructuredProviderError as first_error:
        try:
            retried = provider.generate(
                subject_id=f"{subject_id}.semantic_retry_1",
                payload=payload,
                response_model=response_model,
                cancel_requested=cancel_requested,
            )
        except StructuredProviderError as second_error:
            raise StructuredProviderError(
                second_error.code,
                (*first_error.call_records, *second_error.call_records),
                repair_attempts=(
                    *first_error.repair_attempts,
                    *second_error.repair_attempts,
                ),
            ) from second_error
        return _GeneratedCall(retried, (*first_error.call_records, *retried.call_records), 1)
    return _GeneratedCall(result, tuple(result.call_records), 0)


# A stage's deterministic last-resort fallback: given the output that still failed
# after repair and regeneration and its error, return the fully validated fixed
# output, the affected candidate IDs (the cache marker) and the manifest records,
# or ``None`` when the failure is not eligible.
_FallbackResult = tuple[OutputModel, tuple[str, ...], tuple[BaseModel, ...]]
_ConservativeFallback = Callable[[OutputModel, ValueError], _FallbackResult[OutputModel] | None]


def _boundary_opening_fallback(
    profile: ClipProfile,
    subject_id: str,
    validate: Callable[[ProfileBoundaryReviewOutput], ProfileBoundaryReviewOutput],
) -> _ConservativeFallback[ProfileBoundaryReviewOutput]:
    """After repair and regeneration, only the opening invariant may be resolved,
    and only by downgrading ``opening_complete``; any other failure stays fatal."""

    def fallback(
        output: ProfileBoundaryReviewOutput, error: ValueError
    ) -> _FallbackResult[ProfileBoundaryReviewOutput] | None:
        if not isinstance(error, BoundaryOpeningInvariantError):
            return None
        fixed = validate(apply_boundary_opening_fallback(output, error.candidate_ids))
        record = BoundaryOpeningFallback(
            profile=profile, subject_id=subject_id, candidate_ids=error.candidate_ids
        )
        return fixed, error.candidate_ids, (record,)

    return fallback


def _merge_audit(
    value: ProfileGlobalAuditOutput, initial: ProfileGlobalReviewOutput
) -> ProfileGlobalReviewOutput:
    replacement_map = {item.candidate_id: item for item in value.replacements}
    return ProfileGlobalReviewOutput(
        profile=initial.profile,
        reviews=tuple(replacement_map.get(item.candidate_id, item) for item in initial.reviews),
    )


def _audit_pair_fallback(
    output: ProfileGlobalAuditOutput,
    error: ValueError,
    profile: ClipProfile,
    initial: ProfileGlobalReviewOutput,
    validate: Callable[[ProfileGlobalAuditOutput], ProfileGlobalAuditOutput],
    transcript: TranscriptDocument,
    persisted_flag_ids: frozenset[str],
) -> tuple[ProfileGlobalAuditOutput, tuple[str, ...], tuple[BaseModel, ...]] | None:
    """Downgrade-only Global Audit fallback (Stage 13b), after repair and regeneration.

    Eligible only when every remaining failure is a deterministic audit-pair rule
    (``AuditPairRuleError``). Each violating near-identical pair is resolved by
    blocking its longer member while the other member stays retained (see
    ``plan_audit_pair_fallback``). Representative-rule violations cannot be fixed
    without promoting a candidate, so the model's duplicate is accepted unchanged
    and recorded. Any other failure, or a near-identical violation the blocks do
    not resolve, keeps the run failing.
    """

    if not isinstance(error, AuditPairRuleError):
        return None
    blocks = plan_audit_pair_fallback(
        error,
        _merge_audit(output, initial),
        transcript,
        persisted_flag_ids=persisted_flag_ids,
    )
    fixed = apply_audit_pair_blocks(output, initial, [blocked for blocked, _ in blocks])
    remaining: tuple[AuditPairViolation, ...] = ()
    try:
        validate(fixed)
    except AuditPairRuleError as remaining_error:
        if remaining_error.near_identical:
            return None
        remaining = remaining_error.violations
    records: list[BaseModel] = [
        AuditPairFallback(
            profile=profile,
            rule=AuditPairRule.NEAR_IDENTICAL_PAIR,
            outer_candidate_id=pair[0],
            inner_candidate_id=pair[1],
            blocked_candidate_id=blocked,
        )
        for blocked, pair in blocks
    ]
    records.extend(
        AuditPairFallback(
            profile=profile,
            rule=value.rule,
            outer_candidate_id=value.outer_candidate_id,
            inner_candidate_id=value.inner_candidate_id,
            duplicate_candidate_id=value.duplicate_candidate_id,
        )
        for value in dict.fromkeys(remaining)
    )
    affected = sorted(
        {blocked for blocked, _ in blocks}
        | {value.duplicate_candidate_id for value in remaining if value.duplicate_candidate_id}
    )
    if not affected:
        return None
    return fixed, tuple(affected), tuple(records)


_FALLBACK_MARKER_FIELD = "conservative_fallback"


def _replay_cached_fallback(
    marker: object,
    stage: str,
    output: OutputModel,
    validate: Callable[[OutputModel], OutputModel],
    conservative_fallback: _ConservativeFallback[OutputModel] | None,
) -> _FallbackResult[OutputModel]:
    """Re-apply a recorded conservative fallback to a cached raw model output.

    The marker must name this stage and exactly the candidates the fallback would
    downgrade now, the raw output must fail current validation, and the downgraded
    output must pass it; anything else is an untrusted cache entry and fails closed
    in both refresh modes.
    """

    invalid = ValueError("dual Profile cache fallback marker is invalid")
    if (
        conservative_fallback is None
        or not isinstance(marker, dict)
        or set(marker) != {"stage", "candidate_ids"}
        or marker["stage"] != stage
        or not isinstance(marker["candidate_ids"], list)
        or not marker["candidate_ids"]
        or not all(isinstance(value, str) for value in marker["candidate_ids"])
    ):
        raise invalid
    try:
        validate(output)
    except ValueError as error:
        rescued = _apply_conservative_fallback(conservative_fallback, output, error)
    else:
        raise invalid
    if rescued is None or list(rescued[1]) != marker["candidate_ids"]:
        raise invalid
    return rescued


def _apply_conservative_fallback(
    conservative_fallback: _ConservativeFallback[OutputModel] | None,
    output: OutputModel,
    error: ValueError,
) -> _FallbackResult[OutputModel] | None:
    """Apply the stage's deterministic fallback; ``None`` unless it fully validates."""

    if conservative_fallback is None:
        return None
    try:
        return conservative_fallback(output, error)
    except ValueError:
        return None


def _resolve_call(
    *,
    stage: str,
    subject_id: str,
    payload: dict[str, object],
    response_model: type[OutputModel],
    provider: StructuredLLMProvider,
    profile: ClipProfile | str,
    source_hash: str,
    window_start: int,
    window_end: int,
    cache_dir: Path | None,
    validate: Callable[[OutputModel], OutputModel],
    cancel_requested: Callable[[], bool],
    resolution_audit: _ResolutionAudit | None = None,
    conservative_fallback: _ConservativeFallback[OutputModel] | None = None,
) -> _ResolvedCall:
    # Without an explicit audit the Stage 9 fail-closed default applies.
    if resolution_audit is None:
        resolution_audit = _ResolutionAudit(refresh_stale_cache=False)
    model_settings = {
        "reasoning_effort": getattr(provider, "reasoning_effort", "provider_default"),
        "contract_version": provider.contract_version,
    }
    payload_sha256 = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    cache_settings = {
        **model_settings,
        "stage": stage,
        "payload_sha256": payload_sha256,
        "output_model": response_model.__name__,
    }
    profile_value = profile.value if isinstance(profile, ClipProfile) else profile

    def cache_location(settings: Mapping[str, object]) -> tuple[str, Path | None]:
        location_key = semantic_cache_key(
            source_hash=source_hash,
            profile=profile,
            window_start=window_start,
            window_end=window_end,
            prompt_hash=provider.prompt_sha256,
            model=provider.model_name,
            model_settings=dict(settings),
        )
        return location_key, (
            cache_dir / profile_value / stage / f"{location_key}.json" if cache_dir else None
        )

    key, cache_path = cache_location(cache_settings)
    # Stage 9 contract: every cache hit is fully validated, and by default a cached
    # output that fails current validation fails the run closed. A cached raw output
    # whose entry carries the conservative-fallback marker is re-resolved with the
    # same deterministic fallback (Stage 12c), never treated as stale. Only with the
    # explicit refresh option is such an entry treated as stale: it stays untouched,
    # its output goes through the ordinary repair path, and the result is cached under
    # a superseding key whose settings add the sha256 of the stale output's canonical
    # JSON (``model_dump``). Every stale resolution is recorded in the run manifest.
    stale: tuple[OutputModel, ValueError] | None = None
    pending_link: tuple[str, str, str] | None = None
    for _ in range(_MAX_SUPERSEDED_CACHE_ENTRIES + 1):
        if cache_path is None:
            break
        try:
            raw = json.loads(read_regular_text_no_follow(cache_path, max_bytes=32 * 1024 * 1024))
        except SecureFileMissing:
            if pending_link is not None:
                resolution_audit.record_stale(stage, profile_value, *pending_link, reused=False)
            break
        except (SecureFileError, json.JSONDecodeError) as exc:
            raise ValueError("dual Profile cache exists but is not trusted") from exc
        if not isinstance(raw, dict) or raw.get("cache_key") != key:
            raise ValueError("dual Profile cache identity is invalid")
        output = response_model.model_validate_json(
            json.dumps(raw.get("output"), ensure_ascii=False)
        )
        has_marker = _FALLBACK_MARKER_FIELD in raw
        if pending_link is not None:
            # Recorded only once the superseding entry passed its identity check.
            resolution_audit.record_stale(stage, profile_value, *pending_link, reused=True)
            pending_link = None
        if has_marker:
            # The cache holds the raw model output. Its marker says the cold run
            # resolved it with the deterministic conservative fallback after repair
            # and regeneration, so the same fallback is re-applied and recorded: a
            # warm rerun reproduces the cold output and the manifest record.
            fixed_hit, _hit_ids, hit_records = _replay_cached_fallback(
                raw[_FALLBACK_MARKER_FIELD], stage, output, validate, conservative_fallback
            )
            resolution_audit.record_fallbacks(hit_records)
            return _ResolvedCall(
                output=fixed_hit,
                records=(),
                cache_hit=True,
                retry_count=0,
                repair_count=0,
            )
        try:
            validate(output)
        except ValueError as stale_error:
            if not resolution_audit.refresh_stale_cache:
                raise
            stale = (output, stale_error)
            stale_key = key
            cache_settings = {
                **cache_settings,
                "supersedes_cache_output_sha256": hashlib.sha256(
                    json.dumps(
                        output.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            }
            key, cache_path = cache_location(cache_settings)
            pending_link = (stale_key, key, str(stale_error))
            continue
        return _ResolvedCall(
            output=output,
            records=(),
            cache_hit=True,
            retry_count=0,
            repair_count=0,
        )
    else:
        raise ValueError("dual Profile cache has too many superseded entries")
    semantic_retry_count = 0
    records: list[ProviderCallRecord] = []
    resolved_repair_count = 0
    # After a conservative fallback the cache keeps the raw model output plus a
    # marker naming the downgraded candidates; otherwise it keeps ``output``.
    cached_output: OutputModel | None = None
    fallback_marker: dict[str, object] | None = None
    first_output: OutputModel
    first_error: ValueError | None
    if stale is not None:
        first_output, first_error = stale
    else:
        result = _generate_with_semantic_retry(
            provider=provider,
            subject_id=subject_id,
            payload=payload,
            response_model=response_model,
            cancel_requested=cancel_requested,
        )
        semantic_retry_count = result.retry_count
        records.extend(result.records)
        first_output = cast(OutputModel, result.result.output)
        resolved_repair_count = max(int(result.result.repaired), len(result.result.repair_attempts))
        try:
            output = validate(first_output)
            first_error = None
        except ValueError as exc:
            first_error = exc
    if first_error is not None:
        repaired_result = provider.repair(
            subject_id=subject_id,
            payload={
                **payload,
                "invalid_output": first_output.model_dump(mode="json"),
                "deterministic_validation_errors": [str(first_error)[:2_000]],
            },
            response_model=response_model,
            validation_errors=(str(first_error)[:500],),
            cancel_requested=cancel_requested,
        )
        records.extend(repaired_result.call_records)
        resolved_repair_count += max(
            1,
            int(repaired_result.repaired),
            len(repaired_result.repair_attempts),
        )
        try:
            output = validate(repaired_result.output)
        except ValueError as repaired_error:
            semantic_retry_count += 1
            validation_retry_result = provider.generate(
                subject_id=f"{subject_id}.deterministic_retry_1",
                payload={
                    **payload,
                    "invalid_output": repaired_result.output.model_dump(mode="json"),
                    "deterministic_validation_errors": [str(repaired_error)[:2_000]],
                    "required_action": (
                        "Regenerate the whole response once. Omit an optional Discovery "
                        "candidate if no cue-exact interval satisfies every deterministic "
                        "constraint; never pad or alter cue timestamps."
                    ),
                },
                response_model=response_model,
                cancel_requested=cancel_requested,
            )
            records.extend(validation_retry_result.call_records)
            resolved_repair_count += max(
                int(validation_retry_result.repaired),
                len(validation_retry_result.repair_attempts),
            )
            try:
                output = validate(validation_retry_result.output)
            except ValueError as final_error:
                rescued = _apply_conservative_fallback(
                    conservative_fallback,
                    validation_retry_result.output,
                    final_error,
                )
                if rescued is None:
                    raise ValueError(
                        "deterministic validation still failed after one repair and one "
                        f"regeneration: {final_error}"
                    ) from final_error
                output, fallback_ids, fallback_records = rescued
                cached_output = validation_retry_result.output
                fallback_marker = {"stage": stage, "candidate_ids": list(fallback_ids)}
                resolution_audit.record_fallbacks(fallback_records)
    if cache_path is not None:
        ensure_directory_no_follow(cache_path.parent)
        cache_document: dict[str, object] = {
            "schema_version": "1",
            "cache_key": key,
            "source_hash": source_hash,
            "profile": profile_value,
            "stage": stage,
            "window_start": window_start,
            "window_end": window_end,
            "prompt_hash": provider.prompt_sha256,
            "model": provider.model_name,
            "model_settings": cache_settings,
            "output_model": response_model.__name__,
            "output": (cached_output or output).model_dump(mode="json"),
        }
        if fallback_marker is not None:
            # Only fallback entries carry the marker, so every other entry keeps
            # exactly the bytes earlier code wrote.
            cache_document[_FALLBACK_MARKER_FIELD] = fallback_marker
        payload_text = (
            json.dumps(cache_document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        try:
            write_text_immutable_no_follow(
                cache_path,
                payload_text,
                max_bytes=32 * 1024 * 1024,
            )
        except FileExistsError as exc:
            existing = read_regular_text_no_follow(cache_path, max_bytes=32 * 1024 * 1024)
            if existing != payload_text:
                raise ValueError(
                    "dual Profile cache publication raced with different bytes"
                ) from exc
    return _ResolvedCall(
        output=output,
        records=tuple(records),
        cache_hit=False,
        retry_count=semantic_retry_count,
        repair_count=resolved_repair_count,
    )


def _discovery_payload(source_hash: str, window: DiscoveryWindow) -> dict[str, object]:
    return {
        "schema_version": "1",
        "algorithm_version": DUAL_PROFILE_ALGORITHM_VERSION,
        "source_hash": source_hash,
        "profile": window.profile.value,
        "window_id": window.window_id,
        "context_range": {
            "start_ms": window.context_start_ms,
            "end_ms": window.context_end_ms,
        },
        "ownership_interval": {
            "start_ms": window.ownership_start_ms,
            "end_ms": window.ownership_end_ms,
            "end_exclusive": True,
        },
        "cues": [value.model_dump(mode="json") for value in window.cues],
    }


def _boundary_payload(
    profile: ClipProfile,
    candidates: Sequence[RawProfileCandidate],
    transcript: TranscriptDocument,
    discovery_pass_by_id: Mapping[str, str],
) -> dict[str, object]:
    guard_ms = 30_000 if profile == ClipProfile.SHORT_HIGHLIGHT else 60_000
    return {
        "schema_version": "1",
        "algorithm_version": DUAL_PROFILE_ALGORITHM_VERSION,
        "profile": profile.value,
        "candidates": [
            {
                "candidate": value.model_dump(mode="json"),
                "discovery_pass": discovery_pass_by_id[value.candidate_id],
                "context": _candidate_context(value, transcript, guard_ms=guard_ms),
            }
            for value in candidates
        ],
    }


def _global_payload(
    profile: ClipProfile,
    candidates: Sequence[RawProfileCandidate],
    boundary: ProfileBoundaryReviewOutput,
    transcript: TranscriptDocument,
    discovery_pass_by_id: Mapping[str, str],
) -> dict[str, object]:
    boundary_map = {value.candidate_id: value for value in boundary.reviews}
    guard_ms = 30_000 if profile == ClipProfile.SHORT_HIGHLIGHT else 60_000
    candidate_payloads: list[dict[str, object]] = []
    cue_catalog: dict[int, dict[str, object]] = {}
    for value in candidates:
        context = _candidate_context(value, transcript, guard_ms=guard_ms)
        context_refs: dict[str, list[int]] = {}
        for section, cue_values in context.items():
            identifiers: list[int] = []
            for cue in cue_values:
                cue_id = cue.get("cue_id")
                if not isinstance(cue_id, int) or isinstance(cue_id, bool):
                    raise ValueError("candidate context contains an invalid cue ID")
                identifiers.append(cue_id)
                cue_catalog.setdefault(cue_id, cue)
            context_refs[f"{section}_cue_ids"] = identifiers
        candidate_payloads.append(
            {
                "candidate": value.model_dump(mode="json"),
                "discovery_pass": discovery_pass_by_id[value.candidate_id],
                "boundary_review": boundary_map[value.candidate_id].model_dump(mode="json"),
                "context_refs": context_refs,
            }
        )
    return {
        "schema_version": "1",
        "algorithm_version": DUAL_PROFILE_ALGORITHM_VERSION,
        "profile": profile.value,
        "cross_profile_dedup_forbidden": True,
        "candidates": candidate_payloads,
        "cue_catalog": [cue_catalog[key] for key in sorted(cue_catalog)],
    }


def _chunks(
    values: Sequence[RawProfileCandidate], *, size: int
) -> tuple[tuple[RawProfileCandidate, ...], ...]:
    if size < 1:
        raise ValueError("chunk size must be positive")
    return tuple(tuple(values[index : index + size]) for index in range(0, len(values), size))


def _candidate_context(
    candidate: RawProfileCandidate,
    transcript: TranscriptDocument,
    *,
    guard_ms: int,
) -> dict[str, list[dict[str, object]]]:
    cues = transcript_cues(transcript)
    cue_map = {value.cue_id: value for value in cues}
    start = cue_map[candidate.start_cue_id].start_ms
    end = cue_map[candidate.end_cue_id].end_ms
    before = tuple(
        value for value in cues if value.end_ms > start - guard_ms and value.end_ms <= start
    )
    complete = tuple(
        value for value in cues if candidate.start_cue_id <= value.cue_id <= candidate.end_cue_id
    )
    after = tuple(
        value for value in cues if value.start_ms >= end and value.start_ms < end + guard_ms
    )
    return {
        "before": [value.model_dump(mode="json") for value in before],
        "complete_candidate": [value.model_dump(mode="json") for value in complete],
        "after": [value.model_dump(mode="json") for value in after],
    }


def _usage_total(calls: Sequence[ProviderCallRecord], key: str) -> int:
    return sum(
        int(record.usage_json[key])
        for record in calls
        if record.usage_json is not None
        and isinstance(record.usage_json.get(key), int)
        and not isinstance(record.usage_json[key], bool)
    )


def _call_metadata(value: ProviderCallRecord) -> dict[str, object]:
    return {
        **value.durable_metadata(),
        "operation": value.operation,
        "provider": value.provider,
        "model": value.model,
        "request_count": value.request_count,
        "retry_count": value.retry_count,
        "latency_ms": value.latency_ms,
        "usage": value.usage_json,
        "status": value.status.value,
    }


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    write_text_immutable_no_follow(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        max_bytes=128 * 1024 * 1024,
    )


__all__ = [
    "DualProfileProviderFactory",
    "configured_dual_profile_provider_factory",
    "render_dual_profile_candidates",
    "run_dual_profile_evaluation",
]
