from __future__ import annotations

import json

import typer

from liveclip import __version__
from liveclip.cli.doctor import DoctorReport, run_doctor
from liveclip.config import get_settings

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
