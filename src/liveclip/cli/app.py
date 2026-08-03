from __future__ import annotations

import json
from pathlib import Path

import typer

from liveclip import __version__
from liveclip.cli.doctor import DoctorReport, run_doctor
from liveclip.config import get_settings
from liveclip.services.demo import DemoRunError, run_demo
from liveclip.services.demo_media import DemoMediaError, clean_demo_contents

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
