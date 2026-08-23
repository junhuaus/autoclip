from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

import typer
from pydantic import ValidationError

from liveclip import __version__
from liveclip.application.deliveries import DeliveryRequest
from liveclip.application.media_assets import MediaAssetInvalid, MediaAssetNotFound
from liveclip.application.offline_review import OfflineReviewPackageConflict
from liveclip.application.reviewing import ClipPatch, RenderRequest, ReviewCommand
from liveclip.bootstrap import (
    BootstrapError,
    LiveClipRuntime,
    local_worker_id,
    pipeline_config_from_settings,
)
from liveclip.cli.doctor import DoctorReport, run_doctor
from liveclip.clipping_skills.semantic_global_v1 import load_semantic_global_prompt
from liveclip.clipping_skills.semantic_windowed_v1 import (
    load_semantic_windowed_discovery_prompt,
)
from liveclip.config import get_settings
from liveclip.db.engine import create_sqlite_engine
from liveclip.domain.edit_plan import CaptionCue
from liveclip.domain.state_transitions import (
    DeliveryStatus,
    PipelineRunStatus,
    RenderStatus,
    ReviewStatus,
)
from liveclip.domain.time import seconds_to_ms
from liveclip.media.ingest import resolve_allowed_source
from liveclip.pipeline.semantic_global import SemanticGlobalConfig
from liveclip.providers.readiness import require_processing_ready
from liveclip.services.cloud_smoke import CloudSmokeError, run_cloud_smoke
from liveclip.services.codex_smoke import CodexSmokeError, run_codex_smoke
from liveclip.services.database_backup import (
    DatabaseBackupError,
    backup_database,
    default_backup_path,
    restore_database,
)
from liveclip.services.demo import DemoRunError, run_demo
from liveclip.services.demo_media import DemoMediaError, clean_demo_contents
from liveclip.services.openrouter_smoke import OpenRouterSmokeError, run_openrouter_smoke
from liveclip.services.semantic_delivery import render_reviewed_semantic_delivery
from liveclip.services.semantic_evaluation import run_semantic_evaluation
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


@app.command("db-backup")
def db_backup(
    output: Annotated[
        Path | None,
        typer.Option("--output", help="New backup filename; existing files are never replaced."),
    ] = None,
    label: Annotated[
        str,
        typer.Option("--label", help="Short lowercase label used by the default backup name."),
    ] = "operator",
) -> None:
    """Create and validate a WAL-consistent, no-clobber SQLite backup."""

    settings = get_settings()
    data_dir = settings.resolved_data_dir(Path.cwd())
    database_path = data_dir / "liveclip.sqlite3"
    if not database_path.is_file():
        typer.echo("LiveClip database does not exist", err=True)
        raise typer.Exit(code=1)
    try:
        destination = output or default_backup_path(data_dir, label=label)
        engine = create_sqlite_engine(database_path)
        try:
            result = backup_database(engine, destination)
        finally:
            engine.dispose(close=True)
    except (DatabaseBackupError, RuntimeError, ValueError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Backup: {result.path}")
    typer.echo(f"SHA-256: {result.sha256}")
    typer.echo(f"Alembic revision: {result.alembic_revision}")
    typer.echo("Integrity: quick_check=ok, foreign_key_check=0")


@app.command("db-restore")
def db_restore(
    backup: Annotated[Path, typer.Option("--backup", help="Validated SQLite backup file.")],
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            help="New database filename. Stop services first; existing files are never replaced.",
        ),
    ],
) -> None:
    """Restore a validated backup to a new file without replacing the live database."""

    try:
        result = restore_database(backup, output)
    except (DatabaseBackupError, RuntimeError, ValueError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Restored database: {result.path}")
    typer.echo(f"SHA-256: {result.sha256}")
    typer.echo(f"Alembic revision: {result.alembic_revision}")
    typer.echo("Integrity: quick_check=ok, foreign_key_check=0")


@app.command("run")
def run_pipeline(
    input_path: Annotated[Path, typer.Option("--input", help="Absolute local source video path.")],
    top_n: Annotated[
        int | None,
        typer.Option("--top-n", "--max-clips", min=1, max=100),
    ] = None,
    minimum_seconds: Annotated[
        int | None,
        typer.Option("--min-seconds", "--min-duration", min=1, max=600),
    ] = None,
    maximum_seconds: Annotated[
        int | None,
        typer.Option("--max-seconds", "--max-duration", min=1, max=1_800),
    ] = None,
    algorithm: Annotated[
        Literal["a", "b", "b_v2_experimental", "semantic_global", "semantic_windowed"],
        typer.Option(
            "--algorithm",
            help=("a, b (frozen v1), b_v2_experimental, semantic_global, or semantic_windowed."),
        ),
    ] = "a",
    semantic_profile: Annotated[
        Literal["general", "vocal_coach_live"],
        typer.Option("--profile"),
    ] = "general",
    semantic_score_threshold: Annotated[
        float | None,
        typer.Option("--semantic-threshold", "--score-threshold", min=0, max=100),
    ] = None,
    semantic_target_seconds: Annotated[
        int | None,
        typer.Option("--semantic-target-seconds", "--target-duration", min=1, max=600),
    ] = None,
    semantic_full_context_budget_ratio: Annotated[
        float,
        typer.Option("--full-context-budget-ratio", min=0.1, max=0.8),
    ] = 0.58,
    semantic_model_context_tokens: Annotated[
        int,
        typer.Option("--model-context-tokens", min=16_000, max=2_000_000),
    ] = 128_000,
    prompt_debug: Annotated[
        bool,
        typer.Option("--prompt-debug", help="Print prompt identity and budget metadata only."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate configuration without creating a PipelineRun."),
    ] = False,
    no_render: Annotated[
        bool,
        typer.Option("--no-render", help="Create the final semantic plan but skip FFmpeg renders."),
    ] = False,
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
        if not dry_run:
            require_processing_ready(settings)
        config = pipeline_config_from_settings(
            settings,
            top_n=top_n,
            minimum_clip_seconds=minimum_seconds,
            maximum_clip_seconds=maximum_seconds,
            clipping_algorithm=algorithm,
            semantic_target_clip_seconds=semantic_target_seconds,
            semantic_score_threshold=semantic_score_threshold,
            semantic_profile=semantic_profile,
            semantic_full_context_budget_ratio=semantic_full_context_budget_ratio,
            semantic_model_context_tokens=semantic_model_context_tokens,
            semantic_no_render=no_render,
            semantic_prompt_debug=prompt_debug,
        )
        if prompt_debug and algorithm in {"semantic_global", "semantic_windowed"}:
            for stage in ("discovery", "global_review"):
                bundle = (
                    load_semantic_windowed_discovery_prompt(semantic_profile)
                    if algorithm == "semantic_windowed" and stage == "discovery"
                    else load_semantic_global_prompt(stage, semantic_profile)
                )
                typer.echo(
                    json.dumps(
                        {
                            "stage": stage,
                            "profile": semantic_profile,
                            "version": f"{bundle.version}.{stage}",
                            "sha256": bundle.sha256,
                            "loaded_files": bundle.loaded_files,
                            "model_context_tokens": config.semantic_model_context_tokens,
                            "full_context_budget_ratio": (
                                config.semantic_full_context_budget_ratio
                            ),
                            "tokenizer": config.semantic_tokenizer_name,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
        if dry_run:
            typer.echo(f"Configuration valid: {config.clipping_algorithm}")
            typer.echo(f"Config fingerprint: {config.fingerprint}")
            return
        with LiveClipRuntime.open(settings) as runtime:
            source_path = resolve_allowed_source(
                input_path,
                settings.allowed_media_roots,
                forbidden_roots=(settings.resolved_data_dir(Path.cwd()),),
            )
            created = runtime.pipeline_service.create_project_and_run(
                source_path=source_path,
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


@app.command("semantic-eval")
def semantic_eval(
    transcript: Annotated[
        Path,
        typer.Option("--transcript", help="Timestamped SRT transcript to evaluate."),
    ],
    output: Annotated[
        Path,
        typer.Option("--output", help="New output directory; existing paths are never replaced."),
    ],
    provider: Annotated[
        Literal["configured", "mock"],
        typer.Option("--provider", help="Use configured real LLM or deterministic mock."),
    ] = "configured",
    algorithm: Annotated[
        Literal["semantic_global", "semantic_windowed"],
        typer.Option("--algorithm"),
    ] = "semantic_global",
    profile: Annotated[
        Literal["general", "vocal_coach_live"],
        typer.Option("--profile"),
    ] = "vocal_coach_live",
    minimum_seconds: Annotated[int, typer.Option("--min-duration", min=1, max=600)] = 45,
    target_seconds: Annotated[int, typer.Option("--target-duration", min=1, max=600)] = 60,
    maximum_seconds: Annotated[int, typer.Option("--max-duration", min=1, max=600)] = 90,
    threshold: Annotated[float, typer.Option("--score-threshold", min=0, max=100)] = 75,
    max_clips: Annotated[int, typer.Option("--max-clips", min=1, max=100)] = 15,
    model_context_tokens: Annotated[
        int,
        typer.Option("--model-context-tokens", min=16_000, max=2_000_000),
    ] = 128_000,
    full_context_budget_ratio: Annotated[
        float,
        typer.Option("--full-context-budget-ratio", min=0.1, max=0.8),
    ] = 0.58,
    baseline: Annotated[
        Path | None,
        typer.Option("--baseline", help="Optional prior evaluation directory for the report."),
    ] = None,
    reuse_discovery_from: Annotated[
        Path | None,
        typer.Option(
            "--reuse-discovery-from",
            help=(
                "Reuse compatible validated Discovery output; window mode can resume exact "
                "completed batches from a failed run."
            ),
        ),
    ] = None,
    reuse_global_review_from: Annotated[
        Path | None,
        typer.Option(
            "--reuse-global-review-from",
            help="Reuse one compatible validated Global Review and run later validation stages.",
        ),
    ] = None,
    boundary_refinement: Annotated[
        bool,
        typer.Option(
            "--boundary-refinement/--no-boundary-refinement",
            help="Run the experimental score-neutral boundary re-check.",
        ),
    ] = False,
    discovery_reasoning_effort: Annotated[
        Literal["low", "medium", "high", "xhigh"],
        typer.Option(
            "--discovery-reasoning-effort",
            help="Codex reasoning effort for Discovery.",
        ),
    ] = "medium",
    global_review_reasoning_effort: Annotated[
        Literal["low", "medium", "high", "xhigh"],
        typer.Option(
            "--global-review-reasoning-effort",
            help="Codex reasoning effort for Global Review.",
        ),
    ] = "medium",
) -> None:
    """Evaluate a semantic clipping mode from an existing transcript without FFmpeg."""

    try:
        result = run_semantic_evaluation(
            transcript_path=transcript,
            output_dir=output,
            settings=get_settings(),
            profile=profile,
            provider_mode=provider,
            baseline_dir=baseline,
            discovery_cache_dir=reuse_discovery_from,
            global_review_cache_dir=reuse_global_review_from,
            boundary_refinement_enabled=boundary_refinement,
            discovery_reasoning_effort=discovery_reasoning_effort,
            global_review_reasoning_effort=global_review_reasoning_effort,
            algorithm=algorithm,
            config=SemanticGlobalConfig(
                minimum_duration_ms=minimum_seconds * 1_000,
                target_duration_ms=target_seconds * 1_000,
                maximum_duration_ms=maximum_seconds * 1_000,
                score_threshold_exclusive=threshold,
                max_clips=max_clips,
                model_context_tokens=model_context_tokens,
                full_context_budget_ratio=full_context_budget_ratio,
            ),
        )
    except (ValidationError, ValueError, RuntimeError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


@app.command("semantic-deliver")
def semantic_deliver(
    source: Annotated[Path, typer.Option("--source", help="Absolute source media path.")],
    transcript: Annotated[Path, typer.Option("--transcript", help="Timestamped SRT evidence.")],
    plan: Annotated[Path, typer.Option("--plan", help="Validated semantic clipping plan.")],
    review: Annotated[Path, typer.Option("--review", help="Auditable offline review JSON.")],
    output: Annotated[
        Path,
        typer.Option("--output", help="New output directory; existing paths are not replaced."),
    ],
    reuse_renders_from: Annotated[
        Path | None,
        typer.Option(
            "--reuse-renders-from",
            help="Prior reviewed-render-manifest.json; only exact source/range matches are reused.",
        ),
    ] = None,
) -> None:
    """Render reviewed semantic clips and create a browsable delivery package."""

    if not source.is_absolute() or ".." in source.parts:
        typer.echo("--source must be an absolute path without '..'", err=True)
        raise typer.Exit(code=2)
    settings = get_settings()
    try:
        result = render_reviewed_semantic_delivery(
            source_path=source,
            transcript_path=transcript,
            plan_path=plan,
            review_path=review,
            output_dir=output,
            allowed_media_roots=settings.allowed_media_roots,
            reuse_render_manifest_path=reuse_renders_from,
        )
    except (ValidationError, ValueError, RuntimeError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Verified delivery clips: {result.rendered_clip_count}")
    typer.echo(f"New renders: {result.new_render_count}")
    typer.echo(f"Reused verified renders: {result.reused_render_count}")
    typer.echo(f"Review manifest: {result.review_manifest_path}")
    typer.echo(f"Delivery index: {result.delivery.directory / 'index.html'}")
    typer.echo(f"Delivery ZIP: {result.delivery.zip_path}")


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
                detail = runtime.review_service.get_clip(clip.clip_id)
                typer.echo(
                    f"{clip.clip_id} | {clip.review_status.value} | "
                    f"{clip.source_start_ms / 1000:.3f}-{clip.source_end_ms / 1000:.3f}s | "
                    f"{clip.score:.1f} | {clip.title}"
                )
                typer.echo(f"  Hook: {detail.plan.hook}")
                typer.echo(f"  Reason: {clip.reason}")
                typer.echo(
                    "  Risk flags: " + (", ".join(clip.risk_flags) if clip.risk_flags else "none")
                )
                proxy_status = clip.proxy_status.value if clip.proxy_status else "not_rendered"
                typer.echo(f"  Proxy status: {proxy_status}")
                typer.echo(f"  Captions ({len(detail.captions)}, clip-relative):")
                for index, cue in enumerate(detail.captions, start=1):
                    typer.echo(
                        f"    {index:02d} | {cue.start_ms / 1000:.3f}-"
                        f"{cue.end_ms / 1000:.3f}s | {cue.text}"
                    )
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
            typer.echo(f"Hook: {result.plan.hook}")
            typer.echo(f"Captions ({len(result.captions)}, clip-relative):")
            for index, cue in enumerate(result.captions, start=1):
                typer.echo(
                    f"  {index:02d} | {cue.start_ms / 1000:.3f}-"
                    f"{cue.end_ms / 1000:.3f}s | {cue.text}"
                )
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
    """Queue the current revision for a clean review and delivery master render."""

    settings = get_settings()
    try:
        with LiveClipRuntime.open(settings) as runtime:
            current = runtime.review_service.get_clip(clip_id)
            queued = runtime.render_service.enqueue(
                clip_id,
                RenderRequest(
                    expected_revision=current.current_revision,
                    kind="proxy",
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


@app.command("export-review")
def export_review(
    project_id: str,
    include_zip: Annotated[
        bool,
        typer.Option("--zip/--no-zip", help="Include the self-contained offline ZIP."),
    ] = True,
) -> None:
    """Export current clean proxies and editorial descriptions for offline review."""

    settings = get_settings()
    try:
        with LiveClipRuntime.open(settings) as runtime:
            result = runtime.offline_review_package_service.create(
                project_id,
                include_zip=include_zip,
            )
            typer.echo(f"Offline review package: {result.package_id}")
            typer.echo(f"Package version: {result.package_version}")
            typer.echo(f"Clips: {result.clip_count}")
            typer.echo(f"Package directory: {result.directory.resolve(strict=True)}")
            typer.echo(f"Offline page: {result.index_path.resolve(strict=True)}")
            typer.echo(f"Manifest: {result.manifest_path.resolve(strict=True)}")
            typer.echo(f"Manifest SHA-256: {result.manifest_sha256}")
            if result.zip_path is not None:
                typer.echo(f"Package ZIP: {result.zip_path.resolve(strict=True)}")
                typer.echo(f"Package ZIP SHA-256: {result.zip_sha256}")
            typer.echo("Review state unchanged: this package is not a formal approved delivery")
    except (
        BootstrapError,
        OfflineReviewPackageConflict,
        ValidationError,
        ValueError,
        RuntimeError,
        LookupError,
    ) as exc:
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
    typer.echo(f"Delivery master: {result.final_video.resolve()}")
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


@app.command("smoke-codex")
def smoke_codex() -> None:
    """Run one real tool-disabled Codex editorial call using saved CLI login."""

    try:
        result = run_codex_smoke(get_settings())
    except (CodexSmokeError, ValidationError, ValueError, RuntimeError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("Codex smoke: succeeded")
    typer.echo(f"Provider: {result.provider}")
    typer.echo(f"Model: {result.model}")
    typer.echo(f"Codex thread ID: {result.thread_id}")
    typer.echo(f"Usage: input={result.input_tokens} output={result.output_tokens}")
    typer.echo(f"Score: {result.score}")
    typer.echo(f"Title: {result.title}")
    typer.echo(f"Boundary: {result.source_start_ms}-{result.source_end_ms} ms")


@app.command("smoke-openrouter")
def smoke_openrouter(
    input_path: Annotated[Path, typer.Option("--input", exists=False, dir_okay=False)],
) -> None:
    """Prove real OpenRouter Whisper ASR followed by real local Codex editing."""

    try:
        result = run_openrouter_smoke(
            settings=get_settings(),
            input_path=input_path,
            project_root=Path.cwd(),
        )
    except (OpenRouterSmokeError, BootstrapError, ValidationError, ValueError, RuntimeError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("OpenRouter + Codex smoke: succeeded")
    typer.echo(f"Project ID: {result.project_id}")
    typer.echo(f"Run ID: {result.run_id}")
    typer.echo(f"ASR model: {result.asr_model}")
    typer.echo(f"Codex model: {result.llm_model}")
    typer.echo(f"ASR generation IDs: {', '.join(result.asr_generation_ids)}")
    typer.echo(f"Codex thread IDs: {', '.join(result.codex_thread_ids)}")
    typer.echo(f"Selected clips: {result.selected_clip_count}")


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
