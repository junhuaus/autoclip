from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, TypeVar, cast

import pytest
from pydantic import BaseModel

from liveclip.clipping_skills.dual_profile_v1 import (
    load_dual_profile_prompt,
    load_dual_profile_variant_link_prompt,
)
from liveclip.clipping_skills.semantic_global_v1 import SemanticGlobalPromptBundle
from liveclip.domain.clip_profile import ClipProfile
from liveclip.pipeline.dual_profile import (
    DUAL_PROFILE_ROUTING_POLICY_VERSION,
    BoundaryReviewItem,
    BoundaryState,
    CandidateDisposition,
    CrossProfileVariantLinkOutput,
    DualProfileFinalResult,
    DualProfileRunManifest,
    DualRiskTag,
    GlobalReviewItem,
    NestedPairDecision,
    NestedPairDecisionKind,
    ProfileBoundaryReviewOutput,
    ProfileDiscoveryOutput,
    ProfileGlobalAuditOutput,
    ProfileGlobalReviewOutput,
    RawProfileCandidate,
    VariantLinkItem,
)
from liveclip.providers.llm import claude_cli as claude_cli_module
from liveclip.providers.llm.claude_cli import ClaudeCliStructuredLLMProvider
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
                    nested_pair_decisions=(),
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


class RiskRoutingProvider(ScriptedDualProvider):
    """Adds a risk-pass record and a base-pass look-alike that share the risk_ prefix."""

    def _output(
        self,
        payload: dict[str, object],
        response_model: type[OutputModel],
    ) -> OutputModel:
        mini = payload.get("profile") == ClipProfile.MINI_LESSON.value
        profile = ClipProfile.MINI_LESSON
        if response_model is ProfileDiscoveryOutput and mini:
            window_id = str(payload["window_id"])
            ownership = cast(dict[str, object], payload["ownership_interval"])
            discovery_pass = payload.get("discovery_pass")
            if int(ownership["start_ms"]) == 0 and discovery_pass in {None, "risk_discovery"}:
                base = cast(ProfileDiscoveryOutput, super()._output(payload, response_model))
                extra = RawProfileCandidate(
                    candidate_id=(
                        "risk_from_pass" if discovery_pass == "risk_discovery" else "risk_lookalike"
                    ),
                    profile=profile,
                    source_window_id=window_id,
                    start_cue_id=2 if discovery_pass is None else 3,
                    end_cue_id=12 if discovery_pass is None else 13,
                    evidence_cue_ids=(4,),
                    title="风险相关内容",
                    summary="包含健康主张的教学片段。",
                    boundary_state=BoundaryState(opening_complete=True, ending_complete=True),
                    risk_tags=(DualRiskTag.MEDICAL_CLAIM,),
                )
                candidates = (extra,) if discovery_pass else (*base.candidates, extra)
                return cast(
                    OutputModel,
                    ProfileDiscoveryOutput(
                        profile=profile, window_id=window_id, candidates=candidates
                    ),
                )
        output = super()._output(payload, response_model)
        if response_model is ProfileBoundaryReviewOutput:
            raw = {
                value.candidate_id: value
                for value in (
                    RawProfileCandidate.model_validate_json(json.dumps(item["candidate"]))
                    for item in cast(list[dict[str, Any]], payload["candidates"])
                )
            }
            boundary = cast(ProfileBoundaryReviewOutput, output)
            return cast(
                OutputModel,
                boundary.model_copy(
                    update={
                        "reviews": tuple(
                            item.model_copy(update={"risk_tags": raw[item.candidate_id].risk_tags})
                            for item in boundary.reviews
                        )
                    }
                ),
            )
        if response_model is ProfileGlobalReviewOutput and mini:
            review = cast(ProfileGlobalReviewOutput, output)
            return cast(
                OutputModel,
                review.model_copy(
                    update={
                        "reviews": tuple(
                            item
                            if not item.candidate_id.startswith("risk_")
                            else item.model_copy(
                                update={
                                    "score": 60.0,
                                    "review_status": CandidateDisposition.REJECTED,
                                    "duplicate_of_candidate_id": "mini_lesson_lesson",
                                    "risk_tags": (DualRiskTag.MEDICAL_CLAIM,),
                                    "review_reason": "Duplicate of the representative lesson.",
                                }
                            )
                            for item in review.reviews
                        )
                    }
                ),
            )
        return output


class NestedPairProvider(ScriptedDualProvider):
    """Mini Discovery returns a nested same-start pair; the first audit omits its decision."""

    def __init__(self, prompt: SemanticGlobalPromptBundle, counter: dict[str, int]) -> None:
        super().__init__(prompt, counter)
        self.payloads: list[tuple[str, dict[str, object]]] = []
        self.audit_repairs = 0

    def generate(
        self,
        *,
        subject_id: str,
        payload: dict[str, object],
        response_model: type[OutputModel],
        cancel_requested=lambda: False,
    ) -> StructuredCallResult[OutputModel]:
        self.payloads.append((response_model.__name__, payload))
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
        if response_model is ProfileGlobalAuditOutput:
            self.audit_repairs += 1
            assert any("cover every listed nested pair" in value for value in validation_errors)
            initial = ProfileGlobalReviewOutput.model_validate_json(
                json.dumps(payload["initial_global_review"])
            )
            outer = next(
                value for value in initial.reviews if value.candidate_id == "mini_lesson_lesson"
            )
            output = ProfileGlobalAuditOutput(
                profile=ClipProfile.MINI_LESSON,
                replacements=(
                    outer.model_copy(
                        update={
                            "review_status": CandidateDisposition.REJECTED,
                            "duplicate_of_candidate_id": "mini_inner",
                            "score": 60.0,
                            "review_reason": "Same objective; the inner unit is complete.",
                        }
                    ),
                ),
                nested_pair_decisions=(
                    NestedPairDecision(
                        outer_candidate_id="mini_lesson_lesson",
                        inner_candidate_id="mini_inner",
                        decision=NestedPairDecisionKind.DUPLICATE,
                        reason="Same objective; keep the shortest complete unit.",
                    ),
                ),
                audit_reason="Resolved the listed nested pair.",
            )
            return StructuredCallResult(
                output=cast(OutputModel, output), call_records=(), repaired=True
            )
        return super().repair(
            subject_id=subject_id,
            payload=payload,
            response_model=response_model,
            validation_errors=validation_errors,
            cancel_requested=cancel_requested,
        )

    def _output(
        self,
        payload: dict[str, object],
        response_model: type[OutputModel],
    ) -> OutputModel:
        output = super()._output(payload, response_model)
        if (
            response_model is ProfileDiscoveryOutput
            and payload.get("profile") == ClipProfile.MINI_LESSON.value
            and payload.get("discovery_pass") is None
        ):
            discovery = cast(ProfileDiscoveryOutput, output)
            if discovery.candidates:
                inner = discovery.candidates[0].model_copy(
                    update={
                        "candidate_id": "mini_inner",
                        "end_cue_id": 10,
                        "evidence_cue_ids": (1, 10),
                    }
                )
                return cast(
                    OutputModel,
                    discovery.model_copy(update={"candidates": (*discovery.candidates, inner)}),
                )
        return output


class AuditCreatedPairProvider(NestedPairProvider):
    """The inner candidate starts rejected; the audit promotes it, creating a nested pair."""

    def __init__(
        self,
        prompt: SemanticGlobalPromptBundle,
        counter: dict[str, int],
        *,
        decide_created_pair_on_repair: bool = True,
    ) -> None:
        super().__init__(prompt, counter)
        self.decide_created_pair_on_repair = decide_created_pair_on_repair

    def _audit(self, payload: dict[str, object], *, decide: bool) -> ProfileGlobalAuditOutput:
        initial = ProfileGlobalReviewOutput.model_validate_json(
            json.dumps(payload["initial_global_review"])
        )
        inner = next(value for value in initial.reviews if value.candidate_id == "mini_inner")
        return ProfileGlobalAuditOutput(
            profile=ClipProfile.MINI_LESSON,
            replacements=(
                inner.model_copy(
                    update={
                        "review_status": CandidateDisposition.MANUAL_REVIEW,
                        "score": 70.0,
                        "review_reason": "Distinct narrower objective worth review.",
                    }
                ),
            ),
            nested_pair_decisions=(
                (
                    NestedPairDecision(
                        outer_candidate_id="mini_lesson_lesson",
                        inner_candidate_id="mini_inner",
                        decision=NestedPairDecisionKind.DISTINCT_OBJECTIVE,
                        reason="Each answers its own question.",
                    ),
                )
                if decide
                else ()
            ),
            audit_reason="Promoted the narrower lesson.",
        )

    def _output(
        self,
        payload: dict[str, object],
        response_model: type[OutputModel],
    ) -> OutputModel:
        mini = payload.get("profile") == ClipProfile.MINI_LESSON.value
        if response_model is ProfileGlobalAuditOutput and mini:
            assert payload["nested_pairs"] == []
            return cast(OutputModel, self._audit(payload, decide=False))
        output = super()._output(payload, response_model)
        if response_model is ProfileGlobalReviewOutput and mini:
            review = cast(ProfileGlobalReviewOutput, output)
            return cast(
                OutputModel,
                review.model_copy(
                    update={
                        "reviews": tuple(
                            item.model_copy(
                                update={
                                    "review_status": CandidateDisposition.REJECTED,
                                    "score": 60.0,
                                }
                            )
                            if item.candidate_id == "mini_inner"
                            else item
                            for item in review.reviews
                        )
                    }
                ),
            )
        return output

    def repair(
        self,
        *,
        subject_id: str,
        payload: dict[str, object],
        response_model: type[OutputModel],
        validation_errors: tuple[str, ...],
        cancel_requested=lambda: False,
    ) -> StructuredCallResult[OutputModel]:
        if response_model is ProfileGlobalAuditOutput:
            self.audit_repairs += 1
            assert any("cover every listed nested pair" in value for value in validation_errors)
            return StructuredCallResult(
                output=cast(
                    OutputModel,
                    self._audit(payload, decide=self.decide_created_pair_on_repair),
                ),
                call_records=(),
                repaired=True,
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


def test_service_routes_rejections_from_the_risk_pass_structurally(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    counter: dict[str, int] = {}

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        return RiskRoutingProvider(prompt, counter)

    output_dir = tmp_path / "run"
    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=output_dir,
        provider_factory=factory,
        cache_dir=tmp_path / "cache",
        discovery_concurrency=2,
    )
    final = DualProfileFinalResult.model_validate_json(
        (output_dir / "final-validated.json").read_text(encoding="utf-8")
    )
    DualProfileRunManifest.model_validate_json(
        (output_dir / "run-manifest.json").read_text(encoding="utf-8")
    ).validate_against(final)
    assert final.routing_policy_version == DUAL_PROFILE_ROUTING_POLICY_VERSION
    mini = final.profiles[ClipProfile.MINI_LESSON]
    # Same risk_ prefix and same rejection, but only the record produced by the
    # dedicated risk-discovery pass is retained as blocked.
    assert [value.candidate_id for value in mini.blocked] == ["risk_from_pass"]
    assert mini.blocked[0].duplicate_of_candidate_id == "mini_lesson_lesson"
    assert mini.blocked[0].review_reason.startswith("Deterministic risk routing: ")
    assert [value.candidate_id for value in mini.rejected] == ["risk_lookalike"]
    assert mini.rejected[0].duplicate_of_candidate_id == "mini_lesson_lesson"
    assert [value.candidate_id for value in mini.selected] == ["mini_lesson_lesson"]
    assert mini.statistics.discovered == 3


def test_global_audit_must_decide_python_listed_nested_pairs(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    counter: dict[str, int] = {}
    providers: list[NestedPairProvider] = []

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        provider = NestedPairProvider(prompt, counter)
        providers.append(provider)
        return provider

    output_dir = tmp_path / "run"
    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=output_dir,
        provider_factory=factory,
        cache_dir=tmp_path / "cache",
        discovery_concurrency=2,
    )
    payloads = [item for provider in providers for item in provider.payloads]
    audit_payloads = [
        payload
        for name, payload in payloads
        if name == "ProfileGlobalAuditOutput" and payload["profile"] == "mini_lesson"
    ]
    assert audit_payloads[0]["nested_pairs"] == [
        {"outer_candidate_id": "mini_lesson_lesson", "inner_candidate_id": "mini_inner"}
    ]
    boundary_payloads = [
        payload for name, payload in payloads if name == "ProfileBoundaryReviewOutput"
    ]
    global_payloads = [payload for name, payload in payloads if name == "ProfileGlobalReviewOutput"]
    for payload in (*boundary_payloads, *global_payloads):
        for entry in cast(list[dict[str, object]], payload["candidates"]):
            assert entry["discovery_pass"] == "base"
    assert sum(provider.audit_repairs for provider in providers) == 1
    final = DualProfileFinalResult.model_validate_json(
        (output_dir / "final-validated.json").read_text(encoding="utf-8")
    )
    mini = final.profiles[ClipProfile.MINI_LESSON]
    assert [value.candidate_id for value in mini.selected] == ["mini_inner"]
    assert [value.candidate_id for value in mini.rejected] == ["mini_lesson_lesson"]
    assert mini.rejected[0].duplicate_of_candidate_id == "mini_inner"


def test_fresh_audit_must_decide_pairs_its_replacements_create(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    counter: dict[str, int] = {}
    providers: list[AuditCreatedPairProvider] = []

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        provider = AuditCreatedPairProvider(prompt, counter)
        providers.append(provider)
        return provider

    output_dir = tmp_path / "run"
    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=output_dir,
        provider_factory=factory,
        cache_dir=tmp_path / "cache",
        discovery_concurrency=2,
    )
    assert sum(provider.audit_repairs for provider in providers) == 1
    final = DualProfileFinalResult.model_validate_json(
        (output_dir / "final-validated.json").read_text(encoding="utf-8")
    )
    mini = final.profiles[ClipProfile.MINI_LESSON]
    assert [value.candidate_id for value in mini.manual_review] == ["mini_inner"]
    assert [value.candidate_id for value in mini.selected] == ["mini_lesson_lesson"]


def test_cached_audit_without_created_pair_decision_does_not_crash_a_warm_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from liveclip.services import dual_profile_evaluation as service

    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    cache = tmp_path / "cache"
    counter: dict[str, int] = {}

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        return AuditCreatedPairProvider(prompt, counter)

    # Simulate an audit output cached under the earlier contract, which only
    # required decisions for the pairs listed from the initial review.
    original_pairs = service.nested_candidate_pairs
    with monkeypatch.context() as patch:
        patch.setattr(
            service,
            "nested_candidate_pairs",
            lambda review: (
                ()
                if any(
                    item.candidate_id == "mini_inner"
                    and item.review_status == CandidateDisposition.MANUAL_REVIEW
                    for item in review.reviews
                )
                else original_pairs(review)
            ),
        )
        run_dual_profile_evaluation(
            transcript_path=transcript,
            output_dir=tmp_path / "first",
            provider_factory=factory,
            cache_dir=cache,
            discovery_concurrency=2,
        )
    generated = sum(counter.values())
    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=tmp_path / "warm",
        provider_factory=factory,
        cache_dir=cache,
        discovery_concurrency=2,
    )
    assert sum(counter.values()) == generated
    warm = DualProfileRunManifest.model_validate_json(
        (tmp_path / "warm" / "run-manifest.json").read_text(encoding="utf-8")
    )
    assert warm.calls == {
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


# Discovery-family prompt identities are frozen: a change would invalidate every
# cached Discovery call.  Review-stage prompts may evolve independently.
FROZEN_DISCOVERY_PROMPT_HASHES = {
    ("short_highlight", "discovery"): (
        "560083a53e4a04c9d8917c7efeed32849269141ece13df60a522e83ba0d3ef07"
    ),
    ("short_highlight", "coverage_audit"): (
        "5cf38c6d0cff076721437ecb88e64c3b37b7e942af9d7c7756d8c71220b2727d"
    ),
    ("mini_lesson", "discovery"): (
        "bd807b720db282447efc180dfec11f1aa2d94a173d8e4de2bb78b82cbc83b885"
    ),
    ("mini_lesson", "coverage_audit"): (
        "057f0a5bb3a3bdeb24c08dc44cd3f78e6c148742390475c226da4f3fcff091f3"
    ),
    ("mini_lesson", "precision_audit"): (
        "ef399dc6090a7f108a07cee47f858ab28d61b7f00e2d048583ca6cf05d8ec443"
    ),
    ("mini_lesson", "precision_confirmation"): (
        "3ccb77bc963fa0e906207c33a55297dc1245021e8c6e47ad26e1ee4e1a82c5aa"
    ),
    ("mini_lesson", "risk_discovery"): (
        "f136669d1b7560711c74e31b3ed3326cfab6c5df9e0c462d8acca5c12b03f3f9"
    ),
}


def test_discovery_prompt_identities_are_unchanged() -> None:
    for (profile, stage), expected in FROZEN_DISCOVERY_PROMPT_HASHES.items():
        assert load_dual_profile_prompt(stage, ClipProfile(profile)).sha256 == expected


def test_review_stage_prompts_route_by_structure_and_audit_nested_pairs() -> None:
    def text(stage: Any, profile: ClipProfile) -> str:
        return " ".join(load_dual_profile_prompt(stage, profile).instructions.split())

    for profile in ClipProfile:
        boundary = text("boundary_review", profile)
        review = text("global_review", profile)
        audit = text("global_audit", profile)
        assert "beginning with `risk_`" not in boundary
        assert "`discovery_pass` is `risk_discovery`" in boundary
        assert "only to meet duration" not in boundary
        assert "whether or not they are needed to reach the Profile minimum" in boundary
        assert "setup, not premises" in boundary
        for value in (boundary, review, audit):
            assert "meaning cannot be recovered from cues inside the interval" in value
            assert "is not a dependency" in value
            assert "immediate application or consequence of the same concept" in value
        assert "also remove `missing_required_prior_steps`" not in audit
        assert "Boundary Review quality flags are cumulative" in review
        assert "Boundary Review quality flags are cumulative" in audit
        assert "`nested_pair_decisions`" in audit
        assert "containment or a shared edge alone never establishes duplication" in audit
        assert "shortest independently complete candidate" in audit


def test_stage9_review_prompt_batch_is_general_and_consistent() -> None:
    def text(stage: Any, profile: ClipProfile) -> str:
        return " ".join(load_dual_profile_prompt(stage, profile).instructions.split())

    shared_label_rule = (
        "A number, nickname or ordinal attached to an item that the interval itself presents, "
        "contrasts or demonstrates is recoverable even if it was coined earlier, including when it "
        "appears only in the conclusion; do not flag it or extend the interval to its "
        "coinage. Flag a dependency only when the opening or the conclusion's instruction "
        "depends on a definition, sample, step or comparison half that the interval never "
        "presents"
    )
    for profile in ClipProfile:
        boundary = text("boundary_review", profile)
        review = text("global_review", profile)
        audit = text("global_audit", profile)
        for value in (boundary, review, audit):
            assert shared_label_rule in value
            assert "second half of a before/after comparison is context-dependent" in value
            assert "never resolves a dependency" in value
        # A: narrowed audio-note carve-out and device/playback trouble.
        assert "short device-distance statement" not in boundary
        assert "brief functional audio-position note" not in boundary
        assert "own brief remark about microphone distance or placement" in boundary
        assert "trouble playing back a recording are `device_or_waiting_padding`" in boundary
        assert "and also `material_interruption` when they split a demonstration" in boundary
        assert (
            "A reference to another video or post is setup when the kept interval defines and "
            "demonstrates its own method" in boundary
        )
        # C: live diagnosis boundaries come from transcribed cues.
        assert "starts at the first transcribed cue of the evaluated sample" in boundary
        assert "untranscribed gap holds audio" in boundary
        assert "a participant's own question about their voice" in boundary
        assert "starting at its first transcribed cue" in review
        # B2: the Profile minimum must be met by on-topic content.
        assert "The Profile minimum must be met by on-topic content" in boundary
        assert "at or under the Profile minimum, flag `padded_with_irrelevant_content`" in boundary
        assert "closing acknowledgement or address to the audience does not count" in boundary
        # Reviewer P2 wording.
        assert "(a `risk_discovery` record is retained as `blocked`)" in review
        assert "decide every nested pair your replacements create" in audit
        # Earlier asserted phrases are kept.
        assert "status, flags and reason must agree" in audit
        assert "setup, not premises" in boundary


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


def test_claude_cli_provider_and_model_reach_the_run_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    contract = f"claude-cli-editorial-v1.2.1.307.{'c' * 64}"
    monkeypatch.setattr(claude_cli_module, "resolve_claude_executable", lambda _value: "/fake")
    monkeypatch.setattr(claude_cli_module, "claude_cli_contract_version", lambda _value: contract)
    auth_checks: list[str] = []

    def subscription(value: str) -> claude_cli_module.ClaudeCliAuthStatus:
        auth_checks.append(value)
        return claude_cli_module.ClaudeCliAuthStatus(
            logged_in=True, auth_method="claude.ai", api_provider="firstParty"
        )

    monkeypatch.setattr(claude_cli_module, "require_claude_subscription", subscription)
    scripted = ScriptedDualProvider(
        load_dual_profile_prompt("discovery", ClipProfile.SHORT_HIGHLIGHT), {}
    )
    models: dict[str, type[BaseModel]] = {
        model.__name__: model
        for model in (
            ProfileDiscoveryOutput,
            ProfileBoundaryReviewOutput,
            ProfileGlobalReviewOutput,
            ProfileGlobalAuditOutput,
            CrossProfileVariantLinkOutput,
        )
    }
    efforts: list[str] = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        # Stand-in for the CLI: answer from the scripted Profile fixture.
        efforts.append(argv[argv.index("--effort") + 1])
        schema = json.loads(argv[argv.index("--json-schema") + 1])
        prompt = kwargs["stdin_stream"].read().decode()
        payload = json.loads(
            prompt.split("<untrusted_json>\n", 1)[1].rsplit("\n</untrusted_json>", 1)[0]
        )
        output = scripted._output(payload, models[schema["title"]])
        result = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "structured_output": output.model_dump(mode="json"),
            "num_turns": 2,
            "permission_denials": [],
            "usage": {"input_tokens": 3, "cache_read_input_tokens": 7, "output_tokens": 5},
            "modelUsage": {"claude-opus-5-5": {}},
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(result), "")

    monkeypatch.setattr(claude_cli_module, "run_cancellable_process", run)

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: Any):
        return ClaudeCliStructuredLLMProvider(
            prompts=prompt,
            model_name="claude-opus-5-5",
            claude_executable="claude",
            timeout_seconds=60,
            contract_version=contract,
            reasoning_effort=reasoning_effort,
        )

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
    calls = json.loads((output_dir / "provider-calls.json").read_text(encoding="utf-8"))["calls"]
    assert manifest.provider == "claude_cli"
    assert manifest.model == "claude-opus-5-5"
    assert manifest.input_tokens == 10 * len(calls)
    assert manifest.output_tokens == 5 * len(calls)
    assert calls
    assert {call["provider"] for call in calls} == {"claude_cli"}
    assert {call["model"] for call in calls} == {"claude-opus-5-5"}
    assert {call["request_count"] for call in calls} == {1}
    assert {"medium", "high"} <= set(efforts)
    # One subscription check per provider construction plus one per call.
    assert len(auth_checks) > len(efforts)
