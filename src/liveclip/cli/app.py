from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

import typer
from pydantic import ValidationError

from liveclip import __version__
from liveclip.application.completion import CompletionOptions
from liveclip.application.completion_presets import resolve_completion_preset
from liveclip.application.deliveries import DeliveryRequest
from liveclip.application.idempotency import build_idempotency_context
from liveclip.application.media_assets import MediaAssetInvalid, MediaAssetNotFound
from liveclip.application.offline_review import OfflineReviewPackageConflict
from liveclip.application.pipeline import PipelineService, RunSnapshot
from liveclip.application.reviewing import ClipPatch, RenderRequest, ReviewCommand
from liveclip.application.selection import SelectionMode, SelectionResult
from liveclip.application.stage_runner import StageTaskRunner
from liveclip.bootstrap import (
    BootstrapError,
    LiveClipRuntime,
    local_worker_id,
    pipeline_config_from_settings,
)
from liveclip.cli.completion_watch import observe_completion
from liveclip.cli.doctor import DoctorReport, run_doctor
from liveclip.clipping_skills.semantic_global_v1 import load_semantic_global_prompt
from liveclip.clipping_skills.semantic_global_v2 import load_installed_global_review_prompt
from liveclip.clipping_skills.semantic_global_v3 import (
    load_semantic_global_v3_boundary_prompt,
)
from liveclip.clipping_skills.semantic_topic_chain_v1 import (
    load_semantic_topic_chain_prompt,
)
from liveclip.clipping_skills.semantic_windowed_v2 import (
    load_installed_semantic_windowed_discovery_prompt,
)
from liveclip.config import get_settings
from liveclip.db.engine import create_sqlite_engine
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.completion import CompletionSelectionPolicy
from liveclip.domain.edit_plan import CaptionCue
from liveclip.domain.state_transitions import (
    DeliveryStatus,
    PipelineRunStatus,
    PipelineStage,
    RenderStatus,
    ReviewStatus,
    StageRunStatus,
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

_PROGRESS_REPORT_INTERVAL_SECONDS = 2.0

_AUTO_TOP_N = 15
_AUTO_MINIMUM_SECONDS = 45
_AUTO_MAXIMUM_SECONDS = 90
_AUTO_TARGET_SECONDS = 60
_AUTO_SCORE_THRESHOLD = 75.0

_STAGE_TEXT = {
    PipelineStage.INGEST.value: "素材接入",
    PipelineStage.PREPROCESS.value: "音频预处理",
    PipelineStage.TRANSCRIBE.value: "语音转写",
    PipelineStage.CANDIDATES.value: "候选发现",
    PipelineStage.EDIT.value: "全局筛选",
    PipelineStage.PROXY_RENDER.value: "切片渲染",
}

_STATUS_MARK = {
    StageRunStatus.QUEUED: "○",
    StageRunStatus.RUNNING: "▶",
    StageRunStatus.SUCCEEDED: "✓",
    StageRunStatus.SKIPPED: "-",
    StageRunStatus.FAILED: "✗",
    StageRunStatus.CANCELLED: "x",
}

_STATUS_TEXT = {
    StageRunStatus.QUEUED: "等待",
    StageRunStatus.RUNNING: "进行中",
    StageRunStatus.SUCCEEDED: "完成",
    StageRunStatus.SKIPPED: "跳过",
    StageRunStatus.FAILED: "失败",
    StageRunStatus.CANCELLED: "已取消",
}

_STAGE_HINT = {
    PipelineStage.INGEST.value: "正在校验并接入源视频",
    PipelineStage.PREPROCESS.value: "正在提取并分割音频",
    PipelineStage.TRANSCRIBE.value: "正在并行转写音频块",
    PipelineStage.CANDIDATES.value: "Discovery 正在理解直播内容",
    PipelineStage.EDIT.value: "Global Review 正在筛选高光与边界",
    PipelineStage.PROXY_RENDER.value: "FFmpeg 正在生成竖屏干净切片",
}

_SPINNER = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class _TerminalDashboard:
    """Keep foreground progress in one terminal region when stdout is a TTY."""

    def __init__(self) -> None:
        self.interactive = bool(getattr(sys.stdout, "isatty", lambda: False)())
        self._line_count = 0
        self._lock = threading.Lock()

    def open(self) -> None:
        if self.interactive:
            sys.stdout.write("\x1b[?25l")
            sys.stdout.flush()

    def show(self, frame: str) -> None:
        with self._lock:
            if not self.interactive:
                typer.echo(frame)
                return
            if self._line_count:
                sys.stdout.write(f"\x1b[{self._line_count}F")
            sys.stdout.write("\x1b[J")
            sys.stdout.write(frame.rstrip("\n") + "\n")
            sys.stdout.flush()
            self._line_count = len(frame.splitlines())

    def close(self) -> None:
        if self.interactive:
            with self._lock:
                sys.stdout.write("\x1b[?25h")
                sys.stdout.flush()


def _progress_bar(progress: int, *, width: int = 24) -> str:
    completed = min(width, max(0, round(progress * width / 100)))
    return "█" * completed + "░" * (width - completed)


def _format_pipeline_text_ui(
    snapshot: RunSnapshot,
    *,
    elapsed_seconds: int | None,
    selection_counts: tuple[int, int, int] | None = None,
    delivery_status: DeliveryStatus | None = None,
) -> str:
    """Render one stable, ANSI-free terminal dashboard frame."""

    lines = [
        "╭─ LiveClip 切片流水线",
        f"│ Project  {snapshot.project_id}",
        f"│ Run      {snapshot.run_id}",
        f"│ 自动处理 [{_progress_bar(snapshot.progress)}] {snapshot.progress:3d}%",
        "├────────────────────────────────────────────────────────",
    ]
    for index, stage in enumerate(snapshot.stages, start=1):
        label = _STAGE_TEXT.get(stage.stage, stage.stage)
        marker = _STATUS_MARK[stage.status]
        detail = f"{marker} {index}/8  {label:<10} {stage.status.value:<10} {stage.progress:3d}%"
        if stage.retry_count:
            detail += f"  重试 {stage.retry_count}"
        if stage.error_code:
            detail += f"  [{stage.error_code}]"
        lines.append(f"│ {detail}")
    if selection_counts is None:
        selection_marker = "▶" if snapshot.status == PipelineRunStatus.COMPLETED else "○"
        selection_detail = "ready" if snapshot.status == PipelineRunStatus.COMPLETED else "waiting"
    else:
        candidate_count, selected_count, pending_count = selection_counts
        selection_marker = "✓" if pending_count == 0 and selected_count > 0 else "▶"
        selection_detail = f"selected={selected_count}/{candidate_count}, pending={pending_count}"
    lines.append(f"│ {selection_marker} 7/8  {'切片选择':<10} {selection_detail}")
    delivery_marker = "○"
    delivery_detail = "waiting"
    if delivery_status is not None:
        delivery_detail = delivery_status.value
        if delivery_status == DeliveryStatus.SUCCEEDED:
            delivery_marker = "✓"
        elif delivery_status == DeliveryStatus.FAILED:
            delivery_marker = "✗"
        else:
            delivery_marker = "▶"
    lines.append(f"│ {delivery_marker} 8/8  {'生成交付包':<10} {delivery_detail}")
    if elapsed_seconds is not None:
        minutes, seconds = divmod(max(0, elapsed_seconds), 60)
        lines.append(f"│ 已用时   {minutes:02d}:{seconds:02d}")
    if snapshot.status == PipelineRunStatus.COMPLETED:
        lines.append("│ 下一步   选择切片并生成交付包: liveclip select PROJECT_ID")
    elif snapshot.status == PipelineRunStatus.FAILED:
        lines.append("│ 下一步   修复错误后执行: liveclip retry RUN_ID --wait")
    lines.append("╰────────────────────────────────────────────────────────")
    return "\n".join(lines)


def _format_elapsed(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3_600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _seconds_since(value: datetime | None) -> int | None:
    if value is None:
        return None
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - normalized).total_seconds()))


def _timestamp_expired(value: datetime | None) -> bool:
    if value is None:
        return False
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized <= datetime.now(UTC)


def _format_pipeline_dashboard(
    snapshot: RunSnapshot,
    *,
    elapsed_seconds: int | None,
    selection_counts: tuple[int, int, int] | None = None,
    delivery_status: DeliveryStatus | None = None,
    pulse: int = 0,
) -> str:
    """Render the compact eight-step dashboard frame without control characters."""

    active_stage = next(
        (stage for stage in snapshot.stages if stage.status == StageRunStatus.RUNNING),
        None,
    )
    lease_expired = _timestamp_expired(snapshot.active_task_lease_expires_at)
    heartbeat_age = _seconds_since(snapshot.active_task_heartbeat_at)
    lines = [
        "╭─ LiveClip 自动切片",
        f"│ Project  {snapshot.project_id}",
        f"│ Run      {snapshot.run_id}",
        f"│ 总进度  [{_progress_bar(snapshot.progress, width=28)}] {snapshot.progress:3d}%",
    ]
    if lease_expired and snapshot.cancellation_requested:
        lines.append("│ 状态    取消已记录 · Worker 心跳已过期 · 等待恢复器回收")
    elif lease_expired:
        lines.append("│ 状态    Worker 心跳已过期 · 任务未在运行 · 等待恢复")
    elif snapshot.cancellation_requested:
        lines.append("│ 状态    正在安全停止 · 等待当前调用退出并保存已完成结果")
    elif heartbeat_age is not None:
        lines.append(f"│ 心跳    正常 · {_format_elapsed(heartbeat_age)} 前")
    if active_stage is not None:
        label = _STAGE_TEXT.get(active_stage.stage, active_stage.stage)
        unit_detail = ""
        if active_stage.completed_units is not None and active_stage.total_units is not None:
            unit_name = (
                "音频块" if active_stage.unit_label == "audio chunks" else active_stage.unit_label
            )
            unit_detail = (
                f" · {active_stage.completed_units}/{active_stage.total_units} {unit_name}"
            )
        elif active_stage.activity_count is not None:
            activity_name = (
                "模型调用"
                if active_stage.activity_label == "model calls"
                else active_stage.activity_label
            )
            unit_detail = f" · 已完成 {active_stage.activity_count} 次{activity_name}"
        stage_elapsed = _seconds_since(active_stage.started_at)
        elapsed_detail = (
            f" · 阶段用时 {_format_elapsed(stage_elapsed)}" if stage_elapsed is not None else ""
        )
        if lease_expired:
            active_label = "等待回收"
        elif snapshot.cancellation_requested:
            active_label = "停止中"
        else:
            active_label = label
        lines.extend(
            [
                f"│ 当前    {_SPINNER[pulse % len(_SPINNER)]} "
                f"{active_label}"
                f" · {active_stage.progress}%{unit_detail}{elapsed_detail}",
                (
                    "│          已完成结果已保留; 恢复器不会重复它们"
                    if lease_expired
                    else (
                        "│          正在撤销未完成调用; 已成功的缓存会保留"
                        if snapshot.cancellation_requested
                        else f"│          {_STAGE_HINT.get(active_stage.stage, '正在处理')}"
                    )
                ),
            ]
        )
    lines.append("├─────────────────────────────────────────────────────────────────")
    for index, stage in enumerate(snapshot.stages, start=1):
        label = _STAGE_TEXT.get(stage.stage, stage.stage)
        marker = _STATUS_MARK[stage.status]
        detail = (
            f"{marker} {index}/8  {label:<8} {_STATUS_TEXT[stage.status]:<5} "
            f"[{_progress_bar(stage.progress, width=10)}] {stage.progress:3d}%"
        )
        if stage.completed_units is not None and stage.total_units is not None:
            detail += f"  {stage.completed_units}/{stage.total_units}"
        elif stage.activity_count is not None:
            detail += f"  活动 {stage.activity_count}"
        if stage.retry_count:
            detail += f"  重试 {stage.retry_count}"
        if stage.error_code:
            detail += f"  [{stage.error_code}]"
        lines.append(f"│ {detail}")
    if selection_counts is None:
        selection_marker = "▶" if snapshot.status == PipelineRunStatus.COMPLETED else "○"
        selection_detail = "就绪" if snapshot.status == PipelineRunStatus.COMPLETED else "等待"
    else:
        candidate_count, selected_count, pending_count = selection_counts
        if pending_count == 0 and selected_count > 0:
            selection_marker = "✓"
        elif candidate_count > 0:
            selection_marker = "▶"
        else:
            selection_marker = "○"
        selection_detail = f"已选 {selected_count}/{candidate_count} · 待选 {pending_count}"
    lines.append(f"│ {selection_marker} 7/8  {'切片选择':<8} {selection_detail}")
    delivery_marker = "○"
    delivery_detail = "等待"
    if delivery_status is not None:
        delivery_detail = {
            DeliveryStatus.QUEUED: "等待",
            DeliveryStatus.CREATING: "生成中",
            DeliveryStatus.SUCCEEDED: "完成",
            DeliveryStatus.FAILED: "失败",
        }[delivery_status]
        if delivery_status == DeliveryStatus.SUCCEEDED:
            delivery_marker = "✓"
        elif delivery_status == DeliveryStatus.FAILED:
            delivery_marker = "✗"
        else:
            delivery_marker = "▶"
    lines.append(f"│ {delivery_marker} 8/8  {'生成交付包':<8} {delivery_detail}")
    if elapsed_seconds is not None:
        lines.append(
            f"│ 已用时  {_format_elapsed(elapsed_seconds)}"
            f" · 界面刷新 {datetime.now().astimezone().strftime('%H:%M:%S')}"
            " · Ctrl-C 安全停止"
        )
    if snapshot.status == PipelineRunStatus.COMPLETED:
        lines.append("│ 下一步   选择切片并生成交付包: liveclip select PROJECT_ID")
    elif snapshot.status == PipelineRunStatus.FAILED:
        lines.append("│ 下一步   修复错误后执行: liveclip retry RUN_ID --wait")
    lines.append("╰────────────────────────────────────────────────────────────────")
    return "\n".join(lines)


def _run_foreground_with_progress(
    *,
    pipeline_service: PipelineService,
    initial_snapshot: RunSnapshot,
    operation: Callable[[], RunSnapshot],
) -> RunSnapshot:
    started = time.monotonic()
    stopped = threading.Event()
    dashboard = _TerminalDashboard()
    pulse = 0

    def emit(snapshot: RunSnapshot) -> None:
        nonlocal pulse
        dashboard.show(
            _format_pipeline_dashboard(
                snapshot,
                elapsed_seconds=max(0, int(time.monotonic() - started)),
                pulse=pulse,
            )
        )
        pulse += 1

    dashboard.open()
    emit(initial_snapshot)

    def report() -> None:
        while not stopped.wait(_PROGRESS_REPORT_INTERVAL_SECONDS):
            with suppress(LookupError, RuntimeError):
                emit(pipeline_service.get_run(initial_snapshot.run_id))

    reporter = threading.Thread(
        target=report,
        name=f"liveclip-cli-progress-{initial_snapshot.run_id[:8]}",
        daemon=True,
    )
    reporter.start()
    try:
        result = operation()
        # Stop the reporter before the terminal frame. Otherwise it can race
        # with this emit and overwrite a completed snapshot with stale running
        # state after the foreground operation has already returned.
        stopped.set()
        reporter.join(timeout=1)
        emit(result)
        return result
    except KeyboardInterrupt:
        # A foreground interrupt must become durable cancellation intent. The
        # active lease monitor is interrupted first; a later worker will then
        # acknowledge this request instead of silently resuming abandoned work.
        with suppress(LookupError, RuntimeError):
            pipeline_service.cancel(initial_snapshot.run_id)
        raise
    finally:
        stopped.set()
        reporter.join(timeout=1)
        dashboard.close()


def _run_pipeline_with_progress(
    *,
    pipeline_service: PipelineService,
    stage_runner: StageTaskRunner,
    initial_snapshot: RunSnapshot,
    worker_id: str,
) -> RunSnapshot:
    """Run foreground stages while emitting the complete Pipeline text UI."""

    return _run_foreground_with_progress(
        pipeline_service=pipeline_service,
        initial_snapshot=initial_snapshot,
        operation=lambda: stage_runner.run_until_terminal(
            initial_snapshot.run_id,
            worker_id=worker_id,
        ),
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
    clip_profile: Annotated[
        ClipProfile,
        typer.Option(
            "--clip-profile",
            help="short_highlight (45-90s) or mini_lesson (90-300s).",
        ),
    ] = ClipProfile.SHORT_HIGHLIGHT,
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
    finish: Annotated[
        bool,
        typer.Option(
            "--finish",
            help="Default-select the generated clips and create the ZIP delivery.",
        ),
    ] = False,
) -> None:
    """Create a Project and optionally process it to rendered clip selection."""

    if not input_path.is_absolute() or ".." in input_path.parts:
        typer.echo("--input must be an absolute path without '..'", err=True)
        raise typer.Exit(code=2)
    if finish and (not wait or dry_run or no_render):
        typer.echo(
            "--finish requires --wait and cannot be used with --dry-run or --no-render", err=True
        )
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
            clip_profile=clip_profile,
            semantic_full_context_budget_ratio=semantic_full_context_budget_ratio,
            semantic_model_context_tokens=semantic_model_context_tokens,
            semantic_no_render=no_render,
            semantic_prompt_debug=prompt_debug,
        )
        if prompt_debug and algorithm in {"semantic_global", "semantic_windowed"}:
            stages = (
                (
                    "discovery",
                    "link_review",
                    "topic_chain",
                    "boundary_review",
                    "global_review",
                )
                if clip_profile == ClipProfile.MINI_LESSON
                else ("discovery", "boundary_review", "global_review")
                if config.semantic_global_review_skill_version == "semantic_global_v3.global_review"
                else ("discovery", "global_review")
            )
            for stage in stages:
                bundle = (
                    load_semantic_topic_chain_prompt(stage, semantic_profile, clip_profile)
                    if clip_profile == ClipProfile.MINI_LESSON
                    else load_installed_semantic_windowed_discovery_prompt(
                        config.semantic_discovery_skill_version,
                        semantic_profile,
                    )
                    if algorithm == "semantic_windowed" and stage == "discovery"
                    else load_installed_global_review_prompt(
                        config.semantic_global_review_skill_version,
                        semantic_profile,
                    )
                    if stage == "global_review"
                    else load_semantic_global_v3_boundary_prompt(semantic_profile)
                    if stage == "boundary_review"
                    else load_semantic_global_prompt(stage, semantic_profile)
                )
                typer.echo(
                    json.dumps(
                        {
                            "stage": stage,
                            "profile": semantic_profile,
                            "clip_profile": clip_profile.value,
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
            snapshot = _run_pipeline_with_progress(
                pipeline_service=runtime.pipeline_service,
                stage_runner=runtime.stage_runner,
                initial_snapshot=runtime.pipeline_service.get_run(created.run_id),
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
            if finish:
                selection = runtime.selection_service.select(
                    created.project_id,
                    mode=SelectionMode.DEFAULT,
                )
                _echo_selection_result(selection)
                _package_project(
                    runtime,
                    project_id=created.project_id,
                    include_zip=True,
                    wait=True,
                )
    except typer.Exit:
        raise
    except (BootstrapError, ValidationError, ValueError, RuntimeError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command("auto")
def auto_pipeline(
    input_path: Annotated[
        Path,
        typer.Argument(help="Absolute local source video path."),
    ],
    clip_profile: Annotated[
        ClipProfile,
        typer.Option(
            "--clip-profile",
            help="Use short_highlight by default or request a 90-300s mini_lesson run.",
        ),
    ] = ClipProfile.SHORT_HIGHLIGHT,
    request_key: Annotated[str | None, typer.Option("--request-key")] = None,
    selection_policy: Annotated[
        CompletionSelectionPolicy, typer.Option("--selection-policy")
    ] = CompletionSelectionPolicy.DEFAULT,
    watch: Annotated[bool, typer.Option("--watch/--no-watch")] = True,
) -> None:
    """Save a durable goal; an independent liveclip worker performs the work."""

    settings = get_settings()
    try:
        preset = resolve_completion_preset(f"{clip_profile.value}_v1")
        key = request_key if request_key is not None else f"liveclip-cli-{uuid4().hex}"
        with LiveClipRuntime.open(settings) as runtime:
            actor = runtime.workspace_service.get_user_by_username(settings.workspace_username)
            identity = build_idempotency_context(
                raw_key=key,
                caller_scope=f"cli:{actor.user_id}",
                operation_scope="completion:auto",
                request_payload={
                    "source": str(input_path),
                    "preset": preset.preset_id.value,
                    "selection_policy": selection_policy.value,
                },
            )
            typer.echo(f"Caller: {identity.caller_scope}\nRequest key: {key}")
            sys.stdout.flush()

            def readiness_guard() -> None:
                require_processing_ready(settings)

            config = pipeline_config_from_settings(
                settings,
                top_n=preset.top_n,
                minimum_clip_seconds=preset.minimum_clip_seconds,
                maximum_clip_seconds=preset.maximum_clip_seconds,
                clipping_algorithm=preset.clipping_algorithm,
                semantic_profile=preset.semantic_profile,
                clip_profile=preset.clip_profile,
                semantic_target_clip_seconds=preset.target_clip_seconds,
                semantic_score_threshold=preset.semantic_score_threshold,
                semantic_full_context_budget_ratio=preset.semantic_full_context_budget_ratio,
                semantic_model_context_tokens=preset.semantic_model_context_tokens,
            )
            goal = runtime.completion_service.create_project_and_run_with_goal(
                source_path=input_path,
                config=config,
                max_stage_retries=settings.max_stage_retries,
                actor_user_id=actor.user_id,
                options=CompletionOptions(
                    preset_id=preset.preset_id.value,
                    selection_policy=selection_policy,
                    include_zip=preset.include_zip,
                ),
                idempotency=identity,
                readiness_guard=readiness_guard,
            )
            observe_completion(runtime, goal.intent_id, actor.user_id, watch=watch)
    except typer.Exit:
        raise
    except (ValueError, RuntimeError, LookupError):
        typer.echo(
            "Completion request failed; retry the same key and options to recover.", err=True
        )
        raise typer.Exit(code=1) from None


@app.command("resume")
def resume_completion(
    project_id: Annotated[str, typer.Argument()],
    intent_id: Annotated[str | None, typer.Option("--intent-id")] = None,
    watch: Annotated[bool, typer.Option("--watch/--no-watch")] = True,
) -> None:
    """Reconnect to an existing goal; explicitly resume only needs_action."""
    settings = get_settings()
    try:
        with LiveClipRuntime.open(settings) as runtime:
            actor = runtime.workspace_service.get_user_by_username(settings.workspace_username)
            goals = runtime.completion_service.list_for_project(
                project_id, actor_user_id=actor.user_id
            )
            matches = [goal for goal in goals if intent_id is None or goal.intent_id == intent_id]
            if len(matches) != 1:
                typer.echo(
                    "Select one existing Project goal with --intent-id; "
                    "lookup is ambiguous or empty.",
                    err=True,
                )
                raise typer.Exit(code=2)
            goal = matches[0]
            if (
                goal.status.value == "needs_action"
                and goal.blocking_code != "COORDINATION_RETRIES_EXHAUSTED"
            ):
                runtime.completion_service.resume(
                    goal.intent_id, actor_user_id=actor.user_id, expected_version=goal.version
                )
            observe_completion(runtime, goal.intent_id, actor.user_id, watch=watch)
    except typer.Exit:
        raise
    except (ValueError, RuntimeError, LookupError):
        typer.echo(
            "Goal unavailable or resume conflicted; retry lookup with current authority.", err=True
        )
        raise typer.Exit(code=1) from None


@app.command("retry")
def retry_pipeline(
    run_id: Annotated[str, typer.Argument(help="Failed Pipeline run ID to resume.")],
    wait: Annotated[
        bool, typer.Option("--wait", help="Process the resumed run in this foreground process.")
    ] = False,
) -> None:
    """Resume a failed or cancelled run while reusing verified stages and provider caches."""

    settings = get_settings()
    try:
        with LiveClipRuntime.open(settings) as runtime:
            snapshot = runtime.pipeline_service.retry(run_id)
            typer.echo(f"Project ID: {snapshot.project_id}")
            typer.echo(f"Pipeline run ID: {snapshot.run_id}")
            if not wait:
                typer.echo(f"Pipeline status: {snapshot.status.value}")
                return
            snapshot = _run_pipeline_with_progress(
                pipeline_service=runtime.pipeline_service,
                stage_runner=runtime.stage_runner,
                initial_snapshot=snapshot,
                worker_id=local_worker_id("foreground-retry"),
            )
            project = runtime.pipeline_service.get_project(snapshot.project_id)
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
    except (BootstrapError, ValidationError, ValueError, RuntimeError, LookupError) as exc:
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
    ] = "high",
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
def status(
    project_id: str,
    watch: Annotated[
        bool,
        typer.Option("--watch", help="Refresh one terminal dashboard until the Pipeline stops."),
    ] = False,
) -> None:
    """Show or continuously watch the complete Pipeline text dashboard."""

    settings = get_settings()
    dashboard = _TerminalDashboard()
    started = time.monotonic()
    pulse = 0
    try:
        with LiveClipRuntime.open(settings) as runtime:
            dashboard.open()
            while True:
                project = runtime.pipeline_service.get_project(project_id)
                run = runtime.pipeline_service.get_run(project.current_run_id)
                project_clips = runtime.clip_query_service.list_project_clips(project_id)
                selected_count = sum(
                    value.review_status == ReviewStatus.APPROVED for value in project_clips
                )
                pending_count = sum(
                    value.review_status == ReviewStatus.PENDING_REVIEW for value in project_clips
                )
                deliveries = runtime.delivery_service.list(project_id)
                latest_delivery = max(deliveries, key=lambda value: value.version, default=None)
                dashboard.show(
                    f"Project status: {project.status.value}\n"
                    + _format_pipeline_dashboard(
                        run,
                        elapsed_seconds=(
                            max(0, int(time.monotonic() - started)) if watch else None
                        ),
                        selection_counts=(len(project_clips), selected_count, pending_count),
                        delivery_status=(
                            latest_delivery.status if latest_delivery is not None else None
                        ),
                        pulse=pulse,
                    )
                )
                pulse += 1
                if (
                    not watch
                    or run.status
                    in {
                        PipelineRunStatus.COMPLETED,
                        PipelineRunStatus.FAILED,
                        PipelineRunStatus.CANCELLED,
                    }
                    or _timestamp_expired(run.active_task_lease_expires_at)
                ):
                    break
                threading.Event().wait(_PROGRESS_REPORT_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        return
    except (BootstrapError, ValueError, RuntimeError, LookupError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc
    finally:
        dashboard.close()


def _run_until_stage(
    *,
    pipeline_service: PipelineService,
    stage_runner: StageTaskRunner,
    run_id: str,
    target: PipelineStage,
    worker_id: str,
) -> RunSnapshot:
    while True:
        snapshot = pipeline_service.get_run(run_id)
        target_snapshot = next(stage for stage in snapshot.stages if stage.stage == target.value)
        if target_snapshot.status in {
            StageRunStatus.SUCCEEDED,
            StageRunStatus.SKIPPED,
            StageRunStatus.FAILED,
            StageRunStatus.CANCELLED,
        }:
            return snapshot
        if snapshot.status in {
            PipelineRunStatus.FAILED,
            PipelineRunStatus.CANCELLED,
        }:
            return snapshot
        stage_runner.run_one(worker_id=worker_id, pipeline_run_id=run_id)
        threading.Event().wait(0.2)


@app.command("stage")
def run_stage(
    run_id: Annotated[str, typer.Argument(help="Pipeline run ID.")],
    stage: Annotated[
        Literal[
            "ingest",
            "preprocess",
            "transcribe",
            "candidates",
            "edit",
            "proxy_render",
        ],
        typer.Argument(help="Target stage; unmet dependencies are run first."),
    ],
) -> None:
    """Run exactly through one named Pipeline stage and then stop."""

    settings = get_settings()
    try:
        require_processing_ready(settings)
        with LiveClipRuntime.open(settings) as runtime:
            initial = runtime.pipeline_service.get_run(run_id)
            target = PipelineStage(stage)
            completed = _run_foreground_with_progress(
                pipeline_service=runtime.pipeline_service,
                initial_snapshot=initial,
                operation=lambda: _run_until_stage(
                    pipeline_service=runtime.pipeline_service,
                    stage_runner=runtime.stage_runner,
                    run_id=run_id,
                    target=target,
                    worker_id=local_worker_id(f"foreground-{target.value}"),
                ),
            )
            target_snapshot = next(
                value for value in completed.stages if value.stage == target.value
            )
            if target_snapshot.status not in {
                StageRunStatus.SUCCEEDED,
                StageRunStatus.SKIPPED,
            }:
                raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except (BootstrapError, ValidationError, ValueError, RuntimeError, LookupError) as exc:
        typer.echo(_safe_cli_error(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def clips(project_id: str) -> None:
    """List candidate clips and their current user-selection state."""

    settings = get_settings()
    try:
        with LiveClipRuntime.open(settings) as runtime:
            values = runtime.clip_query_service.list_project_clips(project_id)
            if not values:
                typer.echo("No candidate clips are available")
                return
            for clip in values:
                detail = runtime.review_service.get_clip(clip.clip_id)
                typer.echo(
                    f"{clip.clip_id} | selection={clip.review_status.value} | "
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
    """Compatibility command: edit and select or exclude one clip revision."""

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
            typer.echo(f"Selection status: {result.review.status.value}")
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


def _resolve_manual_selection(
    raw: str,
    *,
    clip_ids: Sequence[str],
) -> tuple[str, ...]:
    normalized = raw.strip()
    if normalized.casefold() in {"", "none"}:
        return ()
    resolved: list[str] = []
    for token in (value.strip() for value in normalized.split(",")):
        if not token:
            continue
        if token.isdecimal():
            index = int(token)
            if index < 1 or index > len(clip_ids):
                raise ValueError("manual selection index is outside the candidate list")
            clip_id = clip_ids[index - 1]
        else:
            clip_id = token
        if clip_id not in resolved:
            resolved.append(clip_id)
    return tuple(resolved)


def _echo_selection_result(result: SelectionResult) -> None:
    typer.echo("╭─ 切片选择结果")
    typer.echo(f"│ 模式       {result.mode.value}")
    typer.echo(f"│ 候选       {result.candidate_count}")
    typer.echo(f"│ 已选择     {len(result.selected_clip_ids)}")
    typer.echo(f"│ 已排除     {len(result.excluded_clip_ids)}")
    typer.echo(f"│ 待选择     {len(result.unchanged_clip_ids)}")
    typer.echo("╰────────────────────────────────────────────────────────")


@app.command("select")
def select_clips(
    project_id: Annotated[str, typer.Argument(help="Project ID whose clips will be selected.")],
    mode: Annotated[
        Literal["default", "manual"],
        typer.Option(
            "--mode",
            help=(
                "default selects all new candidates; manual uses --clips or an interactive prompt."
            ),
        ),
    ] = "default",
    clips_value: Annotated[
        str | None,
        typer.Option(
            "--clips",
            help="Comma-separated clip IDs or 1-based list numbers; use 'none' to select none.",
        ),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", help="Prompt for manual candidate numbers in the terminal."),
    ] = False,
    package: Annotated[
        bool,
        typer.Option("--package/--no-package", help="Create the delivery package after selection."),
    ] = True,
    include_zip: Annotated[
        bool,
        typer.Option("--zip/--no-zip", help="Include the immutable delivery ZIP."),
    ] = True,
    wait: Annotated[
        bool,
        typer.Option("--wait/--no-wait", help="Package in this foreground process."),
    ] = True,
) -> None:
    """Choose clips in default or manual mode, then optionally package them."""

    if mode == SelectionMode.DEFAULT.value and (clips_value is not None or interactive):
        typer.echo("Default selection does not accept --clips or --interactive", err=True)
        raise typer.Exit(code=2)
    if mode == SelectionMode.MANUAL.value and clips_value is None and not interactive:
        typer.echo("Manual selection requires --clips or --interactive", err=True)
        raise typer.Exit(code=2)
    settings = get_settings()
    try:
        with LiveClipRuntime.open(settings) as runtime:
            candidates = runtime.clip_query_service.list_project_clips(project_id)
            candidate_ids = tuple(value.clip_id for value in candidates)
            selected_ids: tuple[str, ...] = ()
            if mode == SelectionMode.MANUAL.value:
                if interactive:
                    typer.echo("候选切片:")
                    for index, clip in enumerate(candidates, start=1):
                        typer.echo(
                            f" {index:02d}. {clip.score:5.1f} | "
                            f"{clip.source_start_ms / 1000:.1f}-"
                            f"{clip.source_end_ms / 1000:.1f}s | {clip.title}"
                        )
                    clips_value = typer.prompt("输入要保留的编号 (逗号分隔, none 表示全部排除)")
                assert clips_value is not None
                selected_ids = _resolve_manual_selection(
                    clips_value,
                    clip_ids=candidate_ids,
                )
            result = runtime.selection_service.select(
                project_id,
                mode=SelectionMode(mode),
                selected_clip_ids=selected_ids,
            )
            typer.echo("╭─ 切片选择结果")
            typer.echo(f"│ 模式       {result.mode.value}")
            typer.echo(f"│ 候选       {result.candidate_count}")
            typer.echo(f"│ 已选择     {len(result.selected_clip_ids)}")
            typer.echo(f"│ 已排除     {len(result.excluded_clip_ids)}")
            typer.echo(f"│ 待选择     {len(result.unchanged_clip_ids)}")
            typer.echo("╰────────────────────────────────────────────────────────")
            if package:
                _package_project(
                    runtime,
                    project_id=project_id,
                    include_zip=include_zip,
                    wait=wait,
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


def _package_project(
    runtime: LiveClipRuntime,
    *,
    project_id: str,
    include_zip: bool,
    wait: bool,
) -> None:
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


@app.command("package")
@app.command("deliver")
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
    """Package all currently selected clips into a new immutable delivery version."""

    settings = get_settings()
    try:
        with LiveClipRuntime.open(settings) as runtime:
            _package_project(
                runtime,
                project_id=project_id,
                include_zip=include_zip,
                wait=wait,
            )
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
