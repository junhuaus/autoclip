from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.config import Settings
from liveclip.media.secure_files import (
    hash_regular_file_no_follow,
    read_regular_text_no_follow,
    write_text_immutable_no_follow,
)
from liveclip.providers.llm.codex import (
    CODEX_DISABLED_FEATURES,
    SUPPORTED_CODEX_CLI_VERSION,
    assert_codex_cli_ready,
    resolve_codex_executable,
)

_SAFE_ENV_KEYS = frozenset(
    {
        "CODEX_HOME",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TMPDIR",
        "USER",
    }
)
_SAFE_ITEM_TYPES = frozenset({"agent_message", "error", "reasoning"})
_MAX_PROMPT_BYTES = 2 * 1024 * 1024
_MAX_TRANSCRIPT_BYTES = 8 * 1024 * 1024
_MAX_RESULT_BYTES = 2 * 1024 * 1024
_SAFE_MODEL = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")


class _SuspectedError(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    start_ms: Annotated[int, Field(ge=0)]
    text: Annotated[str, Field(max_length=1_000)]
    reason: Annotated[str, Field(max_length=1_000)]


class _SystemEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    quality_score: Annotated[float, Field(ge=0, le=100)]
    chinese_fluency: Annotated[float, Field(ge=0, le=10)]
    contextual_coherence: Annotated[float, Field(ge=0, le=10)]
    terminology_consistency: Annotated[float, Field(ge=0, le=10)]
    completeness_proxy: Annotated[float, Field(ge=0, le=10)]
    timestamp_continuity: Annotated[float, Field(ge=0, le=10)]
    strengths: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=500)]], Field(max_length=8)
    ]
    suspected_errors: Annotated[list[_SuspectedError], Field(max_length=12)]

    @model_validator(mode="after")
    def score_must_equal_subscore_total(self) -> _SystemEvaluation:
        expected = 2 * (
            self.chinese_fluency
            + self.contextual_coherence
            + self.terminology_consistency
            + self.completeness_proxy
            + self.timestamp_continuity
        )
        if not math.isclose(self.quality_score, expected, abs_tol=0.001):
            raise ValueError("quality score does not equal twice the subscore total")
        return self


class _PairwiseFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    start_ms: Annotated[int, Field(ge=0)]
    system_a_text: Annotated[str, Field(max_length=1_000)]
    system_b_text: Annotated[str, Field(max_length=1_000)]
    assessment: Annotated[str, Field(max_length=1_000)]


class _JudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1"]
    metric_name: Literal["codex_text_only_quality_proxy"]
    acoustic_accuracy_measured: Literal[False]
    system_a: _SystemEvaluation
    system_b: _SystemEvaluation
    preferred_system: Literal["a", "b", "tie"]
    confidence: Literal["low", "medium", "high"]
    pairwise_findings: Annotated[list[_PairwiseFinding], Field(max_length=12)]
    conclusion: Annotated[str, Field(min_length=1, max_length=3_000)]
    limitations: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=500)]],
        Field(min_length=1, max_length=8),
    ]

    @model_validator(mode="after")
    def preferred_system_must_match_scores(self) -> _JudgeResult:
        score_a = self.system_a.quality_score
        score_b = self.system_b.quality_score
        if self.preferred_system == "a" and score_a <= score_b:
            raise ValueError("preferred system A does not have the higher score")
        if self.preferred_system == "b" and score_b <= score_a:
            raise ValueError("preferred system B does not have the higher score")
        if self.preferred_system == "tie" and score_a != score_b:
            raise ValueError("a tied preference requires equal scores")
        return self


def main() -> None:
    parser = argparse.ArgumentParser(description="Blindly compare two ASR transcripts with Codex.")
    parser.add_argument("--cloud", required=True, type=Path)
    parser.add_argument("--local", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--codex-executable")
    args = parser.parse_args()
    if _SAFE_MODEL.fullmatch(args.model) is None:
        raise ValueError("Codex model name is invalid")
    codex_executable = args.codex_executable or Settings().codex_executable
    cloud_path = _file(args.cloud)
    local_path = _file(args.local)
    output_dir = _directory(args.output_dir)
    experiment_dir = Path(__file__).resolve().parents[1] / "docs/research/asr-comparison-2026-09-02"
    prompt_path = experiment_dir / "judge-prompt.md"
    schema_path = experiment_dir / "judge.schema.json"

    cloud_sha, _ = hash_regular_file_no_follow(cloud_path)
    local_sha, _ = hash_regular_file_no_follow(local_path)
    cloud = _compact_transcript(cloud_path)
    local = _compact_transcript(local_path)
    if cloud["source_duration_ms"] != local["source_duration_ms"]:
        raise ValueError("transcripts do not cover the same source duration")

    # Identity order is deterministic but depends on both transcript hashes. The judge
    # sees no mapping.
    order_hash = hashlib.sha256(f"{cloud_sha}:{local_sha}".encode()).hexdigest()
    cloud_is_a = int(order_hash[0], 16) % 2 == 0
    systems = {
        "system_a": cloud if cloud_is_a else local,
        "system_b": local if cloud_is_a else cloud,
    }
    judge_input = {
        "schema_version": "1",
        "same_audio_chunking": True,
        "source_duration_ms": cloud["source_duration_ms"],
        **systems,
    }
    prompt = (
        read_regular_text_no_follow(prompt_path, max_bytes=64 * 1024)
        + "\n\n<untrusted_asr_comparison>\n"
        + json.dumps(judge_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n</untrusted_asr_comparison>\n"
    )
    if len(prompt.encode()) > _MAX_PROMPT_BYTES:
        raise ValueError("blind ASR comparison prompt exceeds the safe size limit")

    result, call = _run_codex(
        prompt=prompt,
        schema_path=schema_path,
        model=args.model,
        codex_executable=codex_executable,
    )
    if result.get("acoustic_accuracy_measured") is not False:
        raise RuntimeError("judge did not preserve the text-only accuracy boundary")
    mapping = {
        "system_a": "openrouter" if cloud_is_a else "mlx",
        "system_b": "mlx" if cloud_is_a else "openrouter",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "judge-result.json", result)
    _write_json(
        output_dir / "run-metadata.json",
        {
            "schema_version": "1",
            "generated_at": datetime.now(UTC).isoformat(),
            "metric_name": "codex_text_only_quality_proxy",
            "mapping_disclosed_after_judging": mapping,
            "transcript_sha256": {"openrouter": cloud_sha, "mlx": local_sha},
            "prompt_sha256": hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
            "schema_sha256": hashlib.sha256(schema_path.read_bytes()).hexdigest(),
            "call": call,
        },
    )
    print(
        json.dumps(
            {"mapping": mapping, "judge": result, "call": call},
            ensure_ascii=False,
            indent=2,
        )
    )


def _compact_transcript(path: Path) -> dict[str, object]:
    value = json.loads(read_regular_text_no_follow(path, max_bytes=_MAX_TRANSCRIPT_BYTES))
    duration = value.get("source_duration_ms")
    segments = value.get("segments")
    if not isinstance(duration, int) or not isinstance(segments, list):
        raise ValueError("transcript has invalid root fields")
    compact: list[dict[str, object]] = []
    for item in segments:
        if not isinstance(item, dict):
            raise ValueError("transcript segment is invalid")
        start = item.get("start_ms")
        end = item.get("end_ms")
        text = item.get("text")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or not isinstance(text, str)
            or not 0 <= start < end <= duration
        ):
            raise ValueError("transcript segment fields are invalid")
        compact.append({"start_ms": start, "end_ms": end, "text": text})
    return {"source_duration_ms": duration, "segments": compact}


def _run_codex(
    *,
    prompt: str,
    schema_path: Path,
    model: str,
    codex_executable: str,
) -> tuple[dict[str, Any], dict[str, object]]:
    contract = assert_codex_cli_ready(codex_executable)
    executable = resolve_codex_executable(codex_executable)
    disabled = [value for feature in CODEX_DISABLED_FEATURES for value in ("--disable", feature)]
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="liveclip-asr-blind-judge-") as temporary:
        temp_dir = Path(temporary).resolve(strict=True)
        output_path = temp_dir / "result.json"
        schema_copy_path = temp_dir / "judge.schema.json"
        write_text_immutable_no_follow(
            schema_copy_path,
            read_regular_text_no_follow(schema_path, max_bytes=256 * 1024),
            max_bytes=256 * 1024,
        )
        argv = [
            executable,
            "--ask-for-approval",
            "never",
            *disabled,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--strict-config",
            "--sandbox",
            "read-only",
            "-c",
            "features.shell_tool=false",
            "-c",
            "features.unified_exec=false",
            "-c",
            "features.multi_agent=false",
            "-c",
            'web_search="disabled"',
            "-c",
            'model_reasoning_effort="max"',
            "--model",
            model,
            "--output-schema",
            str(schema_copy_path),
            "--output-last-message",
            str(output_path),
            "--json",
            "--color",
            "never",
            "-C",
            str(temp_dir),
            "-",
        ]
        completed = subprocess.run(
            argv,
            input=prompt,
            text=True,
            capture_output=True,
            cwd=temp_dir,
            env={key: value for key, value in os.environ.items() if key.upper() in _SAFE_ENV_KEYS},
            timeout=1_800,
            check=False,
            shell=False,
        )
        thread_id, usage, unsafe = _codex_metadata(completed.stdout)
        if completed.returncode != 0:
            raise RuntimeError("Codex ASR blind judge failed")
        if unsafe or thread_id is None or usage is None:
            raise RuntimeError("Codex ASR blind judge returned invalid call evidence")
        if not output_path.is_file():
            raise RuntimeError("Codex ASR blind judge produced no structured result")
        value = _JudgeResult.model_validate_json(
            read_regular_text_no_follow(output_path, max_bytes=_MAX_RESULT_BYTES)
        ).model_dump(mode="json")
    return value, {
        "provider": "codex_cli",
        "model": model,
        "reasoning_effort": "max",
        "runtime_version": SUPPORTED_CODEX_CLI_VERSION,
        "contract": contract,
        "thread_id": thread_id,
        "usage": usage,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def _codex_metadata(stdout: str) -> tuple[str | None, dict[str, int] | None, bool]:
    thread_id: str | None = None
    usage: dict[str, int] | None = None
    unsafe = False
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            thread_id = event["thread_id"]
        if isinstance(event.get("type"), str) and event["type"].startswith("item."):
            item = event.get("item")
            item_type = item.get("type") if isinstance(item, dict) else None
            if item_type not in _SAFE_ITEM_TYPES:
                unsafe = True
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = {
                key: value
                for key, value in event["usage"].items()
                if isinstance(key, str)
                and re.fullmatch(r"[a-z_]{1,40}", key)
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
            }
    return thread_id, usage, unsafe


def _file(path: Path) -> Path:
    value = path.expanduser()
    if not value.is_absolute() or ".." in value.parts:
        raise ValueError("transcript path must be absolute without parent traversal")
    resolved = value.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("transcript path must be a regular file")
    return resolved


def _directory(path: Path) -> Path:
    value = path.expanduser()
    if not value.is_absolute() or ".." in value.parts:
        raise ValueError("output directory must be absolute without parent traversal")
    resolved = value.resolve(strict=False)
    if resolved == Path(resolved.anchor) or len(resolved.parts) < 4:
        raise ValueError("output directory is too broad")
    return resolved


def _write_json(path: Path, value: object) -> None:
    write_text_immutable_no_follow(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        max_bytes=_MAX_RESULT_BYTES,
    )


if __name__ == "__main__":
    main()
