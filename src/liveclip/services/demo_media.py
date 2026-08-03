from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Sequence
from pathlib import Path


class DemoMediaError(RuntimeError):
    pass


_DEMO_PROJECT_PATTERN = re.compile(r"^demo_\d{8}T\d{6}_[a-f0-9]{8}$")
_DEMO_PHASES = {
    "generate_source",
    "ingest",
    "preprocess",
    "transcribe",
    "candidates",
    "edit",
    "proxy_render",
    "demo_review",
    "final_render",
    "delivery",
    "delivered",
}


def build_demo_source_argv(
    *,
    output_path: Path,
    duration_ms: int,
    ffmpeg_path: str = "ffmpeg",
) -> list[str]:
    if duration_ms < 10_000:
        raise ValueError("Demo source must be at least ten seconds")
    duration_seconds = f"{duration_ms / 1_000:.3f}"
    silence_ranges = _silence_ranges(duration_ms)
    enable = "+".join(
        f"between(t,{start_ms / 1_000:.3f},{end_ms / 1_000:.3f})"
        for start_ms, end_ms in silence_ranges
    )
    audio_filter = f"volume=volume=0:enable='{enable}'" if enable else "anull"
    return [
        ffmpeg_path,
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=640x360:rate=24:duration={duration_seconds}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=660:sample_rate=48000:duration={duration_seconds}",
        "-af",
        audio_filter,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-g",
        "48",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def create_demo_source(
    *,
    output_path: Path,
    duration_ms: int = 96_000,
    ffmpeg_path: str | None = None,
) -> Path:
    executable = ffmpeg_path or shutil.which("ffmpeg")
    if executable is None:
        raise DemoMediaError("ffmpeg is required to generate Demo media")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise DemoMediaError("refusing to overwrite existing Demo source")
    temporary = output_path.with_name(f".{output_path.stem}.tmp-{uuid.uuid4().hex}.mp4")
    argv = build_demo_source_argv(
        output_path=temporary,
        duration_ms=duration_ms,
        ffmpeg_path=executable,
    )
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            shell=False,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DemoMediaError("Demo source generation could not run") from exc
    if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size < 10_000:
        raise DemoMediaError("Demo source generation failed")
    try:
        os.link(temporary, output_path)
    except FileExistsError as exc:
        raise DemoMediaError("Demo source publication lost a no-clobber race") from exc
    except OSError as exc:
        raise DemoMediaError("Demo source could not be published atomically") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return output_path


def clean_demo_contents(*, project_root: Path, allowed_media_roots: Sequence[Path]) -> int:
    resolved_project = project_root.resolve(strict=True)
    lexical_demo = resolved_project / "data" / "demo"
    if lexical_demo.is_symlink():
        raise DemoMediaError("Demo root must not be a symbolic link")
    resolved_demo = lexical_demo.resolve(strict=False)
    forbidden = {
        Path.home().resolve(strict=True),
        resolved_project,
        (resolved_project / "data" / "projects").resolve(strict=False),
    }
    if not str(resolved_demo) or resolved_demo in forbidden:
        raise DemoMediaError("refusing unsafe Demo cleanup target")
    if resolved_demo != lexical_demo:
        raise DemoMediaError("Demo cleanup target escaped the repository data directory")
    for configured_root in allowed_media_roots:
        try:
            allowed = configured_root.resolve(strict=True)
        except OSError:
            continue
        if (
            allowed == resolved_demo
            or resolved_demo in allowed.parents
            or allowed in resolved_demo.parents
        ):
            raise DemoMediaError("Demo cleanup target overlaps a configured allowed media root")
    resolved_demo.mkdir(parents=True, exist_ok=True)
    projects_dir = resolved_demo / "projects"
    if not projects_dir.exists():
        return 0
    if projects_dir.is_symlink() or not projects_dir.is_dir():
        raise DemoMediaError("Demo projects container must be a real directory")
    if projects_dir.resolve(strict=True) != projects_dir:
        raise DemoMediaError("Demo projects container escaped the Demo root")
    removed = 0
    for child in projects_dir.iterdir():
        if not _is_generated_demo_project(child):
            continue
        shutil.rmtree(child)
        removed += 1
    return removed


def _is_generated_demo_project(path: Path) -> bool:
    if path.is_symlink() or not path.is_dir() or not _DEMO_PROJECT_PATTERN.fullmatch(path.name):
        return False
    marker = path / ".phase.json"
    if marker.is_symlink() or not marker.is_file():
        return False
    try:
        if marker.resolve(strict=True).parent != path.resolve(strict=True):
            return False
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("phase"), str)
        and payload["phase"] in _DEMO_PHASES
    )


def _silence_ranges(duration_ms: int) -> tuple[tuple[int, int], ...]:
    if duration_ms < 70_000:
        midpoint = duration_ms // 2
        return ((max(1_000, midpoint - 1_000), min(duration_ms - 1_000, midpoint + 1_000)),)
    return ((30_000, 32_000), (62_000, 64_000))
