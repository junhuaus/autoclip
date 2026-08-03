from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from liveclip.application.assets import AssetReservation, AssetStore
from liveclip.application.pipeline import LeaseIdentity, StageWork
from liveclip.application.stage_execution import (
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
from liveclip.domain.review import EditPlanRevision, RevisionOrigin
from liveclip.domain.state_transitions import FailureClass, PipelineStage
from liveclip.domain.transcript import TranscriptDocument
from liveclip.media.artifacts import (
    attempt_directory,
    project_directory,
    publish_file_no_clobber,
    write_json_no_clobber,
)
from liveclip.media.ingest import MediaIngestError, MediaIngestTransientError, ingest_source
from liveclip.media.models import AudioChunkManifest
from liveclip.media.preprocess import (
    AudioPreprocessCancelled,
    AudioPreprocessError,
    AudioPreprocessTransientError,
    preprocess_audio,
)
from liveclip.pipeline.candidates import (
    CandidateGenerationConfig,
    fallback_select,
    generate_candidates,
)
from liveclip.pipeline.transcript import transcribe_chunks
from liveclip.providers.asr.mock import MockASRProvider
from liveclip.providers.llm.mock import MockLLMProvider
from liveclip.renderer.ffmpeg import FFmpegRenderCancelled, FFmpegRenderError
from liveclip.renderer.quality import (
    MediaValidationCancelled,
    MediaValidationError,
    MediaValidationTransientError,
    validate_rendered_media,
)
from liveclip.renderer.service import render_edit_plan_revision, render_revision_overlays
from liveclip.services.captions import captions_for_clip


class PipelineStageHandlers:
    def __init__(
        self,
        *,
        data_dir: Path,
        allowed_media_roots: tuple[Path, ...],
        assets: AssetStore,
        state: StageStateStore,
    ) -> None:
        self._data_dir = data_dir
        self._allowed_media_roots = allowed_media_roots
        self._assets = assets
        self._state = state

    def execute(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        *,
        cancel_requested: Callable[[], bool],
    ) -> StageExecutionResult:
        _check_cancel(cancel_requested)
        try:
            handlers = {
                PipelineStage.INGEST: self._ingest,
                PipelineStage.PREPROCESS: self._preprocess,
                PipelineStage.TRANSCRIBE: self._transcribe,
                PipelineStage.CANDIDATES: self._candidates,
                PipelineStage.EDIT: self._edit,
                PipelineStage.PROXY_RENDER: self._proxy_render,
            }
            return handlers[work.stage](work, lease, cancel_requested)
        except AudioPreprocessCancelled as exc:
            raise StageCancelled("audio preprocessing was cancelled") from exc
        except (FFmpegRenderCancelled, MediaValidationCancelled) as exc:
            raise StageCancelled("proxy rendering was cancelled") from exc
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
                failure_class=FailureClass.TRANSIENT,
                error_code="RENDER_TEMPORARY",
                safe_message="The local renderer failed temporarily and may be retried",
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
            raise StageExecutionError(
                failure_class=FailureClass.DETERMINISTIC,
                error_code=f"{work.stage.value.upper()}_OUTPUT_INVALID",
                safe_message=f"The {work.stage.value} stage produced invalid local data",
            ) from exc

    def _ingest(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        cancel_requested: Callable[[], bool],
    ) -> StageExecutionResult:
        project_dir = project_directory(self._data_dir, work.project_id)
        relative_path = "source/source-media.json"
        reservation = self._reserve(
            work,
            lease,
            kind="source_metadata",
            relative_path=relative_path,
            mime_type="application/json",
        )
        _check_cancel(cancel_requested)
        source = ingest_source(work.source_path, allowed_roots=self._allowed_media_roots)
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
        source = self._state.load_source(project_id=work.project_id)
        manifest_relative = "audio/chunk-manifest.json"
        manifest_reservation = self._reserve(
            work,
            lease,
            kind="audio_manifest",
            relative_path=manifest_relative,
            mime_type="application/json",
        )
        manifest = preprocess_audio(
            source=source,
            output_dir=project_dir / "audio",
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
        if work.config.provider != "mock":
            raise StageExecutionError(
                failure_class=FailureClass.DETERMINISTIC,
                error_code="OPENAI_PROVIDER_NOT_AVAILABLE",
                safe_message="OpenAI providers are not enabled in this milestone",
            )
        project_dir = project_directory(self._data_dir, work.project_id)
        source = self._state.load_source(project_id=work.project_id)
        manifest = AudioChunkManifest.model_validate_json(
            (project_dir / "audio" / "chunk-manifest.json").read_text(encoding="utf-8")
        )
        reservations = (
            self._reserve(
                work,
                lease,
                kind="transcript_json",
                relative_path="transcript/transcript.json",
                mime_type="application/json",
            ),
            self._reserve(
                work,
                lease,
                kind="transcript_srt",
                relative_path="transcript/transcript.srt",
                mime_type="application/x-subrip",
            ),
        )
        _check_cancel(cancel_requested)
        provider = MockASRProvider(model_name=work.config.transcription_model)
        transcript = transcribe_chunks(
            provider,
            manifest.chunks,
            source_duration_ms=source.duration_ms,
            output_dir=project_dir / "transcript",
            language="zh",
            vocabulary_prompt="LiveClip、直播、高光、切片",
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
        transcript = TranscriptDocument.model_validate_json(
            (project_dir / "transcript" / "transcript.json").read_text(encoding="utf-8")
        )
        manifest = AudioChunkManifest.model_validate_json(
            (project_dir / "audio" / "chunk-manifest.json").read_text(encoding="utf-8")
        )
        reservation = self._reserve(
            work,
            lease,
            kind="rough_candidates",
            relative_path="candidates/rough-candidates.json",
            mime_type="application/json",
        )
        _check_cancel(cancel_requested)
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
        if not candidates:
            raise ValueError("deterministic candidate generation produced no complete clips")
        write_json_no_clobber(
            project_dir / reservation.relative_path,
            {
                "schema_version": "1",
                "config": config.model_dump(mode="json"),
                "candidates": [item.model_dump(mode="json") for item in candidates],
            },
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
        if work.config.provider != "mock":
            raise StageExecutionError(
                failure_class=FailureClass.DETERMINISTIC,
                error_code="OPENAI_PROVIDER_NOT_AVAILABLE",
                safe_message="OpenAI providers are not enabled in this milestone",
            )
        project_dir = project_directory(self._data_dir, work.project_id)
        source = self._state.load_source(project_id=work.project_id)
        transcript = TranscriptDocument.model_validate_json(
            (project_dir / "transcript" / "transcript.json").read_text(encoding="utf-8")
        )
        candidates = self._state.load_candidates(run_id=work.run_id)
        selected_domain = fallback_select(
            tuple(item.candidate for item in candidates),
            top_n=work.config.top_n,
        )
        by_key = {item.candidate.candidate_id: item for item in candidates}
        selected = tuple(by_key[item.candidate_id] for item in selected_domain)
        reservation = self._reserve(
            work,
            lease,
            kind="edit_plans",
            relative_path="editing/edit-plans.json",
            mime_type="application/json",
        )
        artifact_path = project_dir / reservation.relative_path
        if artifact_path.is_file():
            prepared = _load_prepared_revisions(artifact_path)
        else:
            editor = MockLLMProvider(model_name=work.config.llm_model)
            prepared_values: list[PreparedRevision] = []
            created_at = datetime.now(UTC)
            for rank, item in enumerate(selected, start=1):
                _check_cancel(cancel_requested)
                plan = editor.edit_candidate(
                    item.candidate,
                    source_duration_ms=source.duration_ms,
                    minimum_duration_ms=work.config.minimum_clip_ms,
                    maximum_duration_ms=work.config.maximum_clip_ms,
                )
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
                            origin=RevisionOrigin.AI,
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
                },
            )
        if {item.candidate_id for item in prepared} != {item.candidate_id for item in selected}:
            raise ValueError("persisted edit selection differs from current candidates")
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

    def _proxy_render(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        cancel_requested: Callable[[], bool],
    ) -> StageExecutionResult:
        project_dir = project_directory(self._data_dir, work.project_id)
        attempt_dir = attempt_directory(project_dir, lease)
        source = self._state.load_source(project_id=work.project_id)
        revisions = self._state.load_current_revisions(run_id=work.run_id)
        if not revisions:
            raise ValueError("proxy rendering has no selected EditPlan revisions")
        all_assets: list[AssetReservation] = []
        render_ids: list[str] = []
        for item in revisions:
            _check_cancel(cancel_requested)
            spec_fingerprint = _render_spec_fingerprint(
                item.revision,
                width=work.config.preview_width,
                height=work.config.preview_height,
                encoder=work.config.video_encoder,
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
            base_relative = f"renders/proxies/{item.candidate_id}/r001"
            video_relative = f"{base_relative}/review.mp4"
            quality_relative = f"{base_relative}/review-quality/quality-report.json"
            contact_relative = f"{base_relative}/review-quality/contact-sheet.png"
            video_reservation = self._reserve(
                work,
                lease,
                kind="review_proxy",
                relative_path=video_relative,
                mime_type="video/mp4",
                candidate_id=item.candidate_id,
                edit_plan_revision=1,
                revision_epoch=work.revision_epoch,
            )
            quality_reservation = self._reserve(
                work,
                lease,
                kind="render_quality_report",
                relative_path=quality_relative,
                mime_type="application/json",
                candidate_id=item.candidate_id,
                edit_plan_revision=1,
                revision_epoch=work.revision_epoch,
            )
            contact_reservation = self._reserve(
                work,
                lease,
                kind="render_contact_sheet",
                relative_path=contact_relative,
                mime_type="image/png",
                candidate_id=item.candidate_id,
                edit_plan_revision=1,
                revision_epoch=work.revision_epoch,
            )
            canonical_video = project_dir / video_relative
            canonical_quality = project_dir / quality_relative
            canonical_contact = project_dir / contact_relative
            if not canonical_video.is_file():
                attempt_video = attempt_dir / video_relative
                artifact = render_edit_plan_revision(
                    source_path=source.resolved_path,
                    revision=item.revision,
                    output_path=attempt_video,
                    width=work.config.preview_width,
                    height=work.config.preview_height,
                    encoder=work.config.video_encoder,
                    cancel_requested=cancel_requested,
                )
                report_payload = json.loads(
                    artifact.quality_report_path.read_text(encoding="utf-8")
                )
                publish_file_no_clobber(artifact.output_path, canonical_video)
                publish_file_no_clobber(artifact.contact_sheet_path, canonical_contact)
                _write_canonical_quality_report(
                    canonical_quality,
                    report_payload,
                    media_path=canonical_video,
                    contact_sheet=canonical_contact,
                )
            else:
                _check_cancel(cancel_requested)
                recovery_root = attempt_dir / base_relative / "recovery"
                overlays = render_revision_overlays(
                    revision=item.revision,
                    output_dir=recovery_root / "overlays",
                    width=work.config.preview_width,
                    height=work.config.preview_height,
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
                publish_file_no_clobber(recovery_contact, canonical_contact)
                _write_canonical_quality_report(
                    canonical_quality,
                    quality.as_dict(),
                    media_path=canonical_video,
                    contact_sheet=canonical_contact,
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
            )
            committed_quality = self._commit(
                lease,
                quality_reservation,
                project_dir=project_dir,
                validation={"schema_version": "1", "automatic_status": "passed"},
            )
            committed_contact = self._commit(
                lease,
                contact_reservation,
                project_dir=project_dir,
                validation={"schema_version": "1", "frames": 3},
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
                        quality_report_asset_id=committed_quality.asset_id,
                        contact_sheet_asset_id=committed_contact.asset_id,
                    ),
                )
            )
            all_assets.extend((committed_video, committed_quality, committed_contact))
        return self._result(
            work.stage,
            tuple(all_assets),
            {"proxy_count": len(render_ids), "render_ids": render_ids},
        )

    def _reserve(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        *,
        kind: str,
        relative_path: str,
        mime_type: str,
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
            input_fingerprint=work.input_fingerprint,
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
    ) -> AssetReservation:
        return self._assets.commit(
            lease,
            reservation,
            project_dir=project_dir,
            validation=validation,
        )

    @staticmethod
    def _result(
        stage: PipelineStage,
        assets: tuple[AssetReservation, ...],
        checkpoint: dict[str, object],
    ) -> StageExecutionResult:
        asset_ids = [asset.asset_id for asset in assets]
        hashes = tuple(asset.sha256 for asset in assets if asset.sha256 is not None)
        if len(hashes) != len(assets):
            raise ValueError("stage result contains an uncommitted asset")
        return StageExecutionResult(
            output_fingerprint=stage_output_fingerprint(stage, hashes),
            checkpoint={**checkpoint, "asset_ids": asset_ids},
        )


def _check_cancel(cancel_requested: Callable[[], bool]) -> None:
    if cancel_requested():
        raise StageCancelled("stage cancellation was requested")


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


def _load_prepared_revisions(path: Path) -> tuple[PreparedRevision, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
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
) -> str:
    payload = json.dumps(
        {
            "encoder": encoder,
            "height": height,
            "renderer": "ffmpeg-renderer-v1",
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
) -> None:
    if not isinstance(raw_payload, dict):
        raise ValueError("render quality report is not an object")
    payload = {str(key): value for key, value in raw_payload.items()}
    payload["media_path"] = str(media_path.resolve(strict=True))
    payload["contact_sheet"] = str(contact_sheet.resolve(strict=True))
    write_json_no_clobber(path, payload)
