"""Owner-thread semantic persistence and authenticated recovery from immutable outcomes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from liveclip.application.assets import AssetStore
from liveclip.application.pipeline import StageWork
from liveclip.application.semantic_units import SemanticInvocation, SemanticUnitIdentity
from liveclip.application.stage_execution import StageMutationFence, StageStateStore
from liveclip.domain.semantic_validation import (
    CURRENT_SEMANTIC_EXECUTION,
    SEMANTIC_UNIT_MAX_INVOCATIONS,
)
from liveclip.media.artifacts import write_json_no_clobber
from liveclip.media.secure_files import SecureFileError, read_regular_file_no_follow
from liveclip.pipeline.semantic_cache import semantic_stage_cache_key
from liveclip.pipeline.semantic_executor import (
    SemanticUnitOutcome,
    SemanticUnitRequest,
    run_bounded_semantic_units,
)
from liveclip.pipeline.semantic_transport import canonical_json
from liveclip.providers.llm.structured import StructuredLLMProvider, StructuredProviderError
from liveclip.providers.telemetry import ProviderCancelled

_OUTCOME_MAX_BYTES = 64 * 1024 * 1024


class SemanticRecoveryError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__("semantic invocation recovery requires inspection or an explicit new run")
        self.code = code


class SemanticBatchFailure(StructuredProviderError):
    """Trusted unit disposition survives Stage failure classification."""

    def __init__(self, error: StructuredProviderError, *, deterministic: bool) -> None:
        super().__init__(
            error.code,
            error.call_records,
            repair_attempts=error.repair_attempts,
            diagnostic_relative_path=error.diagnostic_relative_path,
        )
        self.deterministic = deterministic


class SemanticOutcomeEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["1"] = "1"
    invocation: SemanticInvocation
    config_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    stage_input_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    schema_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider: str
    model: str
    provider_contract: str
    prompt_version: str
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: SemanticUnitOutcome


@dataclass(frozen=True, slots=True)
class SemanticBatchResult:
    outputs: Mapping[str, BaseModel]
    outcomes: Mapping[str, SemanticUnitOutcome]
    cache_hits: Mapping[str, bool]
    request_keys: Mapping[str, str]


def run_persisted_semantic_units(
    *,
    work: StageWork,
    fence: StageMutationFence,
    project_dir: Path,
    state: StageStateStore,
    assets: AssetStore,
    stage: str,
    source_sha256: str,
    provider: StructuredLLMProvider,
    model_settings: dict[str, object],
    requests: Sequence[SemanticUnitRequest],
    concurrency: int,
    cancel_requested: Callable[[], bool],
    redact: Callable[[object], object],
) -> SemanticBatchResult:
    if getattr(work.config, "semantic_execution_contract", None) != CURRENT_SEMANTIC_EXECUTION:
        raise ValueError("durable semantic execution requires its immutable config contract")
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
        raise ValueError("semantic runtime fence differs from its immutable work")
    requests = tuple(requests)
    if len({r.subject_id for r in requests}) != len(requests):
        raise ValueError("semantic unit subjects must be unique")
    if any(len(f"{work.run_id}.{stage}.{r.subject_id}") > 128 for r in requests):
        raise ValueError("qualified semantic subject exceeds provider evidence bound")
    journal = state.semantic_invocations
    settings = {
        **model_settings,
        "semantic_execution_contract": CURRENT_SEMANTIC_EXECUTION,
        "pipeline_config_fingerprint": work.config.fingerprint,
        "source_sha256": source_sha256,
    }
    identities = {
        request.subject_id: SemanticUnitIdentity(
            semantic_stage=stage,
            subject_id=request.subject_id,
            request_key=semantic_stage_cache_key(
                stage=stage,
                payload=request.payload(),
                provider=provider,
                model_settings=settings,
                output_model=request.response_model,
            ),
        )
        for request in requests
    }
    outputs: dict[str, BaseModel] = {}
    outcomes: dict[str, SemanticUnitOutcome] = {}
    hits: dict[str, bool] = {}
    histories: dict[str, tuple[str, ...]] = {}
    pending: list[SemanticUnitRequest] = []
    reservations: dict[int, SemanticInvocation] = {}

    def active() -> None:
        if cancel_requested():
            raise ProviderCancelled()
        state.assert_mutation_fence(fence)

    def binding(request: SemanticUnitRequest) -> dict[str, object]:
        return {
            "config_fingerprint": work.config.fingerprint,
            "source_sha256": source_sha256,
            "payload_sha256": hashlib.sha256(request.payload_json.encode()).hexdigest(),
            "schema_sha256": hashlib.sha256(
                canonical_json(request.response_model.model_json_schema(mode="validation")).encode()
            ).hexdigest(),
            "provider": provider.provider_name,
            "model": provider.model_name,
            "provider_contract": provider.contract_version,
            "prompt_version": provider.prompt_version,
            "prompt_sha256": provider.prompt_sha256,
        }

    def replay(request: SemanticUnitRequest, saved: SemanticInvocation) -> SemanticUnitOutcome:
        origin = journal.load_origin_identity(fence, saved)
        if any(
            getattr(origin, key) != getattr(saved, key)
            for key in ("invocation_id", "project_id", "run_id", "stage_run_id", "generation")
        ):
            raise SemanticRecoveryError("SEMANTIC_UNIT_EVIDENCE_INVALID")
        if saved.completed_at is None:
            raise SemanticRecoveryError("SEMANTIC_UNIT_EXECUTION_UNCERTAIN")
        if not saved.outcome_relative_path or saved.outcome_size_bytes is None:
            raise SemanticRecoveryError("SEMANTIC_UNIT_EVIDENCE_INVALID")
        path = project_dir / saved.outcome_relative_path
        # Journal store authenticates a deterministic relative path and exact Asset
        # owner first. The filesystem read rejects symlinks and enforces the bound.
        try:
            raw = read_regular_file_no_follow(path, max_bytes=_OUTCOME_MAX_BYTES)
            envelope = SemanticOutcomeEnvelope.model_validate_json(raw)
        except (SecureFileError, OSError, ValueError) as exc:
            raise SemanticRecoveryError("SEMANTIC_UNIT_EVIDENCE_INVALID") from exc
        if (
            len(raw) != saved.outcome_size_bytes
            or hashlib.sha256(raw).hexdigest() != saved.outcome_sha256
        ):
            raise SemanticRecoveryError("SEMANTIC_UNIT_EVIDENCE_INVALID")
        expected_reservation = saved.model_copy(
            update={
                "completed_at": None,
                "disposition": None,
                "repair_spent": None,
                "outcome_asset_id": None,
                "outcome_sha256": None,
                "outcome_size_bytes": None,
                "outcome_relative_path": None,
            }
        )
        if (
            envelope.config_fingerprint != origin.config_fingerprint
            or envelope.stage_input_fingerprint != origin.stage_input_fingerprint
            or envelope.invocation != expected_reservation
            or any(getattr(envelope, key) != value for key, value in binding(request).items())
        ):
            raise SemanticRecoveryError("SEMANTIC_UNIT_EVIDENCE_INVALID")
        if (
            saved.run_id == work.run_id
            and envelope.stage_input_fingerprint != work.input_fingerprint
        ):
            raise SemanticRecoveryError("SEMANTIC_UNIT_EVIDENCE_INVALID")
        outcome = envelope.outcome
        if outcome.disposition != saved.disposition or outcome.repair_spent != saved.repair_spent:
            raise SemanticRecoveryError("SEMANTIC_UNIT_EVIDENCE_INVALID")
        _validate_calls(saved, envelope)
        if outcome.disposition == "succeeded":
            try:
                raw_model = request.response_model.model_validate_json(
                    json.dumps(outcome.raw_output)
                )
                validated = request.validate(raw_model)
            except ValueError as exc:
                raise SemanticRecoveryError("SEMANTIC_UNIT_EVIDENCE_INVALID") from exc
            if validated.model_dump(mode="json") != outcome.validated_output:
                raise SemanticRecoveryError("SEMANTIC_UNIT_EVIDENCE_INVALID")
            outputs[request.subject_id] = validated
        return outcome

    active()
    for request in requests:
        identity = identities[request.subject_id]
        history = journal.load_history(fence, identity)
        # Validate all prior transient evidence, not just the latest status flag.
        prior = [replay(request, item) for item in history]
        histories[request.subject_id] = tuple(item.invocation_id for item in history)
        if history:
            latest = prior[-1]
            if latest.disposition == "succeeded":
                outcomes[request.subject_id] = latest
                hits[request.subject_id] = True
                continue
            if latest.disposition != "transient" or latest.repair_spent:
                outcomes[request.subject_id] = latest
                hits[request.subject_id] = True
                continue
            if len(history) >= SEMANTIC_UNIT_MAX_INVOCATIONS:
                raise SemanticRecoveryError("SEMANTIC_UNIT_INVOCATIONS_EXHAUSTED")
        else:
            success_history = journal.load_prior_success_history(fence, identity)
            if success_history:
                # Every predecessor contributes authority to a later success. Its
                # bytes/calls must authenticate just as they do for same-run retry.
                authenticated = [replay(request, item) for item in success_history]
                outcome = authenticated[-1]
                if outcome.disposition != "succeeded":
                    raise SemanticRecoveryError("SEMANTIC_UNIT_EVIDENCE_INVALID")
                outcomes[request.subject_id] = outcome
                hits[request.subject_id] = True
                continue
        pending.append(request)

    # A known terminal unit prohibits starting fresh siblings on an unchanged retry.
    if any(outcome.disposition != "succeeded" for outcome in outcomes.values()):
        return SemanticBatchResult(
            outputs, outcomes, hits, {k: v.request_key for k, v in identities.items()}
        )

    def reserve(index: int, _: SemanticUnitRequest) -> None:
        active()
        request = pending[index]
        reservations[index] = journal.reserve(
            fence,
            identities[request.subject_id],
            expected_history=histories[request.subject_id],
        )

    def persist(index: int, outcome: SemanticUnitOutcome) -> None:
        active()
        request = pending[index]
        saved = reservations[index]
        envelope = SemanticOutcomeEnvelope.model_validate(
            {
                "invocation": saved,
                "stage_input_fingerprint": work.input_fingerprint,
                "outcome": outcome,
                **binding(request),
            }
        )
        _validate_calls(saved, envelope)
        state.record_provider_calls(fence, outcome.call_records, cache_hit=False)
        relative = (
            f"runs/g{work.generation:03d}/semantic-units/"
            f"{saved.attempt_id}/{saved.invocation_id}.json"
        )
        reservation = assets.reserve(
            fence.lease,
            project_id=work.project_id,
            kind="semantic_unit_outcome",
            relative_path=relative,
            mime_type="application/json",
            input_fingerprint=saved.request_key,
            generation=work.generation,
        )
        active()
        digest = write_json_no_clobber(
            project_dir / relative,
            redact(envelope.model_dump(mode="json")),
            max_bytes=_OUTCOME_MAX_BYTES,
        )
        active()
        committed = assets.commit(
            fence.lease,
            reservation,
            project_dir=project_dir,
            expected_sha256=digest,
            validation={"schema_version": "1", "execution_contract": CURRENT_SEMANTIC_EXECUTION},
        )
        if committed.size_bytes is None:
            raise SemanticRecoveryError("SEMANTIC_UNIT_EVIDENCE_INVALID")
        journal.complete(
            fence,
            saved,
            outcome_asset_id=committed.asset_id,
            expected_sha256=digest,
            expected_size_bytes=committed.size_bytes,
            disposition=outcome.disposition,
            repair_spent=outcome.repair_spent,
        )
        if outcome.disposition == "succeeded":
            outputs[request.subject_id] = request.response_model.model_validate_json(
                json.dumps(outcome.validated_output)
            )
        outcomes[request.subject_id] = outcome
        hits[request.subject_id] = False

    def abandoned(_: int, outcome: SemanticUnitOutcome) -> None:
        for record in outcome.call_records:
            state.record_provider_call_after_cancel(fence, record)

    qualified = tuple(
        replace(request, subject_id=f"{work.run_id}.{stage}.{request.subject_id}")
        for request in pending
    )
    run_bounded_semantic_units(
        qualified,
        provider=provider,
        concurrency=concurrency,
        before_submit=reserve,
        on_complete=persist,
        on_abandoned=abandoned,
        cancel_requested=cancel_requested,
    )
    return SemanticBatchResult(
        outputs, outcomes, hits, {k: v.request_key for k, v in identities.items()}
    )


def _validate_calls(saved: SemanticInvocation, envelope: SemanticOutcomeEnvelope) -> None:
    outcome = envelope.outcome
    phases: list[str] = []
    for call in outcome.call_records:
        phase = call.operation.rsplit(".", 1)[-1]
        if (
            call.subject_id != f"{saved.run_id}.{saved.semantic_stage}.{saved.subject_id}"
            or call.provider != envelope.provider
            or call.model != envelope.model
            or call.prompt_sha256 != envelope.prompt_sha256
            or call.prompt_version != f"{envelope.prompt_version}.{saved.semantic_stage}"
            or call.operation != f"responses.semantic.{saved.semantic_stage}.{phase}"
            or phase not in {"initial", "repair"}
            or call.called_at < saved.reserved_at
        ):
            raise SemanticRecoveryError("SEMANTIC_UNIT_EVIDENCE_INVALID")
        phases.append(phase)
    if phases not in ([], ["initial"], ["initial", "repair"]):
        raise SemanticRecoveryError("SEMANTIC_UNIT_EVIDENCE_INVALID")
    if ("repair" in phases and not outcome.repair_spent) or (
        outcome.disposition == "succeeded"
        and (not phases or outcome.repair_spent != ("repair" in phases))
    ):
        raise SemanticRecoveryError("SEMANTIC_UNIT_EVIDENCE_INVALID")
