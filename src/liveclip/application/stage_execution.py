from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from liveclip.application.pipeline import LeaseIdentity, StageWork
from liveclip.domain.candidate import CandidateClip
from liveclip.domain.review import EditPlanRevision
from liveclip.domain.state_transitions import FailureClass, PipelineStage
from liveclip.domain.transcript import TranscriptDocument
from liveclip.media.models import AudioChunkManifest, SourceMediaMetadata
from liveclip.providers.telemetry import ProviderCallRecord, ProviderCallStatus

if TYPE_CHECKING:
    from liveclip.application.semantic_units import SemanticInvocationStore


class StageCancelled(RuntimeError):
    """Raised at a safe boundary after a persisted cancellation request."""


class StageExecutionError(RuntimeError):
    def __init__(
        self,
        *,
        failure_class: FailureClass,
        error_code: str,
        safe_message: str,
        diagnostic_relative_path: str | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.failure_class = failure_class
        self.error_code = error_code
        self.safe_message = safe_message
        self.diagnostic_relative_path = diagnostic_relative_path


@dataclass(frozen=True, slots=True)
class StageExecutionResult:
    output_fingerprint: str
    checkpoint: dict[str, object]
    diagnostic_relative_path: str | None = None


@dataclass(frozen=True, slots=True)
class StageMutationFence:
    lease: LeaseIdentity
    project_id: str
    run_id: str
    stage_run_id: str
    generation: int


@dataclass(frozen=True, slots=True)
class PersistedCandidate:
    candidate_id: str
    candidate: CandidateClip
    rank: int


@dataclass(frozen=True, slots=True)
class PreparedRevision:
    candidate_id: str
    rank: int
    revision: EditPlanRevision


@dataclass(frozen=True, slots=True)
class PersistedRevision:
    candidate_id: str
    edit_plan_revision_id: str
    revision: EditPlanRevision


@dataclass(frozen=True, slots=True)
class CommittedStageAsset:
    asset_id: str
    kind: str
    relative_path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ProxyRenderIntent:
    candidate_id: str
    edit_plan_revision_id: str
    edit_plan_revision: int
    revision_epoch: int
    width: int
    height: int
    spec_fingerprint: str


@dataclass(frozen=True, slots=True)
class ProxyRenderPersistence:
    candidate_id: str
    edit_plan_revision_id: str
    edit_plan_revision: int
    revision_epoch: int
    width: int
    height: int
    spec_fingerprint: str
    video_asset_id: str
    subtitle_asset_id: str
    quality_report_asset_id: str
    contact_sheet_asset_id: str


class StageStateStore(Protocol):
    @property
    def semantic_invocations(self) -> SemanticInvocationStore: ...

    def assert_mutation_fence(self, fence: StageMutationFence) -> None: ...

    def save_source(
        self,
        fence: StageMutationFence,
        *,
        source: SourceMediaMetadata,
    ) -> str: ...

    def load_source(self, *, project_id: str) -> SourceMediaMetadata: ...

    def load_committed_assets(
        self,
        *,
        project_id: str,
        run_id: str,
        generation: int,
        kinds: tuple[str, ...],
    ) -> tuple[CommittedStageAsset, ...]: ...

    def save_audio(
        self,
        fence: StageMutationFence,
        *,
        manifest: AudioChunkManifest,
        chunk_asset_ids: Mapping[int, str],
    ) -> None: ...

    def record_asr_chunk_outcome(
        self,
        fence: StageMutationFence,
        *,
        cache_key: str,
        status: ProviderCallStatus,
        call_record: ProviderCallRecord | None,
        cache_hit: bool,
    ) -> None: ...

    def record_provider_calls(
        self,
        fence: StageMutationFence,
        records: Sequence[ProviderCallRecord],
        *,
        cache_hit: bool,
    ) -> None: ...

    def record_provider_call_after_cancel(
        self,
        fence: StageMutationFence,
        record: ProviderCallRecord,
    ) -> bool: ...

    def save_transcript(
        self,
        fence: StageMutationFence,
        *,
        transcript: TranscriptDocument,
        transcript_asset_id: str,
        fingerprint: str,
        provider: str,
        model: str,
    ) -> str: ...

    def save_candidates(
        self,
        fence: StageMutationFence,
        *,
        candidates: Sequence[CandidateClip],
    ) -> tuple[PersistedCandidate, ...]: ...

    def load_candidates(self, *, run_id: str) -> tuple[PersistedCandidate, ...]: ...

    def save_revisions(
        self,
        fence: StageMutationFence,
        prepared: Sequence[PreparedRevision],
    ) -> tuple[PersistedRevision, ...]: ...

    def load_current_revisions(self, *, run_id: str) -> tuple[PersistedRevision, ...]: ...

    def start_proxy_render(
        self,
        fence: StageMutationFence,
        value: ProxyRenderIntent,
    ) -> str: ...

    def save_proxy_render(
        self,
        fence: StageMutationFence,
        render_id: str,
        value: ProxyRenderPersistence,
    ) -> str: ...


class StageHandler(Protocol):
    def execute(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        *,
        cancel_requested: Callable[[], bool],
    ) -> StageExecutionResult: ...


def stage_output_fingerprint(stage: PipelineStage, asset_hashes: tuple[str, ...]) -> str:
    if not asset_hashes or any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in asset_hashes):
        raise ValueError("stage output requires committed SHA-256 asset hashes")
    payload = json.dumps(
        {
            "asset_hashes": sorted(asset_hashes),
            "stage": stage.value,
            "version": "stage-output-v1",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
