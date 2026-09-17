from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from liveclip.config import Settings
from liveclip.media.ingest import resolve_allowed_source
from liveclip.media.models import AudioChunk
from liveclip.media.secure_files import hash_regular_file_no_follow
from liveclip.providers.asr.mlx import MLXASRProvider, assert_mlx_asr_ready


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one real, bounded local MLX ASR smoke.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--duration-seconds", type=float, default=30.0)
    args = parser.parse_args()
    if args.start_seconds < 0 or not 1 <= args.duration_seconds <= 120:
        raise ValueError("start must be nonnegative and duration must be between 1 and 120 seconds")

    settings = Settings()
    source = resolve_allowed_source(
        args.input,
        settings.allowed_media_roots,
        forbidden_roots=(settings.resolved_data_dir(),),
    )
    model_path = settings.resolved_mlx_asr_model_path()
    expected_snapshot = assert_mlx_asr_ready(model_path)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is unavailable")

    with tempfile.TemporaryDirectory(prefix="liveclip-mlx-smoke-") as temporary:
        chunk_path = Path(temporary).resolve(strict=True) / "smoke.m4a"
        result = subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                str(args.start_seconds),
                "-i",
                str(source),
                "-t",
                str(args.duration_seconds),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "aac",
                "-b:a",
                "64k",
                str(chunk_path),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            raise RuntimeError("ffmpeg could not extract the local ASR smoke audio")
        sha256, size_bytes = hash_regular_file_no_follow(chunk_path)
        duration_ms = round(args.duration_seconds * 1_000)
        source_start_ms = round(args.start_seconds * 1_000)
        chunk = AudioChunk(
            index=0,
            chunk_id="chunk_000000",
            source_start_ms=source_start_ms,
            source_end_ms=source_start_ms + duration_ms,
            duration_ms=duration_ms,
            overlap_before_ms=0,
            overlap_after_ms=0,
            path=chunk_path,
            size_bytes=size_bytes,
            sha256=sha256,
            cache_key=sha256,
        )
        provider = MLXASRProvider(model_path=model_path)
        started = time.monotonic()
        transcription = provider.transcribe(
            chunk,
            language="zh",
            vocabulary_prompt=settings.asr_vocabulary_prompt,
        )
        elapsed_seconds = round(time.monotonic() - started, 3)

    if provider.model_snapshot != expected_snapshot:
        raise RuntimeError("model snapshot changed between readiness and inference")
    print(
        json.dumps(
            {
                "schema_version": "1",
                "provider": transcription.provider,
                "model": transcription.model,
                "contract": provider.contract_version,
                "audio_sha256": sha256,
                "source_start_ms": source_start_ms,
                "duration_ms": duration_ms,
                "elapsed_seconds": elapsed_seconds,
                "word_timing_status": transcription.word_timing_status.value,
                "segments": [
                    {
                        "start_ms": segment.start_ms,
                        "end_ms": segment.end_ms,
                        "text": segment.text,
                    }
                    for segment in transcription.segments
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
