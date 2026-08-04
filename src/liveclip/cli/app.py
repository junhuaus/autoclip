from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from liveclip import __version__
from liveclip.application.deliveries import DeliveryRequest
from liveclip.application.media_assets import MediaAssetInvalid, MediaAssetNotFound
from liveclip.application.reviewing import ClipPatch, RenderRequest, ReviewCommand
from liveclip.bootstrap import (
    BootstrapError,
    LiveClipRuntime,
    local_worker_id,
    pipeline_config_from_settings,
)
from liveclip.cli.doctor import DoctorReport, run_doctor
from liveclip.config import get_settings
from liveclip.domain.edit_plan import CaptionCue
from liveclip.domain.state_transitions import (
    DeliveryStatus,
    PipelineRunStatus,
    RenderStatus,
    ReviewStatus,
)
from liveclip.domain.time import seconds_to_ms
from liveclip.services.cloud_smoke import CloudSmokeError, run_cloud_smoke
from liveclip.services.demo import DemoRunError, run_demo
from liveclip.services.demo_media import DemoMediaError, clean_demo_contents
from liveclip.worker import run_worker

app = typer.Typer(
    name="liveclip",
    help="Local-first Chinese livestream highlight clipping.",
    no_args_is_help=True,
    add_completion=False,
)


def _render_report(report: DoctorReport) -> None:
    symbols = {"pass": "PASS", "warning": "WARN", "fail": "FAIL"}
    for check in report.checks:
        typer.echo(f"[{symbols[check.status]}] {check.name}: {check.summary}")
        if check.details:
            typer.echo(f"       {json.dumps(check.details, ensure_ascii=False, sort_keys=True)}")
    state = "READY" if report.ok else "NOT READY"
    typer.echo(f"LiveClip doctor: {state} ({report.warnings} warning(s))")


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Emit a machine-readable report."),
) -> None:
    """Check local runtime, media, SQLite, paths, fonts, and cloud configuration."""

    report = run_doctor(get_settings())
    if json_output:
        typer.echo(report.as_json())
    else:
        _render_report(report)
    if not report.ok:
        raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Print the LiveClip package version."""

    typer.echo(__version__)


@app.command("run")
def run_pipeline(
    input_path: Annotated[Path, typer.Option("--input", help="Absolute local source video path.")],
    top_n: Annotated[int | None, typer.Option("--top-n", min=1, max=100)] = None,
    minimum_seconds: Annotated[int | None, typer.Option("--min-seconds", min=1, max=600)] = None,
    maximum_seconds: Annotated[int | None, typer.Option("--max-seconds", min=1, max=1_800)] = None,
    wait: Annotated[
        bool, typer.Option("--wait", help="Process in this foreground process.")
    ] = False,
) -> None:
    """Create a persisted project/run and optionally process it to human review."""

    if not input_path.is_absolute() or ".." in input_path.parts:
        typer.echo("--input must be an absolute path without '..'", err=True)
        raise typer.Exit(code=2)
    settings = get_settings()
    try:
        config = pipeline_config_from_settings(
            settings,
            top_n=top_n,
            minimum_clip_seconds=minimum_seconds,
            maximum_clip_seconds=maximum_seconds,
        )
        with LiveClipRuntime.open(settings) as runtime:
            created = runtime.pipeline_service.create_project_and_run(
                source_path=input_path,
                config=config,
                max_stage_retries=settings.max_stage_retries,
            )
            typer.echo(f"Project ID: {created.project_id}")
            typer.echo(f"Pipeline run ID: {created.run_id}")
            if not wait:
                typer.echo("Pipeline status: queued")
                return
            snapshot = runtime.stage_runner.run_until_terminal(
                created.run_id,
                worker_id=local_worker_id("foreground"),
            )
            project = runtime.pipeline_service.get_project(created.project_id)
            typer.echo(f"Pipeline status: {snapshot.status.value}")
            typer.echo(f"Project status: {project.status.value}")
            typer.echo(f"Progress: {snapshot.progress}%")
            if snapshot.status != PipelineRunStatus.COMPLETED:
                if snapshot.error_code:
                    typer.echo(f"Error: {snapshot.error_code}", err=True)
                if snapshot.safe_error_message:
                    typer.echo(snapshot.safe_error_message, err=True)
                raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except (BootstrapError, ValidationError, ValueError, RuntimeError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def status(project_id: str) -> None:
    """Show the current derived project state and detailed pipeline stages."""

    settings = get_settings()
    try:
        with LiveClipRuntime.open(settings) as runtime:
            project = runtime.pipeline_service.get_project(project_id)
            run = runtime.pipeline_service.get_run(project.current_run_id)
            typer.echo(f"Project ID: {project.project_id}")
            typer.echo(f"Project status: {project.status.value}")
            typer.echo(f"Pipeline run ID: {run.run_id}")
            typer.echo(f"Pipeline status: {run.status.value}")
            typer.echo(f"Progress: {run.progress}%")
            for stage in run.stages:
                detail = f" - {stage.stage}: {stage.status.value} ({stage.progress}%)"
                if stage.error_code:
                    detail += f" [{stage.error_code}]"
                typer.echo(detail)
    except (BootstrapError, ValueError, RuntimeError, LookupError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def clips(project_id: str) -> None:
    """List the selected review candidates for a project."""

    settings = get_settings()
    try:
        with LiveClipRuntime.open(settings) as runtime:
            values = runtime.clip_query_service.list_project_clips(project_id)
            if not values:
                typer.echo("No review clips are available")
                return
            for clip in values:
                typer.echo(
                    f"{clip.clip_id} | {clip.review_status.value} | "
                    f"{clip.source_start_ms / 1000:.3f}-{clip.source_end_ms / 1000:.3f}s | "
                    f"{clip.score:.1f} | {clip.title}"
                )
                typer.echo(f"  Reason: {clip.reason}")
                typer.echo(
                    "  Risk flags: " + (", ".join(clip.risk_flags) if clip.risk_flags else "none")
                )
                proxy_status = clip.proxy_status.value if clip.proxy_status else "not_rendered"
                typer.echo(f"  Proxy status: {proxy_status}")
                if clip.proxy_asset_id is not None:
                    try:
                        proxy = runtime.media_asset_service.resolve(
                            clip.proxy_asset_id,
                            required_kind="review_proxy",
                        )
                    except (MediaAssetInvalid, MediaAssetNotFound):
                        typer.echo("  Proxy path: unavailable (asset verification failed)")
                    else:
                        typer.echo(f"  Proxy path: {proxy.path}")
    except (BootstrapError, ValueError, RuntimeError, LookupError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def review(
    clip_id: str,
    approve: Annotated[bool, typer.Option("--approve", help="Approve the current revision.")] = (
        False
    ),
    reject: Annotated[bool, typer.Option("--reject", help="Reject the current revision.")] = False,
    reason: Annotated[str | None, typer.Option("--reason", help="Required rejection reason.")] = (
        None
    ),
    start: Annotated[
        float | None,
        typer.Option("--start", min=0, help="New absolute source start in seconds."),
    ] = None,
    end: Annotated[
        float | None,
        typer.Option("--end", min=0, help="New absolute source end in seconds."),
    ] = None,
    title: Annotated[str | None, typer.Option("--title", help="New Chinese clip title.")] = None,
    subtitle_text: Annotated[
        str | None,
        typer.Option(
            "--subtitle-text",
            help="Replace captions with one cue spanning the revised clip.",
        ),
    ] = None,
) -> None:
    """Atomically edit and approve or reject a clip revision."""

    if approve == reject:
        typer.echo("Choose exactly one of --approve or --reject", err=True)
        raise typer.Exit(code=2)
    settings = get_settings()
    try:
        with LiveClipRuntime.open(settings) as runtime:
            current = runtime.review_service.get_clip(clip_id)
            new_start_ms = seconds_to_ms(start) if start is not None else None
            new_end_ms = seconds_to_ms(end) if end is not None else None
            captions = None
            if subtitle_text is not None:
                effective_start = (
                    new_start_ms if new_start_ms is not None else current.plan.source_start_ms
                )
                effective_end = new_end_ms if new_end_ms is not None else current.plan.source_end_ms
                captions = (
                    CaptionCue(
                        start_ms=0,
                        end_ms=effective_end - effective_start,
                        text=subtitle_text,
                    ),
                )
            command = ReviewCommand(
                expected_revision=current.current_revision,
                status=ReviewStatus.APPROVED if approve else ReviewStatus.REJECTED,
                reason=reason,
            )
            has_patch = any(
                value is not None for value in (new_start_ms, new_end_ms, title, subtitle_text)
            )
            if has_patch:
                result = runtime.review_service.revise_and_review(
                    clip_id,
                    ClipPatch(
                        expected_revision=current.current_revision,
                        source_start_ms=new_start_ms,
                        source_end_ms=new_end_ms,
                        title=title,
                        captions=captions,
                    ),
                    command,
                )
            else:
                result = runtime.review_service.review_clip(clip_id, command)
            typer.echo(f"Clip ID: {result.clip_id}")
            typer.echo(f"EditPlan revision: {result.current_revision}")
            typer.echo(f"Review status: {result.review.status.value}")
            typer.echo(
                f"Source range: {result.plan.source_start_ms / 1000:.3f}-"
                f"{result.plan.source_end_ms / 1000:.3f}s"
            )
            typer.echo(f"Title: {result.plan.title}")
    except typer.Exit:
        raise
    except (BootstrapError, ValidationError, ValueError, RuntimeError, LookupError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def rerender(
    clip_id: str,
    wait: Annotated[
        bool,
        typer.Option("--wait/--no-wait", help="Render in this foreground process."),
    ] = True,
) -> None:
    """Queue the approved current revision for a final portrait render."""

    settings = get_settings()
    try:
        with LiveClipRuntime.open(settings) as runtime:
            current = runtime.review_service.get_clip(clip_id)
            queued = runtime.render_service.enqueue(
                clip_id,
                RenderRequest(
                    expected_revision=current.current_revision,
                    kind="final",
                ),
            )
            typer.echo(f"Render ID: {queued.render_id}")
            typer.echo(f"Task ID: {queued.task_id}")
            if not wait:
                typer.echo(f"Render status: {queued.status.value}")
                return
            completed = runtime.render_runner.run_until_terminal(
                queued.render_id,
                worker_id=local_worker_id("foreground-render"),
            )
            typer.echo(f"Render status: {completed.status.value}")
            if completed.status != RenderStatus.SUCCEEDED:
                raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except (BootstrapError, ValidationError, ValueError, RuntimeError, LookupError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def deliver(
    project_id: str,
    include_zip: Annotated[
        bool,
        typer.Option("--zip/--no-zip", help="Include the immutable delivery ZIP."),
    ] = True,
    wait: Annotated[
        bool,
        typer.Option("--wait/--no-wait", help="Package in this foreground process."),
    ] = True,
) -> None:
    """Create a new immutable delivery version for all eligible clips."""

    settings = get_settings()
    try:
        with LiveClipRuntime.open(settings) as runtime:
            queued = runtime.delivery_service.enqueue(
                project_id,
                DeliveryRequest(include_zip=include_zip),
            )
            typer.echo(f"Delivery ID: {queued.delivery_id}")
            typer.echo(f"Delivery version: {queued.delivery_version}")
            typer.echo(f"Task ID: {queued.task_id}")
            if not wait:
                typer.echo(f"Delivery status: {queued.status.value}")
                return
            completed = runtime.delivery_runner.run_until_terminal(
                queued.delivery_id,
                worker_id=local_worker_id("foreground-delivery"),
            )
            typer.echo(f"Delivery status: {completed.status.value}")
            if completed.status != DeliveryStatus.SUCCEEDED:
                raise typer.Exit(code=1)
            directory = runtime.data_dir / project_id / "deliveries" / completed.delivery_version
            typer.echo(f"Delivery directory: {directory.resolve(strict=True)}")
            if completed.zip_asset_id is not None:
                archive = runtime.media_asset_service.resolve(
                    completed.zip_asset_id,
                    required_kind="delivery_zip",
                )
                typer.echo(f"Delivery ZIP: {archive.path}")
    except typer.Exit:
        raise
    except (BootstrapError, ValidationError, ValueError, RuntimeError, LookupError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def worker(
    once: Annotated[
        bool, typer.Option("--once", help="Process at most one ready stage task.")
    ] = False,
) -> None:
    """Run the independent SQLite-leased local worker."""

    try:
        raise typer.Exit(code=run_worker(get_settings(), once=once))
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        typer.echo("LiveClip worker stopped")
    except (BootstrapError, ValueError, RuntimeError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def demo() -> None:
    """Run the no-key, real-media Mock acceptance pipeline in the foreground."""

    settings = get_settings()
    try:
        result = run_demo(project_root=Path.cwd(), settings=settings)
    except DemoRunError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Project ID: {result.project_id}")
    typer.echo(f"Project status: {result.project_status}")
    typer.echo(f"Candidates: {result.candidate_count}")
    typer.echo(f"Source video: {result.source_video.resolve()}")
    typer.echo(f"Final video: {result.final_video.resolve()}")
    typer.echo(f"Contact sheet: {result.contact_sheet.resolve()}")
    typer.echo(f"Quality report: {result.quality_report.resolve()}")
    typer.echo(f"Delivery directory: {result.delivery_dir.resolve()}")
    typer.echo(f"Delivery ZIP: {result.delivery_zip.resolve()}")


@app.command("smoke-cloud")
def smoke_cloud(
    input_path: Annotated[Path, typer.Option("--input", help="Absolute short test video.")],
) -> None:
    """Run strict real OpenAI ASR and Responses checks; never fall back to Mock."""

    try:
        result = run_cloud_smoke(
            settings=get_settings(),
            input_path=input_path,
            project_root=Path.cwd(),
        )
    except (CloudSmokeError, BootstrapError, ValidationError, ValueError, RuntimeError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("Cloud smoke: succeeded")
    typer.echo(f"Project ID: {result.project_id}")
    typer.echo(f"Pipeline run ID: {result.run_id}")
    typer.echo(f"OpenAI ASR model: {result.asr_model}")
    typer.echo(f"OpenAI LLM model: {result.llm_model}")
    typer.echo(f"ASR request IDs: {', '.join(result.asr_request_ids)}")
    typer.echo(f"LLM request IDs: {', '.join(result.llm_request_ids)}")
    typer.echo(f"Selected non-degraded clips: {result.selected_clip_count}")


@app.command()
def clean_demo() -> None:
    """Delete only validated LiveClip-generated content below data/demo."""

    settings = get_settings()
    try:
        removed = clean_demo_contents(
            project_root=Path.cwd(),
            allowed_media_roots=settings.allowed_media_roots,
        )
    except DemoMediaError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Removed {removed} generated Demo entries from data/demo")


def _safe_cli_error(exc: Exception) -> str:
    message = str(exc).replace("\r", " ").replace("\n", " ").strip()
    if not message or len(message) > 500:
        return "LiveClip operation failed; inspect local diagnostics"
    return message
