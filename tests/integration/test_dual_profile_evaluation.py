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
    DualQualityFlag,
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
            assert payload["audit_pairs"] == []
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
    assert audit_payloads[0]["audit_pairs"] == [
        {
            "outer_candidate_id": "mini_lesson_lesson",
            "inner_candidate_id": "mini_inner",
            "pair_kind": "nested",
            "near_identical": False,
        }
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


def test_warm_rerun_after_a_fresh_audit_decided_a_created_pair(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    cache = tmp_path / "cache"
    counter: dict[str, int] = {}
    providers: list[AuditCreatedPairProvider] = []

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        provider = AuditCreatedPairProvider(prompt, counter)
        providers.append(provider)
        return provider

    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=tmp_path / "cold",
        provider_factory=factory,
        cache_dir=cache,
        discovery_concurrency=2,
    )
    # The cold audit was repaired once to decide the pair its replacement created.
    assert sum(provider.audit_repairs for provider in providers) == 1
    generated = sum(counter.values())
    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=tmp_path / "warm",
        provider_factory=factory,
        cache_dir=cache,
        discovery_concurrency=2,
    )
    assert sum(counter.values()) == generated
    assert sum(provider.audit_repairs for provider in providers) == 1
    warm = DualProfileRunManifest.model_validate_json(
        (tmp_path / "warm" / "run-manifest.json").read_text(encoding="utf-8")
    )
    assert warm.calls == {
        "discovery": 0,
        "boundary_review": 0,
        "global_review": 0,
        "variant_link": 0,
    }
    cold_final = (tmp_path / "cold" / "final-validated.json").read_text(encoding="utf-8")
    warm_final = (tmp_path / "warm" / "final-validated.json").read_text(encoding="utf-8")
    assert cold_final == warm_final


# Global Audit prompt hashes at 4f2c068, the last audit prompt before the
# created-pair rule.  Any audit cached without that rule carries one of these
# (or an older) identity and therefore can never be a cache hit now.
PRE_CREATED_PAIR_RULE_AUDIT_PROMPT_HASHES = {
    "mini_lesson": "ff7f2745be299b993820e377bb46c4cf45f8969a37fb3720d98a61a8590794d5",
    "short_highlight": "9c0b507b110b62977cafad0657cb2d2cc6ffc71f46410418c983a61e69b73e5a",
}


def _plant_stale_created_pair_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    counter: dict[str, int],
) -> tuple[Path, Path, dict[Path, bytes]]:
    """Plant an audit that omits the created-pair decision under the CURRENT prompt.

    This is impossible in practice (see the hashes above); it models a cache entry
    written under a weaker validation contract.
    """

    from liveclip.services import dual_profile_evaluation as service

    for profile, old_hash in PRE_CREATED_PAIR_RULE_AUDIT_PROMPT_HASHES.items():
        assert load_dual_profile_prompt("global_audit", ClipProfile(profile)).sha256 != old_hash

    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    cache = tmp_path / "cache"

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        return AuditCreatedPairProvider(prompt, counter)

    original_pairs = service.audit_candidate_pairs
    with monkeypatch.context() as patch:
        patch.setattr(
            service,
            "audit_candidate_pairs",
            lambda review, transcript: (
                ()
                if any(
                    item.candidate_id == "mini_inner"
                    and item.review_status == CandidateDisposition.MANUAL_REVIEW
                    for item in review.reviews
                )
                else original_pairs(review, transcript)
            ),
        )
        run_dual_profile_evaluation(
            transcript_path=transcript,
            output_dir=tmp_path / "planted",
            provider_factory=factory,
            cache_dir=cache,
            discovery_concurrency=2,
        )
    planted = {path: path.read_bytes() for path in cache.glob("*/global_audit/*.json")}
    assert planted
    return transcript, cache, planted


def test_cache_hit_audits_are_fully_validated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Negative control (Stage 9 contract, the default): a cache hit is re-validated
    # with the full rule and refused, failing closed rather than being accepted
    # under a weaker contract or silently refreshed.
    counter: dict[str, int] = {}
    transcript, cache, planted = _plant_stale_created_pair_audit(tmp_path, monkeypatch, counter)

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        return AuditCreatedPairProvider(prompt, counter)

    with pytest.raises(ValueError, match="cover every listed nested pair"):
        run_dual_profile_evaluation(
            transcript_path=transcript,
            output_dir=tmp_path / "warm",
            provider_factory=factory,
            cache_dir=cache,
            discovery_concurrency=2,
        )
    assert {path: path.read_bytes() for path in planted} == planted
    assert set(cache.glob("*/global_audit/*.json")) == set(planted)


def test_opt_in_stale_cache_refresh_repairs_once_and_reuses_the_superseding_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter: dict[str, int] = {}
    transcript, cache, planted = _plant_stale_created_pair_audit(tmp_path, monkeypatch, counter)
    providers: list[AuditCreatedPairProvider] = []

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        provider = AuditCreatedPairProvider(prompt, counter)
        providers.append(provider)
        return provider

    def run(name: str) -> DualProfileRunManifest:
        run_dual_profile_evaluation(
            transcript_path=transcript,
            output_dir=tmp_path / name,
            provider_factory=factory,
            cache_dir=cache,
            discovery_concurrency=2,
            refresh_stale_cache=True,
        )
        return DualProfileRunManifest.model_validate_json(
            (tmp_path / name / "run-manifest.json").read_text(encoding="utf-8")
        )

    warm = run("warm")
    # The stale audit was refused and repaired once (the repair asserts the "cover
    # every listed nested pair" error); the planted entry stays byte-identical.
    assert sum(provider.audit_repairs for provider in providers) == 1
    assert {path: path.read_bytes() for path in planted} == planted
    final = DualProfileFinalResult.model_validate_json(
        (tmp_path / "warm" / "final-validated.json").read_text(encoding="utf-8")
    )
    assert [
        value.candidate_id for value in final.profiles[ClipProfile.MINI_LESSON].manual_review
    ] == ["mini_inner"]
    # The resolution is visible in the run artifacts, not only in cache files.
    assert warm.stale_cache_refresh_enabled is True
    assert warm.stale_cache_resolution_count == 1
    (resolution,) = warm.stale_cache_resolutions
    assert (resolution.stage, resolution.profile) == ("global_audit", "mini_lesson")
    assert resolution.cache_key in {path.stem for path in planted}
    assert "cover every listed nested pair" in resolution.error_summary
    assert resolution.reused is False
    superseding = (
        cache / "mini_lesson" / "global_audit" / f"{resolution.superseding_cache_key}.json"
    )
    assert (
        "supersedes_cache_output_sha256"
        in json.loads(superseding.read_text("utf-8"))["model_settings"]
    )
    assert warm.calls["global_review"] == 1

    # A third run reuses the superseding audit entry with zero calls.
    generated = dict(counter)
    third = run("third")
    assert counter == generated
    assert sum(provider.audit_repairs for provider in providers) == 1
    assert set(third.calls.values()) == {0}
    (reused,) = third.stale_cache_resolutions
    assert reused.reused is True
    assert reused.superseding_cache_key == resolution.superseding_cache_key
    assert {path: path.read_bytes() for path in planted} == planted

    # Without the option the stale primary entry still fails closed.
    with pytest.raises(ValueError, match="cover every listed nested pair"):
        run_dual_profile_evaluation(
            transcript_path=transcript,
            output_dir=tmp_path / "default",
            provider_factory=factory,
            cache_dir=cache,
            discovery_concurrency=2,
        )


class OpeningFlagBoundaryProvider(ScriptedDualProvider):
    """Boundary Review keeps `context_dependent_opening` with `opening_complete=true`.

    Its repair (or a later honest answer) sets `opening_complete=false`. Global
    Review routes a candidate with any merged flag to `manual_review`.
    """

    def __init__(self, prompt: SemanticGlobalPromptBundle, counter: dict[str, int]) -> None:
        super().__init__(prompt, counter)
        self.boundary_repairs: list[tuple[str, ...]] = []

    def _boundary(self, payload: dict[str, object], *, opening_complete: bool) -> Any:
        output = cast(
            ProfileBoundaryReviewOutput,
            super()._output(payload, ProfileBoundaryReviewOutput),
        )
        return output.model_copy(
            update={
                "reviews": tuple(
                    item.model_copy(
                        update={
                            "opening_complete": opening_complete,
                            "quality_flags": (DualQualityFlag.CONTEXT_DEPENDENT_OPENING,),
                        }
                    )
                    for item in output.reviews
                )
            }
        )

    def _output(self, payload: dict[str, object], response_model: type[OutputModel]) -> OutputModel:
        if response_model is ProfileBoundaryReviewOutput:
            return cast(OutputModel, self._boundary(payload, opening_complete=True))
        output = super()._output(payload, response_model)
        if response_model is ProfileGlobalReviewOutput:
            review = cast(ProfileGlobalReviewOutput, output)
            return cast(
                OutputModel,
                review.model_copy(
                    update={
                        "reviews": tuple(
                            item.model_copy(
                                update={
                                    "review_status": CandidateDisposition.MANUAL_REVIEW,
                                    "score": 70.0,
                                    "review_reason": (
                                        "Coherent; disagrees with the advisory opening flag."
                                    ),
                                }
                            )
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
        if response_model is ProfileBoundaryReviewOutput:
            self.boundary_repairs.append(validation_errors)
            return StructuredCallResult(
                output=cast(OutputModel, self._boundary(payload, opening_complete=False)),
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


def _opening_flag_factory(counter: dict[str, int], providers: list[OpeningFlagBoundaryProvider]):
    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        provider = OpeningFlagBoundaryProvider(prompt, counter)
        providers.append(provider)
        return provider

    return factory


def test_boundary_opening_flag_invariant_is_repaired_not_fatal(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    counter: dict[str, int] = {}
    providers: list[OpeningFlagBoundaryProvider] = []
    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=tmp_path / "output",
        provider_factory=_opening_flag_factory(counter, providers),
        discovery_concurrency=1,
    )
    repairs = [errors for provider in providers for errors in provider.boundary_repairs]
    # One Boundary Review chunk per Profile, each repaired once through the existing path.
    assert len(repairs) == len(ClipProfile)
    assert all(
        "context_dependent_opening requires opening_complete=false" in errors[0]
        for errors in repairs
    )
    final = DualProfileFinalResult.model_validate_json(
        (tmp_path / "output" / "final-validated.json").read_text(encoding="utf-8")
    )
    for result in final.profiles.values():
        # Advisory-only flag: the coherent candidate stays reviewable, not blocked.
        assert [value.review_status for value in result.manual_review] == [
            CandidateDisposition.MANUAL_REVIEW
        ]
        assert result.blocked == ()


def test_cached_boundary_review_violating_the_invariant_is_repaired_not_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from liveclip.services import dual_profile_evaluation as service

    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    cache = tmp_path / "cache"
    counter: dict[str, int] = {}
    providers: list[OpeningFlagBoundaryProvider] = []
    factory = _opening_flag_factory(counter, providers)

    # Plant Boundary Review cache entries written under a validator without the
    # invariant (as a pre-invariant cache under an unchanged prompt would be).
    original = service.validate_boundary_review_output

    def lenient(output, **kwargs):
        relaxed = output.model_copy(
            update={
                "reviews": tuple(
                    item.model_copy(update={"opening_complete": False}) for item in output.reviews
                )
            }
        )
        original(relaxed, **kwargs)
        return output

    with monkeypatch.context() as patch:
        patch.setattr(service, "validate_boundary_review_output", lenient)
        run_dual_profile_evaluation(
            transcript_path=transcript,
            output_dir=tmp_path / "planted",
            provider_factory=factory,
            cache_dir=cache,
            discovery_concurrency=1,
        )
    assert not any(provider.boundary_repairs for provider in providers)
    planted = {path: path.read_bytes() for path in sorted(cache.glob("*/boundary_review/*.json"))}
    assert len(planted) == len(ClipProfile)

    # By default (Stage 9 contract) the violating cached entry fails the run closed.
    with pytest.raises(ValueError, match="context_dependent_opening requires"):
        run_dual_profile_evaluation(
            transcript_path=transcript,
            output_dir=tmp_path / "default",
            provider_factory=factory,
            cache_dir=cache,
            discovery_concurrency=1,
        )
    assert not any(provider.boundary_repairs for provider in providers)

    # With the explicit option the warm run re-validates each cached Boundary
    # Review, refuses it and sends it through the existing repair path.
    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=tmp_path / "warm",
        provider_factory=factory,
        cache_dir=cache,
        discovery_concurrency=1,
        refresh_stale_cache=True,
    )
    repairs = [errors for provider in providers for errors in provider.boundary_repairs]
    assert len(repairs) == len(ClipProfile)
    warm = DualProfileRunManifest.model_validate_json(
        (tmp_path / "warm" / "run-manifest.json").read_text(encoding="utf-8")
    )
    assert warm.calls["discovery"] == 0
    assert warm.calls["boundary_review"] == len(ClipProfile)
    assert warm.stale_cache_resolution_count == len(ClipProfile)
    assert {value.stage for value in warm.stale_cache_resolutions} == {"boundary_review"}
    assert {value.profile for value in warm.stale_cache_resolutions} == {
        profile.value for profile in ClipProfile
    }
    assert not any(value.reused for value in warm.stale_cache_resolutions)
    assert {value.cache_key for value in warm.stale_cache_resolutions} == {
        path.stem for path in planted
    }
    # Cache entries are immutable evidence: the stale entry is untouched and the
    # repaired output is stored under a key bound to the stale output's bytes.
    assert {path: path.read_bytes() for path in planted} == planted
    boundary_files = sorted(cache.glob("*/boundary_review/*.json"))
    assert len(boundary_files) == 2 * len(ClipProfile)
    superseding = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in boundary_files
        if path not in planted
    ]
    assert all("supersedes_cache_output_sha256" in value["model_settings"] for value in superseding)
    assert all(
        not item["opening_complete"] for value in superseding for item in value["output"]["reviews"]
    )

    # A third run resolves every stage from the cache, including the repaired entry.
    generated = dict(counter)
    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=tmp_path / "third",
        provider_factory=factory,
        cache_dir=cache,
        discovery_concurrency=1,
        refresh_stale_cache=True,
    )
    assert counter == generated
    assert len([errors for provider in providers for errors in provider.boundary_repairs]) == len(
        ClipProfile
    )
    third = DualProfileRunManifest.model_validate_json(
        (tmp_path / "third" / "run-manifest.json").read_text(encoding="utf-8")
    )
    assert set(third.calls.values()) == {0}
    assert third.stale_cache_resolution_count == len(ClipProfile)
    assert all(value.reused for value in third.stale_cache_resolutions)


class StubbornOpeningFlagProvider(OpeningFlagBoundaryProvider):
    """Repair and regeneration keep violating the opening invariant."""

    def __init__(
        self,
        prompt: SemanticGlobalPromptBundle,
        counter: dict[str, int],
        *,
        also_break_evidence: bool = False,
    ) -> None:
        super().__init__(prompt, counter)
        self.also_break_evidence = also_break_evidence

    def _boundary(self, payload: dict[str, object], *, opening_complete: bool) -> Any:
        del opening_complete
        output = super()._boundary(payload, opening_complete=True)
        if not self.also_break_evidence:
            return output
        return output.model_copy(
            update={
                "reviews": tuple(
                    item.model_copy(update={"evidence_cue_ids": (item.end_cue_id + 1,)})
                    for item in output.reviews
                )
            }
        )


def test_exhausted_opening_invariant_alone_falls_back_conservatively(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    counter: dict[str, int] = {}
    providers: list[StubbornOpeningFlagProvider] = []

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        provider = StubbornOpeningFlagProvider(prompt, counter)
        providers.append(provider)
        return provider

    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=tmp_path / "output",
        provider_factory=factory,
        discovery_concurrency=1,
    )
    # One repair per chunk, then one regeneration, then the deterministic fallback.
    assert len([e for p in providers for e in p.boundary_repairs]) == len(ClipProfile)
    manifest = DualProfileRunManifest.model_validate_json(
        (tmp_path / "output" / "run-manifest.json").read_text(encoding="utf-8")
    )
    assert {value.profile for value in manifest.boundary_opening_fallbacks} == set(ClipProfile)
    assert sorted(
        candidate_id
        for value in manifest.boundary_opening_fallbacks
        for candidate_id in value.candidate_ids
    ) == sorted(f"{profile.value}_lesson" for profile in ClipProfile)
    assert manifest.stale_cache_resolutions == ()
    boundary = json.loads((tmp_path / "output" / "boundary-review.json").read_text("utf-8"))
    for profile_output in boundary["profiles"].values():
        for item in profile_output["reviews"]:
            # Only downgraded: the flag stays and the opening is marked incomplete.
            assert item["opening_complete"] is False
            assert item["quality_flags"] == ["context_dependent_opening"]
    final = DualProfileFinalResult.model_validate_json(
        (tmp_path / "output" / "final-validated.json").read_text(encoding="utf-8")
    )
    for result in final.profiles.values():
        assert result.selected == ()


def test_opening_fallback_never_masks_another_validation_failure(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    counter: dict[str, int] = {}

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        return StubbornOpeningFlagProvider(prompt, counter, also_break_evidence=True)

    with pytest.raises(ValueError, match="evidence lies outside its final interval"):
        run_dual_profile_evaluation(
            transcript_path=transcript,
            output_dir=tmp_path / "output",
            provider_factory=factory,
            discovery_concurrency=1,
        )


class NoCallProvider(ScriptedDualProvider):
    """Any model call fails the test: a warm rerun must be served from the cache."""

    def generate(self, **kwargs: Any) -> Any:
        raise AssertionError(f"unexpected model call: {kwargs['subject_id']}")

    def repair(self, **kwargs: Any) -> Any:
        raise AssertionError(f"unexpected model repair: {kwargs['subject_id']}")


def _no_call_factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
    del reasoning_effort
    return NoCallProvider(prompt, {})


def _stubborn_cold_run(tmp_path: Path) -> tuple[Path, Path, DualProfileRunManifest]:
    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    cache = tmp_path / "cache"
    counter: dict[str, int] = {}

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        return StubbornOpeningFlagProvider(prompt, counter)

    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=tmp_path / "cold",
        provider_factory=factory,
        cache_dir=cache,
        discovery_concurrency=1,
    )
    cold = DualProfileRunManifest.model_validate_json(
        (tmp_path / "cold" / "run-manifest.json").read_text(encoding="utf-8")
    )
    return transcript, cache, cold


@pytest.mark.parametrize("refresh", [False, True])
def test_opening_fallback_round_trips_through_the_cache(tmp_path: Path, refresh: bool) -> None:
    transcript, cache, cold = _stubborn_cold_run(tmp_path)
    assert {value.profile for value in cold.boundary_opening_fallbacks} == set(ClipProfile)
    # The cache keeps only the raw model output; a marker names the downgraded rows.
    boundary_files = sorted(cache.glob("*/boundary_review/*.json"))
    assert len(boundary_files) == len(ClipProfile)
    for path in boundary_files:
        entry = json.loads(path.read_text(encoding="utf-8"))
        assert all(item["opening_complete"] for item in entry["output"]["reviews"])
        assert entry["conservative_fallback"] == {
            "stage": "boundary_review",
            "candidate_ids": [f"{entry['profile']}_lesson"],
        }
        assert "supersedes_cache_output_sha256" not in entry["model_settings"]
    # Ordinary entries are written exactly as before (no marker field).
    others = [path for path in cache.glob("*/*/*.json") if path not in boundary_files]
    assert others
    assert not any(
        "conservative_fallback" in json.loads(path.read_text("utf-8")) for path in others
    )
    before = {path: path.read_bytes() for path in cache.glob("*/*/*.json")}

    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=tmp_path / "warm",
        provider_factory=_no_call_factory,
        cache_dir=cache,
        discovery_concurrency=1,
        refresh_stale_cache=refresh,
    )
    warm = DualProfileRunManifest.model_validate_json(
        (tmp_path / "warm" / "run-manifest.json").read_text(encoding="utf-8")
    )
    assert set(warm.calls.values()) == {0}
    assert warm.boundary_opening_fallbacks == cold.boundary_opening_fallbacks
    assert warm.stale_cache_resolutions == ()
    for name in ("final-validated.json", "boundary-review.json", "global-review.json"):
        assert (tmp_path / "warm" / name).read_bytes() == (tmp_path / "cold" / name).read_bytes()
    assert {path: path.read_bytes() for path in cache.glob("*/*/*.json")} == before


@pytest.mark.parametrize("refresh", [False, True])
@pytest.mark.parametrize(
    "tamper",
    ["wrong_ids", "wrong_stage", "extra_key", "not_a_mapping", "valid_output"],
)
def test_tampered_fallback_marker_fails_closed(tmp_path: Path, refresh: bool, tamper: str) -> None:
    transcript, cache, _ = _stubborn_cold_run(tmp_path)
    path = sorted(cache.glob("short_highlight/boundary_review/*.json"))[0]
    entry = json.loads(path.read_text(encoding="utf-8"))
    marker = entry["conservative_fallback"]
    if tamper == "wrong_ids":
        marker["candidate_ids"] = ["someone_else"]
    elif tamper == "wrong_stage":
        marker["stage"] = "global_review"
    elif tamper == "extra_key":
        marker["note"] = "x"
    elif tamper == "not_a_mapping":
        entry["conservative_fallback"] = ["short_highlight_lesson"]
    else:
        # A marker on an output that already validates is not a fallback entry.
        for item in entry["output"]["reviews"]:
            item["opening_complete"] = False
    path.chmod(0o600)
    path.write_text(json.dumps(entry), encoding="utf-8")
    with pytest.raises(ValueError, match="fallback marker is invalid"):
        run_dual_profile_evaluation(
            transcript_path=transcript,
            output_dir=tmp_path / "warm",
            provider_factory=_no_call_factory,
            cache_dir=cache,
            discovery_concurrency=1,
            refresh_stale_cache=refresh,
        )


def _scripted_cold_cache(tmp_path: Path) -> tuple[Path, Path]:
    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)
    cache = tmp_path / "cache"

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        return ScriptedDualProvider(prompt, {})

    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=tmp_path / "cold",
        provider_factory=factory,
        cache_dir=cache,
        discovery_concurrency=1,
    )
    return transcript, cache


def _corrupt_cache_entry(path: Path, corruption: str) -> None:
    original = path.read_text(encoding="utf-8")
    path.chmod(0o600)
    if corruption == "mis_keyed":
        entry = json.loads(original)
        entry["cache_key"] = "0" * 64
        path.write_text(json.dumps(entry), encoding="utf-8")
    elif corruption == "garbage_json":
        path.write_text("{not json", encoding="utf-8")
    else:
        target = path.with_name("symlink-target.txt")
        target.write_text(original, encoding="utf-8")
        path.unlink()
        path.symlink_to(target)


@pytest.mark.parametrize("refresh", [False, True])
@pytest.mark.parametrize("corruption", ["mis_keyed", "garbage_json", "symlink"])
@pytest.mark.parametrize("stage", ["discovery", "boundary_review", "global_audit"])
def test_untrusted_dual_profile_cache_entries_always_raise(
    tmp_path: Path, refresh: bool, corruption: str, stage: str
) -> None:
    transcript, cache = _scripted_cold_cache(tmp_path)
    path = sorted(cache.glob(f"short_highlight/{stage}/*.json"))[0]
    _corrupt_cache_entry(path, corruption)
    expected = "identity is invalid" if corruption == "mis_keyed" else "is not trusted"
    with pytest.raises(ValueError, match=expected):
        run_dual_profile_evaluation(
            transcript_path=transcript,
            output_dir=tmp_path / "warm",
            provider_factory=_no_call_factory,
            cache_dir=cache,
            discovery_concurrency=1,
            refresh_stale_cache=refresh,
        )


@pytest.mark.parametrize("corruption", ["mis_keyed", "garbage_json", "symlink"])
def test_untrusted_superseding_entry_raises_and_is_never_recorded_as_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    from liveclip.services import dual_profile_evaluation as service

    counter: dict[str, int] = {}
    transcript, cache, planted = _plant_stale_created_pair_audit(tmp_path, monkeypatch, counter)

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        return AuditCreatedPairProvider(prompt, counter)

    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=tmp_path / "refresh",
        provider_factory=factory,
        cache_dir=cache,
        discovery_concurrency=2,
        refresh_stale_cache=True,
    )
    (superseding,) = set(cache.glob("*/global_audit/*.json")) - set(planted)
    _corrupt_cache_entry(superseding, corruption)
    recorded: list[bool] = []
    original_record = service._ResolutionAudit.record_stale

    def spy(self: Any, *args: Any, reused: bool) -> None:
        recorded.append(reused)
        original_record(self, *args, reused=reused)

    monkeypatch.setattr(service._ResolutionAudit, "record_stale", spy)
    expected = "identity is invalid" if corruption == "mis_keyed" else "is not trusted"
    with pytest.raises(ValueError, match=expected):
        run_dual_profile_evaluation(
            transcript_path=transcript,
            output_dir=tmp_path / "third",
            provider_factory=_no_call_factory,
            cache_dir=cache,
            discovery_concurrency=2,
            refresh_stale_cache=True,
        )
    assert True not in recorded


class DiscoveryFlagProvider(ScriptedDualProvider):
    """Base Discovery flags a gated issue; Boundary Review silently clears it.

    ``trim`` makes Boundary Review move the mini candidate's start one cue later.
    """

    def __init__(
        self, prompt: SemanticGlobalPromptBundle, counter: dict[str, int], *, trim: bool
    ) -> None:
        super().__init__(prompt, counter)
        self.trim = trim

    def _output(self, payload: dict[str, object], response_model: type[OutputModel]) -> OutputModel:
        output = super()._output(payload, response_model)
        if response_model is ProfileDiscoveryOutput and payload.get("discovery_pass") is None:
            discovery = cast(ProfileDiscoveryOutput, output)
            return cast(
                OutputModel,
                discovery.model_copy(
                    update={
                        "candidates": tuple(
                            value.model_copy(
                                update={"quality_flags": (DualQualityFlag.TOPIC_SWITCH_INSIDE,)}
                            )
                            for value in discovery.candidates
                        )
                    }
                ),
            )
        if (
            self.trim
            and response_model in {ProfileBoundaryReviewOutput, ProfileGlobalReviewOutput}
            and payload.get("profile") == ClipProfile.MINI_LESSON.value
        ):
            reviews = cast(Any, output).reviews
            return cast(
                OutputModel,
                cast(Any, output).model_copy(
                    update={
                        "reviews": tuple(
                            item.model_copy(update={"start_cue_id": 2, "evidence_cue_ids": (2, 11)})
                            for item in reviews
                        )
                    }
                ),
            )
        return output


@pytest.mark.parametrize("trim", [False, True])
def test_service_persists_discovery_gated_flags_unless_boundary_review_trims(
    tmp_path: Path, trim: bool
) -> None:
    transcript = tmp_path / "transcript.srt"
    _write_srt(transcript)

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        return DiscoveryFlagProvider(prompt, {}, trim=trim)

    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=tmp_path / "run",
        provider_factory=factory,
        discovery_concurrency=1,
    )
    final = DualProfileFinalResult.model_validate_json(
        (tmp_path / "run" / "final-validated.json").read_text(encoding="utf-8")
    )
    assert final.routing_policy_version == "quality-gate-risk-routing-v4"
    short = final.profiles[ClipProfile.SHORT_HIGHLIGHT]
    mini = final.profiles[ClipProfile.MINI_LESSON]
    # Short: unchanged interval, so the Discovery flag cleared by review still gates.
    assert short.selected == ()
    (blocked,) = short.blocked
    assert DualQualityFlag.TOPIC_SWITCH_INSIDE in blocked.quality_flags
    assert blocked.review_reason.startswith("Deterministic flag persistence: ")
    if trim:
        # A trimmed start lets Boundary Review resolve the Discovery flag.
        assert [value.candidate_id for value in mini.selected] == ["mini_lesson_lesson"]
        assert mini.selected[0].quality_flags == ()
    else:
        assert mini.selected == ()
        assert [value.candidate_id for value in mini.blocked] == ["mini_lesson_lesson"]


class OverlapPairProvider(ScriptedDualProvider):
    """Mini Discovery adds a non-nested candidate that overlaps the base lesson.

    The base mini lesson spans cues 1-11 ([0 s, 110 s)). ``overlap_start`` cue 2
    gives [10 s, 120 s) (100 of 110 s shared: near-identical); cue 3 gives
    [20 s, 130 s) (90 of 110 s: an ordinary overlap). The first audit decides no
    pair (``first_audit="omit"``) or keeps both as distinct objectives
    (``first_audit="distinct"``); its repair applies ``repair_audit``.
    """

    def __init__(
        self,
        prompt: SemanticGlobalPromptBundle,
        counter: dict[str, int],
        *,
        overlap_start: int,
        first_audit: str,
        repair_audit: str,
        prompt_sha256: str | None = None,
        flag_lesson: bool = False,
    ) -> None:
        super().__init__(prompt, counter)
        self.flag_lesson = flag_lesson
        self.overlap_start = overlap_start
        self.first_audit = first_audit
        self.repair_audit = repair_audit
        self._prompt_override = prompt_sha256
        self.audit_payloads: list[dict[str, object]] = []
        self.audit_repairs: list[tuple[str, ...]] = []

    @property
    def prompt_sha256(self) -> str:
        return self._prompt_override or super().prompt_sha256

    def _audit(self, payload: dict[str, object], mode: str) -> ProfileGlobalAuditOutput:
        profile = ClipProfile(str(payload["profile"]))
        pairs = cast(list[dict[str, object]], payload["audit_pairs"])
        initial = ProfileGlobalReviewOutput.model_validate_json(
            json.dumps(payload["initial_global_review"])
        )
        replacements: tuple[GlobalReviewItem, ...] = ()
        by_id = {value.candidate_id: value for value in initial.reviews}

        def duplicate(removed: str, representative: str) -> GlobalReviewItem:
            return by_id[removed].model_copy(
                update={
                    "review_status": CandidateDisposition.REJECTED,
                    "duplicate_of_candidate_id": representative,
                    "score": 60.0,
                    "review_reason": "Same objective; keep one representative.",
                }
            )

        if mode == "duplicate":
            replacements = (duplicate("mini_lesson_lesson", "mini_overlap"),)
        elif mode == "keep_lesson":
            replacements = (duplicate("mini_overlap", "mini_lesson_lesson"),)
        elif mode == "prefixed":
            replacements = (
                by_id["mini_lesson_lesson"].model_copy(
                    update={"review_reason": "Deterministic audit fallback: model-written."}
                ),
            )
        elif mode == "dup_blocked_rep":
            replacements = (
                duplicate("mini_lesson_lesson", "mini_overlap"),
                by_id["mini_overlap"].model_copy(
                    update={
                        "review_status": CandidateDisposition.BLOCKED,
                        "score": 60.0,
                        "review_reason": "Blocked on its own merits.",
                    }
                ),
            )
        decisions = (
            ()
            if mode == "omit"
            else tuple(
                NestedPairDecision(
                    outer_candidate_id=str(pair["outer_candidate_id"]),
                    inner_candidate_id=str(pair["inner_candidate_id"]),
                    decision=(
                        NestedPairDecisionKind.DUPLICATE
                        if mode in {"duplicate", "keep_lesson", "dup_blocked_rep"}
                        else NestedPairDecisionKind.DISTINCT_OBJECTIVE
                    ),
                    reason="Decided on content.",
                )
                for pair in pairs
            )
        )
        return ProfileGlobalAuditOutput(
            profile=profile,
            replacements=replacements,
            nested_pair_decisions=decisions,
            audit_reason="Overlap audit.",
        )

    def _output(self, payload: dict[str, object], response_model: type[OutputModel]) -> OutputModel:
        mini = payload.get("profile") == ClipProfile.MINI_LESSON.value
        if response_model is ProfileGlobalAuditOutput and mini:
            self.audit_payloads.append(payload)
            return cast(OutputModel, self._audit(payload, self.first_audit))
        output = super()._output(payload, response_model)
        if (
            response_model is ProfileDiscoveryOutput
            and mini
            and payload.get("discovery_pass") is None
        ):
            discovery = cast(ProfileDiscoveryOutput, output)
            if discovery.candidates:
                if self.flag_lesson:
                    discovery = discovery.model_copy(
                        update={
                            "candidates": tuple(
                                value.model_copy(
                                    update={"quality_flags": (DualQualityFlag.TOPIC_SWITCH_INSIDE,)}
                                )
                                for value in discovery.candidates
                            )
                        }
                    )
                end = self.overlap_start + 10
                overlap = discovery.candidates[0].model_copy(
                    update={
                        "candidate_id": "mini_overlap",
                        "start_cue_id": self.overlap_start,
                        "end_cue_id": end,
                        "evidence_cue_ids": (self.overlap_start, end),
                        "quality_flags": (),
                    }
                )
                return cast(
                    OutputModel,
                    discovery.model_copy(update={"candidates": (*discovery.candidates, overlap)}),
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
            self.audit_repairs.append(validation_errors)
            return StructuredCallResult(
                output=cast(OutputModel, self._audit(payload, self.repair_audit)),
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


def _overlap_run(
    tmp_path: Path,
    name: str,
    *,
    overlap_start: int,
    first_audit: str,
    repair_audit: str,
    cache: Path | None = None,
    audit_prompt_overrides: dict[str, str] | None = None,
    counter: dict[str, int] | None = None,
    flag_lesson: bool = False,
    refresh_stale_cache: bool = False,
    no_calls: bool = False,
) -> tuple[list[OverlapPairProvider], DualProfileFinalResult]:
    transcript = tmp_path / "transcript.srt"
    if not transcript.exists():
        _write_srt(transcript)
    providers: list[OverlapPairProvider] = []
    shared_counter = counter if counter is not None else {}

    def factory(prompt: SemanticGlobalPromptBundle, reasoning_effort: str):
        del reasoning_effort
        override = (audit_prompt_overrides or {}).get(prompt.sha256)
        provider = OverlapPairProvider(
            prompt,
            shared_counter,
            overlap_start=overlap_start,
            first_audit=first_audit,
            repair_audit=repair_audit,
            prompt_sha256=override,
            flag_lesson=flag_lesson,
        )
        providers.append(provider)
        if no_calls:
            return NoCallProvider(prompt, {})
        return provider

    run_dual_profile_evaluation(
        transcript_path=transcript,
        output_dir=tmp_path / name,
        provider_factory=factory,
        cache_dir=cache,
        discovery_concurrency=1,
        refresh_stale_cache=refresh_stale_cache,
    )
    final = DualProfileFinalResult.model_validate_json(
        (tmp_path / name / "final-validated.json").read_text(encoding="utf-8")
    )
    return providers, final


def test_global_audit_must_decide_overlap_pairs(tmp_path: Path) -> None:
    providers, final = _overlap_run(
        tmp_path, "run", overlap_start=3, first_audit="omit", repair_audit="distinct"
    )
    (payload,) = [value for provider in providers for value in provider.audit_payloads]
    assert payload["audit_pairs"] == [
        {
            "outer_candidate_id": "mini_lesson_lesson",
            "inner_candidate_id": "mini_overlap",
            "pair_kind": "overlap",
            "near_identical": False,
        }
    ]
    (errors,) = [value for provider in providers for value in provider.audit_repairs]
    assert "cover every listed nested pair" in errors[0]
    # An ordinary overlap may keep both as distinct objectives.
    mini = final.profiles[ClipProfile.MINI_LESSON]
    assert {value.candidate_id for value in mini.selected} == {"mini_lesson_lesson", "mini_overlap"}


def test_near_identical_overlap_pair_cannot_keep_both(tmp_path: Path) -> None:
    providers, final = _overlap_run(
        tmp_path, "run", overlap_start=2, first_audit="distinct", repair_audit="duplicate"
    )
    (payload,) = [value for provider in providers for value in provider.audit_payloads]
    (pair,) = cast(list[dict[str, object]], payload["audit_pairs"])
    assert (pair["pair_kind"], pair["near_identical"]) == ("overlap", True)
    (errors,) = [value for provider in providers for value in provider.audit_repairs]
    assert "cannot keep both candidates" in errors[0]
    mini = final.profiles[ClipProfile.MINI_LESSON]
    assert [value.candidate_id for value in mini.selected] == ["mini_overlap"]
    assert [value.candidate_id for value in mini.rejected] == ["mini_lesson_lesson"]
    assert mini.rejected[0].duplicate_of_candidate_id == "mini_overlap"


# Global Audit prompt hashes at a7088c4 (Stage 12b), before overlap pairs.
PRE_OVERLAP_AUDIT_PROMPT_HASHES = {
    "mini_lesson": "cb115e0306315ec87c9e76bc7a6d73cd568aa4783fcc77dcbf8ce040c8e7a35d",
    "short_highlight": "746b625e589b3a6a555ca34b425ebc25916fdaea8f10b264d37570dd5c6f6d32",
}


def test_cached_audit_without_overlap_decisions_misses_under_the_new_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from liveclip.services import dual_profile_evaluation as service

    for profile, old_hash in PRE_OVERLAP_AUDIT_PROMPT_HASHES.items():
        assert load_dual_profile_prompt("global_audit", ClipProfile(profile)).sha256 != old_hash
    cache = tmp_path / "cache"
    nested_only = service.audit_candidate_pairs

    def old_contract(review: Any, transcript: Any) -> Any:
        return tuple(pair for pair in nested_only(review, transcript) if pair.pair_kind == "nested")

    counter: dict[str, int] = {}
    # An audit written by the pre-overlap contract: no overlap pair was listed or
    # decided, under the old audit prompt identity.
    with monkeypatch.context() as patch:
        patch.setattr(service, "audit_candidate_pairs", old_contract)
        _overlap_run(
            tmp_path,
            "old",
            overlap_start=2,
            first_audit="distinct",
            repair_audit="distinct",
            cache=cache,
            audit_prompt_overrides={
                load_dual_profile_prompt("global_audit", ClipProfile(profile)).sha256: old_hash
                for profile, old_hash in PRE_OVERLAP_AUDIT_PROMPT_HASHES.items()
            },
            counter=counter,
        )
    planted = {path: path.read_bytes() for path in cache.glob("*/global_audit/*.json")}
    assert len(planted) == len(ClipProfile)
    audits_before = counter["ProfileGlobalAuditOutput"]

    # Under the current prompt the old entries are simply cache misses: the audit
    # is regenerated (and must decide the overlap pair), never failed closed.
    providers, final = _overlap_run(
        tmp_path,
        "new",
        overlap_start=2,
        first_audit="distinct",
        repair_audit="duplicate",
        cache=cache,
        counter=counter,
    )
    assert counter["ProfileGlobalAuditOutput"] == audits_before + len(ClipProfile)
    assert len([value for provider in providers for value in provider.audit_repairs]) == 1
    assert [value.candidate_id for value in final.profiles[ClipProfile.MINI_LESSON].selected] == [
        "mini_overlap"
    ]
    assert {path: path.read_bytes() for path in planted} == planted
    manifest = DualProfileRunManifest.model_validate_json(
        (tmp_path / "new" / "run-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.calls["discovery"] == 0
    assert manifest.calls["boundary_review"] == 0


def test_old_contract_audit_under_the_current_identity_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Impossible in practice (the audit prompt hash changed); models an audit that
    # omits its overlap decision but sits under the current identity and payload.
    from liveclip.services import dual_profile_evaluation as service

    cache = tmp_path / "cache"
    full = service.validate_audit_pair_decisions
    with monkeypatch.context() as patch:
        patch.setattr(
            service,
            "validate_audit_pair_decisions",
            lambda pairs, decisions, merged, **kwargs: full(
                tuple(pair for pair in pairs if pair.pair_kind == "nested"),
                decisions,
                merged,
                **kwargs,
            ),
        )
        _overlap_run(
            tmp_path,
            "planted",
            overlap_start=3,
            first_audit="omit",
            repair_audit="omit",
            cache=cache,
        )
    planted = {path: path.read_bytes() for path in cache.glob("*/global_audit/*.json")}
    with pytest.raises(ValueError, match="cover every listed nested pair"):
        _overlap_run(
            tmp_path,
            "warm",
            overlap_start=3,
            first_audit="distinct",
            repair_audit="distinct",
            cache=cache,
        )
    assert {path: path.read_bytes() for path in planted} == planted


def _manifest(tmp_path: Path, name: str) -> DualProfileRunManifest:
    return DualProfileRunManifest.model_validate_json(
        (tmp_path / name / "run-manifest.json").read_text(encoding="utf-8")
    )


def test_audit_payload_lists_persisted_discovery_flags_only_for_the_audit(
    tmp_path: Path,
) -> None:
    providers, _ = _overlap_run(
        tmp_path,
        "run",
        overlap_start=2,
        first_audit="duplicate",
        repair_audit="duplicate",
        flag_lesson=True,
    )
    (payload,) = [value for provider in providers for value in provider.audit_payloads]
    flags = {
        cast(dict[str, str], entry["candidate"])["candidate_id"]: entry[
            "persisted_discovery_gated_flags"
        ]
        for entry in cast(list[dict[str, object]], payload["candidates"])
    }
    assert flags == {"mini_lesson_lesson": ["topic_switch_inside"], "mini_overlap": []}


def test_audit_may_not_keep_a_representative_that_persisted_flags_will_block(
    tmp_path: Path,
) -> None:
    providers, final = _overlap_run(
        tmp_path,
        "run",
        overlap_start=2,
        first_audit="keep_lesson",
        repair_audit="duplicate",
        flag_lesson=True,
    )
    (errors,) = [value for provider in providers for value in provider.audit_repairs]
    assert "persisted Discovery gated flags" in errors[0]
    mini = final.profiles[ClipProfile.MINI_LESSON]
    assert [value.candidate_id for value in mini.selected] == ["mini_overlap"]
    assert [value.candidate_id for value in mini.rejected] == ["mini_lesson_lesson"]


@pytest.mark.parametrize("refresh", [False, True])
def test_near_identical_audit_fallback_blocks_one_member_and_round_trips(
    tmp_path: Path, refresh: bool
) -> None:
    cache = tmp_path / "cache"
    # The audit insists on keeping both near-identical members (initial, repair and
    # regeneration alike); the downgrade-only fallback lets the run finish.
    providers, cold_final = _overlap_run(
        tmp_path,
        "cold",
        overlap_start=2,
        first_audit="distinct",
        repair_audit="distinct",
        cache=cache,
    )
    assert len([value for provider in providers for value in provider.audit_repairs]) == 1
    cold = _manifest(tmp_path, "cold")
    (record,) = cold.audit_pair_fallbacks
    # Both span 110 s; the later-starting member is blocked, the other is kept.
    assert (record.rule, record.blocked_candidate_id) == ("near_identical_pair", "mini_overlap")
    mini = cold_final.profiles[ClipProfile.MINI_LESSON]
    assert [value.candidate_id for value in mini.selected] == ["mini_lesson_lesson"]
    (blocked,) = mini.blocked
    assert blocked.review_reason.startswith("Deterministic audit fallback: ")
    (entry_path,) = cache.glob("mini_lesson/global_audit/*.json")
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    assert entry["conservative_fallback"] == {
        "stage": "global_audit",
        "candidate_ids": ["mini_overlap"],
    }
    # The cache keeps the raw model output (no block in it).
    assert entry["output"]["replacements"] == []
    before = {path: path.read_bytes() for path in cache.glob("*/*/*.json")}

    _overlap_run(
        tmp_path,
        "warm",
        overlap_start=2,
        first_audit="distinct",
        repair_audit="distinct",
        cache=cache,
        refresh_stale_cache=refresh,
        no_calls=True,
    )
    warm = _manifest(tmp_path, "warm")
    assert set(warm.calls.values()) == {0}
    assert warm.audit_pair_fallbacks == cold.audit_pair_fallbacks
    for name in ("final-validated.json", "global-review.json"):
        assert (tmp_path / "warm" / name).read_bytes() == (tmp_path / "cold" / name).read_bytes()
    assert {path: path.read_bytes() for path in cache.glob("*/*/*.json")} == before


def test_representative_rule_fallback_accepts_and_records_without_promoting(
    tmp_path: Path,
) -> None:
    providers, final = _overlap_run(
        tmp_path,
        "run",
        overlap_start=2,
        first_audit="dup_blocked_rep",
        repair_audit="dup_blocked_rep",
    )
    assert len([value for provider in providers for value in provider.audit_repairs]) == 1
    (record,) = _manifest(tmp_path, "run").audit_pair_fallbacks
    assert (record.rule, record.duplicate_candidate_id, record.blocked_candidate_id) == (
        "overlap_representative",
        "mini_lesson_lesson",
        None,
    )
    mini = final.profiles[ClipProfile.MINI_LESSON]
    assert mini.selected == () and mini.manual_review == ()
    assert [value.candidate_id for value in mini.rejected] == ["mini_lesson_lesson"]
    assert [value.candidate_id for value in mini.blocked] == ["mini_overlap"]


def test_persisted_representative_violation_is_accepted_and_counted(tmp_path: Path) -> None:
    # The audit keeps insisting on a representative that persisted flags will block.
    providers, final = _overlap_run(
        tmp_path,
        "run",
        overlap_start=3,
        first_audit="keep_lesson",
        repair_audit="keep_lesson",
        flag_lesson=True,
    )
    assert len([value for provider in providers for value in provider.audit_repairs]) == 1
    manifest = _manifest(tmp_path, "run")
    (record,) = manifest.audit_pair_fallbacks
    assert (record.rule, record.duplicate_candidate_id) == (
        "persisted_flag_representative",
        "mini_overlap",
    )
    # Run diagnostic for the real run (Stage 13c P2-B).
    assert manifest.persisted_flag_representative_duplicates == {
        ClipProfile.SHORT_HIGHLIGHT: 0,
        ClipProfile.MINI_LESSON: 1,
    }
    mini = final.profiles[ClipProfile.MINI_LESSON]
    assert mini.selected == () and mini.manual_review == ()
    assert [value.candidate_id for value in mini.blocked] == ["mini_lesson_lesson"]
    assert [value.candidate_id for value in mini.rejected] == ["mini_overlap"]


def test_model_written_fallback_prefix_is_repaired(tmp_path: Path) -> None:
    providers, final = _overlap_run(
        tmp_path, "run", overlap_start=3, first_audit="prefixed", repair_audit="distinct"
    )
    (errors,) = [value for provider in providers for value in provider.audit_repairs]
    assert "reserved for deterministic Python routing" in errors[0]
    assert _manifest(tmp_path, "run").audit_pair_fallbacks == ()
    assert not any(
        value.review_reason.startswith("Deterministic audit fallback: ")
        for result in final.profiles.values()
        for group in (result.selected, result.manual_review, result.blocked, result.rejected)
        for value in group
    )


def test_audit_fallback_never_masks_another_failure(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cover every listed nested pair"):
        _overlap_run(tmp_path, "run", overlap_start=2, first_audit="omit", repair_audit="omit")


def test_tampered_audit_fallback_marker_fails_closed(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _overlap_run(
        tmp_path,
        "cold",
        overlap_start=2,
        first_audit="distinct",
        repair_audit="distinct",
        cache=cache,
    )
    (entry_path,) = cache.glob("mini_lesson/global_audit/*.json")
    entry = json.loads(entry_path.read_text(encoding="utf-8"))
    entry["conservative_fallback"]["candidate_ids"] = ["mini_lesson_lesson"]
    entry_path.chmod(0o600)
    entry_path.write_text(json.dumps(entry), encoding="utf-8")
    with pytest.raises(ValueError, match="fallback marker is invalid"):
        _overlap_run(
            tmp_path,
            "warm",
            overlap_start=2,
            first_audit="distinct",
            repair_audit="distinct",
            cache=cache,
            no_calls=True,
        )


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
        assert "containment, a shared edge or overlap alone never establishes duplication" in audit
        assert "shortest independently complete candidate" in audit
        # Stage 13: overlap pairs, the near-identical rule and the general tie-break.
        assert "`audit_pairs`" in audit and "`nested_pairs`" not in audit
        assert "`overlap`: neither contains the other" in audit
        assert "do not keep both `selected`/`manual_review`" in audit
        assert "keep the shortest independently complete version" in audit
        # Stage 13b: near-copy containment, the precomputed field and persisted flags.
        assert "`containment`: one lies strictly inside the other" in audit
        assert "precomputed `near_identical` field" in audit
        assert "the two end at the same point" not in audit
        assert "`persisted_discovery_gated_flags`" in audit
        assert "never choose it as a duplicate representative" in audit


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
        assert "own brief remark about microphone distance or placement" not in boundary
        assert (
            "brief explanation of their own equipment, microphone distance or placement, or of why "
            "moving closer helps listeners hear, is part of the demonstration" in boundary
        )
        assert "An audibility check means asking or answering whether someone can hear" in boundary
        assert "connection lag" in boundary
        assert "A speaker explaining how listeners can hear better is not an audibility check" in (
            boundary
        )
        assert "described as part of the teaching, is not connection lag" in boundary
        for value in (review, audit):
            assert "asking or answering whether someone can hear" in value
            assert "brief explanation of their own equipment" in value
        assert "trouble playing back a recording are `device_or_waiting_padding`" in boundary
        assert "and also `material_interruption` when they split a demonstration" in boundary
        assert (
            "A reference to another video or post is setup when the kept interval defines and "
            "demonstrates its own method" in boundary
        )
        # C: live diagnosis boundaries come from transcribed cues.
        assert "starts at the first transcribed cue of the evaluated sample" in boundary
        assert "untranscribed gap holds audio" in boundary
        assert (
            "An edge may extend into an untranscribed gap only when transcribed cues inside the "
            "interval show that the sample in that gap is the one being evaluated" in boundary
        )
        assert "an earlier untranscribed sample is the one evaluated" in review
        assert "a participant's own question about their voice" in boundary
        assert "starting at its first transcribed cue" in review
        # B2: the Profile minimum must be met by on-topic content.
        assert "The Profile minimum must be met by on-topic content" in boundary
        assert "at or under the Profile minimum" not in boundary
        assert (
            "would leave a clip that no longer satisfies the Profile duration minimum, flag "
            "`padded_with_irrelevant_content`" in boundary
        )
        assert (
            "closing acknowledgement or address to the audience is neither padding nor subtracted "
            "from the duration" in boundary
        )
        # Reviewer P2 wording.
        assert "(a `risk_discovery` record is retained as `blocked`)" in review
        assert "decide every pair your replacements create" in audit
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
