from __future__ import annotations

import json
import os
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from liveclip.config import Settings
from liveclip.delivery.package import DeliveryClipInput, create_delivery
from liveclip.domain.edit_plan import EditPlan, captions_to_srt
from liveclip.domain.review import (
    ClipLifecycle,
    EditPlanRevision,
    RenderKind,
    RenderRecord,
    RevisionOrigin,
    add_render,
    decide_clip,
    revise_clip,
    start_clip_lifecycle,
)
from liveclip.domain.state_transitions import RenderStatus, ReviewStatus
from liveclip.media.ingest import ingest_source
from liveclip.media.preprocess import preprocess_audio
from liveclip.pipeline.candidates import CandidateGenerationConfig, generate_fallback_candidates
from liveclip.pipeline.transcript import transcribe_chunks
from liveclip.providers.asr.mock import MockASRProvider
from liveclip.providers.llm.mock import MockLLMProvider
from liveclip.renderer.service import RenderTextMode, render_edit_plan_revision
from liveclip.services.captions import captions_for_clip
from liveclip.services.demo_media import create_demo_source


class DemoRunError(RuntimeError):
    pass


class DemoResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    project_id: str
    project_status: str = Field(pattern=r"^delivered$")
    candidate_count: int = Field(ge=3)
    project_dir: Path
    source_video: Path
    final_video: Path
    contact_sheet: Path
    quality_report: Path
    delivery_dir: Path
    delivery_zip: Path
    state_path: Path


def run_demo(*, project_root: Path, settings: Settings) -> DemoResult:
    resolved_project_root = project_root.resolve(strict=True)
    demo_root = resolved_project_root / "data" / "demo"
    demo_root.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC)
    project_id = f"demo_{created_at.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    project_dir = demo_root / "projects" / project_id
    project_dir.mkdir(parents=True, exist_ok=False)
    phase = "generate_source"
    try:
        result = _execute_demo(
            project_id=project_id,
            project_dir=project_dir,
            demo_root=demo_root,
            settings=settings,
            created_at=created_at,
            phase_ref=lambda value: _write_phase(project_dir, value),
        )
    except Exception as exc:
        failure_path = project_dir / "failure.json"
        _atomic_write_json(
            failure_path,
            {
                "schema_version": "1",
                "project_id": project_id,
                "status": "failed",
                "phase": _read_phase(project_dir, default=phase),
                "error_type": exc.__class__.__name__,
                "message": "Demo execution failed; inspect local generated diagnostics.",
                "failed_at": datetime.now(UTC).isoformat(),
            },
        )
        raise DemoRunError(f"Demo failed during {_read_phase(project_dir, default=phase)}") from exc
    return result


def _execute_demo(
    *,
    project_id: str,
    project_dir: Path,
    demo_root: Path,
    settings: Settings,
    created_at: datetime,
    phase_ref: Callable[[str], None],
) -> DemoResult:
    set_phase = phase_ref
    source_path = project_dir / "source" / "demo-source.mp4"
    set_phase("generate_source")
    create_demo_source(output_path=source_path, duration_ms=32_000)

    set_phase("ingest")
    source = ingest_source(source_path, allowed_roots=(demo_root,))
    _atomic_write_json(project_dir / "source" / "source-media.json", source.model_dump(mode="json"))

    set_phase("preprocess")
    audio_manifest = preprocess_audio(
        source=source,
        output_dir=project_dir / "audio",
        chunk_duration_ms=12_000,
        overlap_ms=2_000,
        max_chunk_bytes=24_000_000,
        sample_rate_hz=16_000,
        bitrate="48k",
    )

    set_phase("transcribe")
    transcript = transcribe_chunks(
        MockASRProvider(),
        audio_manifest.chunks,
        source_duration_ms=source.duration_ms,
        output_dir=project_dir / "transcript",
        language="zh",
        vocabulary_prompt="LiveClip、直播、高光、切片",
    )

    set_phase("candidates")
    candidate_config = CandidateGenerationConfig(
        minimum_duration_ms=8_000,
        maximum_duration_ms=12_000,
        rough_limit=12,
        top_n=3,
        context_ms=4_000,
        boundary_pause_ms=700,
    )
    candidates = generate_fallback_candidates(
        transcript,
        config=candidate_config,
        silence_intervals=audio_manifest.silences,
    )
    if len(candidates) < 3:
        raise DemoRunError(
            "deterministic Demo candidate generation produced fewer than three clips"
        )
    _atomic_write_json(
        project_dir / "candidates.json",
        {
            "schema_version": "1",
            "config": candidate_config.model_dump(mode="json"),
            "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        },
    )

    set_phase("edit")
    editor = MockLLMProvider()
    lifecycles: list[ClipLifecycle] = []
    for index, candidate in enumerate(candidates, start=1):
        plan = editor.edit_candidate(
            candidate,
            source_duration_ms=source.duration_ms,
            minimum_duration_ms=candidate_config.minimum_duration_ms,
            maximum_duration_ms=candidate_config.maximum_duration_ms,
        ).plan
        captions = captions_for_clip(
            transcript.segments,
            source_start_ms=plan.source_start_ms,
            source_end_ms=plan.source_end_ms,
        )
        revision = EditPlanRevision(
            clip_id=f"clip_{index:02d}_{candidate.candidate_id[-8:]}",
            revision=1,
            origin=RevisionOrigin.AI,
            plan=plan,
            captions=captions,
            created_at=created_at,
        )
        lifecycles.append(start_clip_lifecycle(revision))

    set_phase("proxy_render")
    for index, lifecycle in enumerate(tuple(lifecycles)):
        proxy_path = project_dir / "renders" / "proxies" / lifecycle.clip_id / "r001" / "review.mp4"
        artifact = render_edit_plan_revision(
            source_path=source.resolved_path,
            revision=lifecycle.current,
            output_path=proxy_path,
            width=settings.preview_render_width,
            height=settings.preview_render_height,
            encoder=settings.video_encoder,
            text_mode=RenderTextMode.NONE,
        )
        lifecycles[index] = add_render(
            lifecycle,
            RenderRecord(
                render_id=f"proxy_{lifecycle.clip_id}_r001",
                revision=1,
                kind=RenderKind.PROXY,
                status=RenderStatus.SUCCEEDED,
                path=artifact.output_path,
                sha256=artifact.sha256,
            ),
        )

    set_phase("demo_review")
    selected = lifecycles[0]
    revised_payload = selected.current.plan.model_dump()
    revised_payload["title"] = "人工修订: 直播表达重点"
    revised_plan = EditPlan.model_validate(revised_payload)
    selected = revise_clip(
        selected,
        plan=revised_plan,
        captions=selected.current.captions,
        created_at=datetime.now(UTC),
    )
    if selected.renders[0].status != RenderStatus.STALE:
        raise DemoRunError("Demo revision did not stale the old proxy render")
    set_phase("delivery_master_render")
    master_path = (
        project_dir
        / "renders"
        / "proxies"
        / selected.clip_id
        / f"r{selected.current_revision:03d}"
        / "review.mp4"
    )
    master_artifact = render_edit_plan_revision(
        source_path=source.resolved_path,
        revision=selected.current,
        output_path=master_path,
        width=settings.final_render_width,
        height=settings.final_render_height,
        encoder=settings.video_encoder,
        text_mode=RenderTextMode.NONE,
    )
    selected = add_render(
        selected,
        RenderRecord(
            render_id=f"master_{selected.clip_id}_r{selected.current_revision:03d}",
            revision=selected.current_revision,
            kind=RenderKind.PROXY,
            status=RenderStatus.SUCCEEDED,
            path=master_artifact.output_path,
            sha256=master_artifact.sha256,
        ),
    )
    selected = decide_clip(
        selected,
        status=ReviewStatus.APPROVED,
        decided_at=datetime.now(UTC),
    )
    lifecycles[0] = selected
    valid_master = next(
        (
            render
            for render in selected.renders
            if render.kind == RenderKind.PROXY
            and render.revision == selected.current_revision
            and render.status == RenderStatus.SUCCEEDED
        ),
        None,
    )
    if valid_master is None or valid_master.path is None or valid_master.sha256 is None:
        raise DemoRunError("current approved revision has no valid delivery master")

    set_phase("delivery")
    delivery = create_delivery(
        project_dir=project_dir,
        project_id=project_id,
        source_filename=source.filename,
        source_fingerprint=source.sha256,
        clips=(
            DeliveryClipInput(
                clip_id=selected.clip_id,
                edit_plan_revision=selected.current_revision,
                render_revision=valid_master.revision,
                title=selected.current.plan.title,
                source_start_ms=selected.current.plan.source_start_ms,
                source_end_ms=selected.current.plan.source_end_ms,
                score=selected.current.plan.score,
                review_status=selected.review_status.value,
                render_status=valid_master.status.value,
                final_video_path=valid_master.path,
                final_video_sha256=valid_master.sha256,
                subtitle_srt=captions_to_srt(selected.current.captions),
            ),
        ),
        include_zip=True,
        created_at=datetime.now(UTC),
    )
    if delivery.zip_path is None:
        raise DemoRunError("Demo delivery did not create its required ZIP")

    set_phase("delivered")
    state_path = project_dir / "project-state.json"
    _atomic_write_json(
        state_path,
        {
            "schema_version": "1",
            "project_id": project_id,
            "project_status": "delivered",
            "created_at": created_at.isoformat(),
            "demo_config": {
                "source_duration_ms": 32_000,
                "minimum_clip_ms": candidate_config.minimum_duration_ms,
                "maximum_clip_ms": candidate_config.maximum_duration_ms,
                "top_n": candidate_config.top_n,
                "provider": "mock",
            },
            "source": source.model_dump(mode="json"),
            "audio_manifest": audio_manifest.model_dump(mode="json"),
            "transcript_path": str((project_dir / "transcript" / "transcript.json").resolve()),
            "clips": [lifecycle.model_dump(mode="json") for lifecycle in lifecycles],
            "delivery": delivery.model_dump(mode="json"),
        },
    )
    return DemoResult(
        project_id=project_id,
        project_status="delivered",
        candidate_count=len(candidates),
        project_dir=project_dir,
        source_video=source.resolved_path,
        final_video=master_artifact.output_path,
        contact_sheet=master_artifact.contact_sheet_path,
        quality_report=master_artifact.quality_report_path,
        delivery_dir=delivery.directory,
        delivery_zip=delivery.zip_path,
        state_path=state_path,
    )


def _write_phase(project_dir: Path, phase: str) -> None:
    _atomic_write_json(project_dir / ".phase.json", {"phase": phase})


def _read_phase(project_dir: Path, *, default: str) -> str:
    try:
        payload = json.loads((project_dir / ".phase.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    value = payload.get("phase") if isinstance(payload, dict) else None
    return value if isinstance(value, str) else default


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
