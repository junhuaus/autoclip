from __future__ import annotations

import json
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from liveclip.config import Settings
from liveclip.config.fonts import available_chinese_fonts

CheckStatus = Literal["pass", "warning", "fail"]


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: CheckStatus
    summary: str
    details: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def ok(self) -> bool:
        return not any(check.status == "fail" for check in self.checks)

    @property
    def warnings(self) -> int:
        return sum(check.status == "warning" for check in self.checks)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "ok": self.ok,
            "warnings": self.warnings,
            "checks": [check.as_dict() for check in self.checks],
        }

    def as_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=2)


def run_doctor(settings: Settings) -> DoctorReport:
    checks = [
        _system_check(),
        _python_check(),
        _tool_check("node", ["node", "--version"]),
        _node_lts_check(),
        _tool_check("npm", ["npm", "--version"]),
        _tool_check("git", ["git", "--version"]),
    ]
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    checks.extend(
        [
            _tool_check("ffmpeg", ["ffmpeg", "-version"]),
            _tool_check("ffprobe", ["ffprobe", "-version"]),
            _ffmpeg_filter_check(ffmpeg_path),
            _font_check(),
            _sqlite_check(settings.resolved_data_dir()),
            _data_dir_check(settings.resolved_data_dir()),
            _allowed_roots_check(settings),
            _openai_check(settings),
            _video_encoder_check(ffmpeg_path, ffprobe_path),
        ]
    )
    return DoctorReport(checks=tuple(checks))


def _system_check() -> DoctorCheck:
    system = platform.system()
    machine = platform.machine()
    mac_version = platform.mac_ver()[0]
    if system != "Darwin" or machine != "arm64":
        return DoctorCheck(
            "system",
            "fail",
            "LiveClip requires Apple Silicon macOS",
            {"system": system, "architecture": machine, "macos": mac_version},
        )
    return DoctorCheck(
        "system",
        "pass",
        "Apple Silicon macOS detected",
        {"system": system, "architecture": machine, "macos": mac_version},
    )


def _python_check() -> DoctorCheck:
    version = platform.python_version()
    machine = platform.machine()
    environment = Path(sys.prefix).name
    supported = tuple(map(int, version.split(".")[:2])) >= (3, 11) and machine == "arm64"
    return DoctorCheck(
        "python",
        "pass" if supported else "fail",
        "Python runtime is supported" if supported else "Python 3.11+ arm64 is required",
        {
            "version": version,
            "architecture": machine,
            "environment": environment,
            "executable": sys.executable,
        },
    )


def _tool_check(name: str, argv: Sequence[str]) -> DoctorCheck:
    path = shutil.which(argv[0])
    if path is None:
        return DoctorCheck(name, "fail", f"{name} was not found on PATH")
    result = _run(argv, timeout=15)
    output = (result.stdout or result.stderr).splitlines()
    summary = output[0].strip() if output else f"{name} returned no version output"
    return DoctorCheck(
        name,
        "pass" if result.returncode == 0 else "fail",
        summary,
        {"path": path},
    )


def _node_lts_check() -> DoctorCheck:
    if shutil.which("node") is None:
        return DoctorCheck("node_lts", "fail", "Node.js was not found")
    result = _run(["node", "-p", "String(process.release.lts || '')"], timeout=10)
    value = result.stdout.strip()
    if result.returncode != 0:
        return DoctorCheck("node_lts", "fail", "Could not inspect Node.js LTS status")
    if not value:
        return DoctorCheck("node_lts", "warning", "Active Node.js is not an LTS release")
    return DoctorCheck("node_lts", "pass", f"Node.js LTS release: {value}")


def parse_ffmpeg_filters(output: str) -> set[str]:
    names: set[str] = set()
    for line in output.splitlines():
        match = re.match(r"^\s*[TSC.]{2,4}\s+([A-Za-z0-9_]+)\s+", line)
        if match:
            names.add(match.group(1))
    return names


def _ffmpeg_filter_check(ffmpeg_path: str | None) -> DoctorCheck:
    if ffmpeg_path is None:
        return DoctorCheck("ffmpeg_filters", "fail", "FFmpeg is unavailable")
    result = _run([ffmpeg_path, "-hide_banner", "-filters"], timeout=20)
    names = parse_ffmpeg_filters(result.stdout + result.stderr)
    required = {"loudnorm", "silencedetect", "overlay", "scale", "crop"}
    text_filters = {"subtitles", "drawtext"}
    missing_required = sorted(required - names)
    present_text = sorted(text_filters & names)
    missing_text = sorted(text_filters - names)
    details: dict[str, object] = {
        "required_present": sorted(required & names),
        "required_missing": missing_required,
        "text_present": present_text,
        "text_missing": missing_text,
        "text_fallback": "Pillow RGBA + overlay",
    }
    if result.returncode != 0 or missing_required:
        return DoctorCheck(
            "ffmpeg_filters", "fail", "Required FFmpeg media filters are missing", details
        )
    if missing_text:
        return DoctorCheck(
            "ffmpeg_filters",
            "warning",
            "FFmpeg text filters are absent; deterministic raster overlay will be used",
            details,
        )
    return DoctorCheck("ffmpeg_filters", "pass", "Required and text filters are available", details)


def _font_check() -> DoctorCheck:
    present = [str(path) for path in available_chinese_fonts()]
    if not present:
        return DoctorCheck("chinese_font", "fail", "No supported Chinese font was found")
    return DoctorCheck(
        "chinese_font", "pass", "A supported Chinese font is available", {"fonts": present}
    )


def _data_dir_check(data_dir: Path) -> DoctorCheck:
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".liveclip-write-", dir=data_dir):
            pass
    except OSError as exc:
        return DoctorCheck(
            "data_dir", "fail", "Data directory is not writable", {"error": exc.__class__.__name__}
        )
    return DoctorCheck("data_dir", "pass", "Data directory is writable", {"path": str(data_dir)})


def _sqlite_check(data_dir: Path) -> DoctorCheck:
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".doctor-sqlite-", dir=data_dir) as temp_dir:
            db_path = Path(temp_dir) / "doctor.sqlite3"
            connection = sqlite3.connect(db_path)
            try:
                journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                connection.execute("PRAGMA foreign_keys=ON")
                foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
                connection.execute("PRAGMA busy_timeout=5000")
                connection.execute(
                    "CREATE TABLE task (id INTEGER PRIMARY KEY, state TEXT NOT NULL)"
                )
                connection.execute("INSERT INTO task(state) VALUES ('queued')")
                returned = connection.execute(
                    "UPDATE task SET state='running' WHERE id=1 RETURNING state"
                ).fetchone()
            finally:
                connection.close()
    except (OSError, sqlite3.Error) as exc:
        return DoctorCheck(
            "sqlite",
            "fail",
            "SQLite capability check failed",
            {"version": sqlite3.sqlite_version, "error": exc.__class__.__name__},
        )
    ok = journal_mode.lower() == "wal" and foreign_keys == 1 and returned == ("running",)
    return DoctorCheck(
        "sqlite",
        "pass" if ok else "fail",
        "SQLite WAL, foreign keys, busy timeout and RETURNING work"
        if ok
        else "SQLite lacks a required capability",
        {"version": sqlite3.sqlite_version, "journal_mode": journal_mode},
    )


def _allowed_roots_check(settings: Settings) -> DoctorCheck:
    roots = settings.allowed_media_roots
    if not roots:
        return DoctorCheck(
            "allowed_media_roots",
            "warning",
            "No allowed media root is configured; real imports are disabled",
        )
    invalid: list[str] = []
    resolved: list[str] = []
    for root in roots:
        try:
            value = root.resolve(strict=True)
        except OSError:
            invalid.append(str(root))
            continue
        if not value.is_dir() or not root.is_absolute():
            invalid.append(str(root))
        else:
            resolved.append(str(value))
    if invalid:
        return DoctorCheck(
            "allowed_media_roots",
            "fail",
            "One or more allowed media roots are invalid",
            {"invalid": invalid, "valid": resolved},
        )
    return DoctorCheck(
        "allowed_media_roots",
        "pass",
        "Allowed media roots are valid",
        {"roots": resolved},
    )


def _openai_check(settings: Settings) -> DoctorCheck:
    configured = bool(settings.openai_api_key and settings.openai_api_key.get_secret_value())
    if not configured:
        return DoctorCheck(
            "openai",
            "warning",
            "OpenAI cloud capability is not configured; Mock Demo remains available",
            {"configured": False},
        )
    return DoctorCheck(
        "openai",
        "pass",
        "OpenAI cloud configuration is present (secret not displayed)",
        {"configured": True},
    )


def _video_encoder_check(ffmpeg_path: str | None, ffprobe_path: str | None) -> DoctorCheck:
    if ffmpeg_path is None or ffprobe_path is None:
        return DoctorCheck("video_encoder", "fail", "FFmpeg and ffprobe are required")
    with tempfile.TemporaryDirectory(prefix="liveclip-doctor-codec-") as temp_dir:
        target = Path(temp_dir) / "probe.mp4"
        vt = _encode_probe(ffmpeg_path, target, "h264_videotoolbox")
        if vt.returncode == 0 and _probe_has_av(ffprobe_path, target):
            return DoctorCheck(
                "video_encoder",
                "pass",
                "Actual h264_videotoolbox H.264/AAC encode succeeded",
                {"selected": "h264_videotoolbox", "fallback": "libx264"},
            )
        target.unlink(missing_ok=True)
        fallback = _encode_probe(ffmpeg_path, target, "libx264")
        if fallback.returncode == 0 and _probe_has_av(ffprobe_path, target):
            return DoctorCheck(
                "video_encoder",
                "warning",
                "VideoToolbox encode failed; actual libx264 fallback encode succeeded",
                {
                    "selected": "libx264",
                    "videotoolbox_error": _safe_last_line(vt.stderr),
                },
            )
        return DoctorCheck(
            "video_encoder",
            "fail",
            "Both VideoToolbox and libx264 actual encode probes failed",
            {
                "videotoolbox_error": _safe_last_line(vt.stderr),
                "libx264_error": _safe_last_line(fallback.stderr),
            },
        )


def _encode_probe(ffmpeg_path: str, target: Path, encoder: str) -> subprocess.CompletedProcess[str]:
    argv = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=160x90:rate=24",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000",
        "-t",
        "0.5",
        "-c:v",
        encoder,
    ]
    if encoder == "h264_videotoolbox":
        argv.extend(["-allow_sw", "0", "-b:v", "300k"])
    else:
        argv.extend(["-preset", "ultrafast", "-crf", "28"])
    argv.extend(["-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(target)])
    return _run(argv, timeout=30)


def _probe_has_av(ffprobe_path: str, target: Path) -> bool:
    result = _run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(target),
        ],
        timeout=15,
    )
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    kinds = {stream.get("codec_type") for stream in payload.get("streams", [])}
    return {"audio", "video"}.issubset(kinds)


def _safe_last_line(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    diagnostic_terms = (
        "cannot create compression session",
        "error while opening encoder",
        "error initializing output stream",
        "operation not permitted",
    )
    for line in reversed(lines):
        if any(term in line.lower() for term in diagnostic_terms):
            return line[:500]
    return lines[-1][:500] if lines else "no diagnostic output"


def _run(argv: Sequence[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(list(argv), 127, "", exc.__class__.__name__)
