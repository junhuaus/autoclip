from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar, cast

from pydantic import BaseModel

from liveclip.clipping_skills.dual_profile_v1 import (
    load_dual_profile_prompt,
    load_dual_profile_variant_link_prompt,
)
from liveclip.clipping_skills.semantic_global_v1 import SemanticGlobalPromptBundle
from liveclip.domain.clip_profile import ClipProfile
from liveclip.pipeline.dual_profile import (
    BoundaryReviewItem,
    BoundaryState,
    CandidateDisposition,
    CrossProfileVariantLinkOutput,
    DualProfileFinalResult,
    DualProfileRunManifest,
    GlobalReviewItem,
    ProfileBoundaryReviewOutput,
    ProfileDiscoveryOutput,
    ProfileGlobalAuditOutput,
    ProfileGlobalReviewOutput,
    RawProfileCandidate,
    VariantLinkItem,
)
from liveclip.providers.llm.structured import StructuredCallResult, StructuredProviderError
from liveclip.services.dual_profile_evaluation import run_dual_profile_evaluation

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class ScriptedDualProvider:
    contract_version = "scripted-dual-v1"

    def __init__(self, prompt: SemanticGlobalPromptBundle, counter: dict[str, int]) -> None:
        self._prompt = prompt
        self._counter = counter

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-dual-v1"

    @property
    def prompt_version(self) -> str:
        return self._prompt.version

    @property
    def prompt_sha256(self) -> str:
        return self._prompt.sha256

    @property
    def reasoning_effort(self) -> str:
        return "mock"

    def generate(
        self,
        *,
        subject_id: str,
        payload: dict[str, object],
        response_model: type[OutputModel],
        cancel_requested=lambda: False,
    ) -> StructuredCallResult[OutputModel]:
        del subject_id, cancel_requested
        self._counter[response_model.__name__] = self._counter.get(response_model.__name__, 0) + 1
        output = self._output(payload, response_model)
        return StructuredCallResult(output=output, call_records=(), repaired=False)

    def repair(
        self,
        *,
        subject_id: str,
        payload: dict[str, object],
        response_model: type[OutputModel],
        validation_errors: tuple[str, ...],
        cancel_requested=lambda: False,
    ) -> StructuredCallResult[OutputModel]:
        del subject_id, validation_errors, cancel_requested
        output = self._output(payload, response_model)
        return StructuredCallResult(output=output, call_records=(), repaired=True)

    def _output(
        self,
        payload: dict[str, object],
        response_model: type[OutputModel],
    ) -> OutputModel:
        if response_model is CrossProfileVariantLinkOutput:
            candidates = cast(list[dict[str, object]], payload["candidates"])
            return cast(
                OutputModel,
                CrossProfileVariantLinkOutput(
                    links=tuple(
                        VariantLinkItem(
                            candidate_id=str(value["candidate_id"]),
                            variant_group_id="shared_lesson",
                        )
                        for value in candidates
                    )
                ),
            )
        if response_model is ProfileGlobalAuditOutput:
            return cast(
                OutputModel,
                ProfileGlobalAuditOutput(
                    profile=ClipProfile(str(payload["profile"])),
                    replacements=(),
                    audit_reason="Mock audit found no corrections.",
                ),
            )
        profile = ClipProfile(str(payload["profile"]))
        if response_model is ProfileDiscoveryOutput:
            window_id = str(payload["window_id"])
            if payload.get("discovery_pass") in {
                "coverage_audit",
                "precision_audit",
                "precision_confirmation",
                "risk_discovery",
            }:
                return cast(
                    OutputModel,
                    ProfileDiscoveryOutput(profile=profile, window_id=window_id),
                )
            ownership = cast(dict[str, object], payload["ownership_interval"])
            if int(ownership["start_ms"]) != 0:
                value = ProfileDiscoveryOutput(
                    profile=profile,
                    window_id=window_id,
                )
            else:
                end_cue = 5 if profile == ClipProfile.SHORT_HIGHLIGHT else 11
                candidate = RawProfileCandidate(
                    candidate_id=f"{profile.value}_lesson",
                    profile=profile,
                    variant_group_id="shared_lesson",
                    source_window_id=window_id,
                    start_cue_id=1,
                    end_cue_id=end_cue,
                    evidence_cue_ids=(1, end_cue),
                    title="同主题教学",
                    summary="同一主题的独立短版或完整长版。",
                    boundary_state=BoundaryState(
                        opening_complete=True,
                        ending_complete=True,
                    ),
                )
                value = ProfileDiscoveryOutput(
                    profile=profile,
                    window_id=window_id,
                    candidates=(candidate,),
                )
            return cast(OutputModel, value)
        raw_candidates = cast(list[dict[str, object]], payload["candidates"])
        candidates = tuple(
            RawProfileCandidate.model_validate_json(
                json.dumps(cast(dict[str, object], value["candidate"]))
            )
            for value in raw_candidates
        )
        if response_model is ProfileBoundaryReviewOutput:
            value = ProfileBoundaryReviewOutput(
                profile=profile,
                reviews=tuple(
                    BoundaryReviewItem(
                        candidate_id=candidate.candidate_id,
                        profile=profile,
                        start_cue_id=candidate.start_cue_id,
                        end_cue_id=candidate.end_cue_id,
                        opening_complete=True,
                        ending_complete=True,
                        central_objective_complete=True,
                        shortest_complete_boundary=True,
                        evidence_cue_ids=candidate.evidence_cue_ids,
                        review_reason="Mock confirms a complete shortest boundary.",
                    )
                    for candidate in candidates
                ),
            )
            return cast(OutputModel, value)
        if response_model is ProfileGlobalReviewOutput:
            value = ProfileGlobalReviewOutput(
                profile=profile,
                reviews=tuple(
                    GlobalReviewItem(
                        candidate_id=candidate.candidate_id,
                        profile=profile,
                        variant_group_id=candidate.variant_group_id,
                        start_cue_id=candidate.start_cue_id,
                        end_cue_id=candidate.end_cue_id,
                        title=candidate.title,
                        hook="一个完整教学钩子",
                        summary=candidate.summary,
                        score=90,
                        review_status=CandidateDisposition.SELECTED,
                        evidence_cue_ids=candidate.evidence_cue_ids,
                        review_reason="Mock global review retains the complete unit.",
                    )
                    for candidate in candidates
                ),
            )
            return cast(OutputModel, value)
        raise AssertionError(f"unexpected response model: {response_model.__name__}")


class SchemaThenDeterministicRepairProvider(ScriptedDualProvider):
    def __init__(self, prompt: SemanticGlobalPromptBundle, counter: dict[str, int]) -> None:
        super().__init__(prompt, counter)
        self.deterministic_repairs = 0

    def generate(
        self,
        *,
        subject_id: str,
        payload: dict[str, object],
        response_model: type[OutputModel],
        cancel_requested=lambda: False,
    ) -> StructuredCallResult[OutputModel]:
        if (
            response_model is ProfileDiscoveryOutput
            and "deterministic_retry_1" not in subject_id
            and payload.get("profile") == ClipProfile.SHORT_HIGHLIGHT.value
            and payload.get("discovery_pass") is None
            and cast(dict[str, object], payload["ownership_interval"])["start_ms"] == 0
        ):
            candidate = RawProfileCandidate(
                candidate_id="schema_repaired_but_too_short",
                profile=ClipProfile.SHORT_HIGHLIGHT,
                source_window_id=str(payload["window_id"]),
                start_cue_id=1,
                end_cue_id=2,
                evidence_cue_ids=(1, 2),
                title="时长仍非法",
                summary="Schema 已修复但确定性时长仍非法。",
                boundary_state=BoundaryState(opening_complete=True, ending_complete=True),
            )
            return StructuredCallResult(
                output=cast(
                    OutputModel,
                    ProfileDiscoveryOutput(
                        profile=ClipProfile.SHORT_HIGHLIGHT,
                        window_id=str(payload["window_id"]),
                        candidates=(candidate,),
                    ),
                ),
                call_records=(),
                repaired=True,
                repair_attempts=({"phase": "schema"},),
            )
        return super().generate(
            subject_id=subject_id,
            payload=payload,
            response_model=response_model,
            cancel_requested=cancel_requested,
        )

    def repair(
        self,
        *,
        subject_id: str,
        payload: dict[str, object],
        response_model: type[OutputModel],
        validation_errors: tuple[str, ...],
        cancel_requested=lambda: False,
    ) -> StructuredCallResult[OutputModel]:
        if (
            response_model is ProfileDiscoveryOutput
            and payload.get("profile") == ClipProfile.SHORT_HIGHLIGHT.value
            and payload.get("discovery_pass") is None
            and cast(dict[str, object], payload["ownership_interval"])["start_ms"] == 0
        ):
            self.deterministic_repairs += 1
            return StructuredCallResult(
                output=cast(
                    OutputModel,
                    ProfileDiscoveryOutput(
                        profile=ClipProfile.SHORT_HIGHLIGHT,
                        window_id=str(payload["window_id"]),
                    ),
                ),
                call_records=(),
                repaired=True,
                repair_attempts=({"phase": "deterministic"},),
            )
        return super().repair(
            subject_id=subject_id,
            payload=payload,
            response_model=response_model,
            validation_errors=validation_errors,
            cancel_requested=cancel_requested,
        )


class FailOnceStructuredProvider(ScriptedDualProvider):
    def __init__(
        self,
        prompt: SemanticGlobalPromptBundle,
        counter: dict[str, int],
        failure_state: dict[str, bool],
    ) -> None:
        super().__init__(prompt, counter)
        self._failure_state = failure_state

    def generate(
        self,
        *,
        subject_id: str,
        payload: dict[str, object],
        response_model: type[OutputModel],
        cancel_requested=lambda: False,
    ) -> StructuredCallResult[OutputModel]:
        if not self._failure_state.get("raised"):
            self._failure_state["raised"] = True
            raise StructuredProviderError("STRUCTURED_OUTPUT_INVALID", ())
        return super().generate(
            subject_id=subject_id,
            payload=payload,
            response_model=response_model,
            cancel_requested=cancel_requested,
        )


class InvalidDeterministicRepairProvider(SchemaThenDeterministicRepairProvider):
    def repair(
        self,
        *,
        subject_id: str,
        payload: dict[str, object],
        response_model: type[OutputModel],
        validation_errors: tuple[str, ...],
        cancel_requested=lambda: False,
    ) -> StructuredCallResult[OutputModel]:
        if (
            response_model is ProfileDiscoveryOutput
            and payload.get("profile") == ClipProfile.SHORT_HIGHLIGHT.value
            and payload.get("discovery_pass") is None
            and cast(dict[str, object], payload["ownership_interval"])["start_ms"] == 0
        ):
            self.deterministic_repairs += 1
            return self.generate(
                subject_id="still_invalid",
                payload=payload,
                response_model=response_model,
                cancel_requested=cancel_requested,
            )
        return super().repair(
            subject_id=subject_id,
            payload=payload,
            response_model=response_model,
            validation_errors=validation_errors,
            cancel_requested=cancel_requested,
        )


def _write_srt(path: Path) -> None:
    cues = []
    for index in range(1, 71):
        start = (index - 1) * 10
        end = index * 10
        cues.append(
            f"{index}\n"
            f"00:{start // 60:02d}:{start % 60:02d},000 --> "
            f"00:{end // 60:02d}:{end % 60:02d},000\n"
            f"教学内容{index}\n"
        )
    path.write_text("\n".join(cues), encoding="utf-8")


def test_dual_profile_service_executes_independent_pools_and_reuses_profile_cache(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    cache = tmp_path / "cache"
    counter: dict[str, int] = {}

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        return ScriptedDualProvider(prompt, counter)

    first_dir = tmp_path / "first"
    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=first_dir,
        provider_factory=factory,
        cache_dir=cache,
        discovery_concurrency=2,
    )
    final = DualProfileFinalResult.model_validate_json(
        (first_dir / "final-validated.json").read_text(encoding="utf-8")
    )
    manifest = DualProfileRunManifest.model_validate_json(
        (first_dir / "run-manifest.json").read_text(encoding="utf-8")
    )
    manifest.validate_against(final)
    assert final.requested_profiles == (
        ClipProfile.SHORT_HIGHLIGHT,
        ClipProfile.MINI_LESSON,
    )
    assert final.executed_profiles == final.requested_profiles
    assert final.profiles[ClipProfile.SHORT_HIGHLIGHT].statistics.selected == 1
    assert final.profiles[ClipProfile.MINI_LESSON].statistics.selected == 1
    assert (
        final.profiles[ClipProfile.SHORT_HIGHLIGHT].selected[0].variant_group_id
        == final.profiles[ClipProfile.MINI_LESSON].selected[0].variant_group_id
    )
    generated = sum(counter.values())
    assert generated > 4

    second_dir = tmp_path / "second"
    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=second_dir,
        provider_factory=factory,
        cache_dir=cache,
        discovery_concurrency=2,
    )
    assert sum(counter.values()) == generated
    second_manifest = DualProfileRunManifest.model_validate_json(
        (second_dir / "run-manifest.json").read_text(encoding="utf-8")
    )
    assert second_manifest.cache_hits > 0
    assert second_manifest.calls == {
        "discovery": 0,
        "boundary_review": 0,
        "global_review": 0,
        "variant_link": 0,
    }


def test_dual_profile_prompts_are_profile_specific_and_forbid_cross_dedup() -> None:
    short = load_dual_profile_prompt("discovery", ClipProfile.SHORT_HIGHLIGHT)
    mini = load_dual_profile_prompt("discovery", ClipProfile.MINI_LESSON)
    review = load_dual_profile_prompt("global_review", ClipProfile.MINI_LESSON)
    audit = load_dual_profile_prompt("coverage_audit", ClipProfile.MINI_LESSON)
    risk = load_dual_profile_prompt("risk_discovery", ClipProfile.MINI_LESSON)
    precision = load_dual_profile_prompt("precision_audit", ClipProfile.MINI_LESSON)
    confirmation = load_dual_profile_prompt("precision_confirmation", ClipProfile.MINI_LESSON)
    global_audit = load_dual_profile_prompt("global_audit", ClipProfile.MINI_LESSON)
    variant = load_dual_profile_variant_link_prompt()
    assert short.sha256 != mini.sha256
    assert "45,000\u201390,000" in short.instructions
    assert "600-second" in mini.instructions
    assert "strictly longer than 90,000" in mini.instructions
    assert "Risk Discovery" in risk.instructions
    assert "Precision Coverage Audit" in precision.instructions
    assert "candidate_id` must start with `precision_" in precision.instructions
    assert "Precision Confirmation" in confirmation.instructions
    assert "candidate_id` beginning with `confirm_" in confirmation.instructions
    assert "Global Review Audit" in global_audit.instructions
    assert "pre-question foundation" in global_audit.instructions
    assert "shortest complete representative" in global_audit.instructions
    assert "overview-to-first-category risk chain" in global_audit.instructions
    assert "recap-only opening" in global_audit.instructions
    assert "status, flags and reason must agree" in global_audit.instructions
    assert "explicitly restart with a local first-step statement" in global_audit.instructions
    assert "does not make a recap-only comparison complete" in global_audit.instructions
    assert "local reference to an earlier technique" in review.instructions
    assert "recap-only version" in review.instructions
    assert (
        "first local\nintroduction"
        in load_dual_profile_prompt("boundary_review", ClipProfile.SHORT_HIGHLIGHT).instructions
    )
    assert "never reject, merge, deduplicate" in variant.instructions
    assert "only inside this Profile" in review.instructions
    assert "candidate_id` must start with `audit_" in audit.instructions
    assert "ownership_interval` literally" in audit.instructions
    assert "strictly less than `ownership_interval.end_ms`" in audit.instructions


def test_service_allows_one_deterministic_repair_after_provider_schema_repair(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    counter: dict[str, int] = {}
    providers: list[SchemaThenDeterministicRepairProvider] = []

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        provider = SchemaThenDeterministicRepairProvider(prompt, counter)
        providers.append(provider)
        return provider

    output_dir = tmp_path / "output"
    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=output_dir,
        provider_factory=factory,
        discovery_concurrency=2,
    )
    manifest = DualProfileRunManifest.model_validate_json(
        (output_dir / "run-manifest.json").read_text(encoding="utf-8")
    )
    final = DualProfileFinalResult.model_validate_json(
        (output_dir / "final-validated.json").read_text(encoding="utf-8")
    )
    assert sum(value.deterministic_repairs for value in providers) == 1
    assert manifest.repair_count == 2
    assert final.profiles[ClipProfile.SHORT_HIGHLIGHT].statistics.discovered == 0


def test_service_retries_one_structured_provider_failure_and_audits_it(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    counter: dict[str, int] = {}
    failure_state: dict[str, bool] = {}

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        return FailOnceStructuredProvider(prompt, counter, failure_state)

    output_dir = tmp_path / "output"
    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=output_dir,
        provider_factory=factory,
        discovery_concurrency=1,
    )
    manifest = DualProfileRunManifest.model_validate_json(
        (output_dir / "run-manifest.json").read_text(encoding="utf-8")
    )
    assert failure_state == {"raised": True}
    assert manifest.retry_count == 1


def test_service_regenerates_once_when_deterministic_repair_is_still_invalid(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    counter: dict[str, int] = {}

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        return InvalidDeterministicRepairProvider(prompt, counter)

    output_dir = tmp_path / "output"
    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=output_dir,
        provider_factory=factory,
        discovery_concurrency=1,
    )
    manifest = DualProfileRunManifest.model_validate_json(
        (output_dir / "run-manifest.json").read_text(encoding="utf-8")
    )
    final = DualProfileFinalResult.model_validate_json(
        (output_dir / "final-validated.json").read_text(encoding="utf-8")
    )
    assert manifest.retry_count == 1
    assert manifest.repair_count == 2
    assert final.profiles[ClipProfile.SHORT_HIGHLIGHT].statistics.discovered == 1
