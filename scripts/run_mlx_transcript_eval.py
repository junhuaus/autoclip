from __future__ import annotations

import argparse
from pathlib import Path

from liveclip.config import Settings
from liveclip.media.models import AudioChunkManifest
from liveclip.media.secure_files import read_regular_text_no_follow
from liveclip.pipeline.transcript import transcribe_chunks_detailed
from liveclip.providers.asr.base import AudioChunkLike
from liveclip.providers.asr.mlx import MLXASRProvider, assert_mlx_asr_ready
from liveclip.providers.telemetry import ProviderCallRecord, ProviderCallStatus


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a resumable full local transcript from an existing verified manifest."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    manifest_path = _absolute(args.manifest, label="manifest")
    output_dir = _absolute(args.output_dir, label="output directory", must_exist=False)
    if output_dir == Path(output_dir.anchor) or len(output_dir.parts) < 4:
        raise ValueError("output directory is too broad")

    manifest = AudioChunkManifest.model_validate_json(
        read_regular_text_no_follow(manifest_path, max_bytes=8 * 1024 * 1024)
    )
    if not manifest.complete:
        raise ValueError("audio chunk manifest is incomplete")
    settings = Settings()
    model_path = settings.resolved_mlx_asr_model_path()
    expected_snapshot = assert_mlx_asr_ready(model_path)
    provider = MLXASRProvider(model_path=model_path)
    if provider.model_snapshot != expected_snapshot:
        raise RuntimeError("model snapshot changed between readiness and evaluation")

    completed = 0

    def report(
        _chunk: AudioChunkLike,
        _call: ProviderCallRecord | None,
        status: ProviderCallStatus,
        cache_hit: bool,
    ) -> None:
        nonlocal completed
        if status is ProviderCallStatus.SUCCEEDED:
            completed += 1
        suffix = " cache" if cache_hit else ""
        print(f"MLX ASR {completed}/{len(manifest.chunks)}{suffix}", flush=True)

    result = transcribe_chunks_detailed(
        provider,
        manifest.chunks,
        source_duration_ms=manifest.source_duration_ms,
        output_dir=output_dir,
        cache_dir=output_dir / "asr-cache",
        language="zh",
        vocabulary_prompt=settings.asr_vocabulary_prompt,
        concurrency=1,
        on_chunk_outcome=report,
    )
    print(
        f"MLX transcript ready: segments={len(result.document.segments)} "
        f"word_timing={result.document.word_timing_status.value} "
        f"calls={len(result.call_records)}"
    )


def _absolute(path: Path, *, label: str, must_exist: bool = True) -> Path:
    value = path.expanduser()
    if not value.is_absolute() or ".." in value.parts:
        raise ValueError(f"{label} must be an absolute path without parent traversal")
    resolved = value.resolve(strict=must_exist)
    if must_exist and not resolved.is_file():
        raise ValueError(f"{label} must be a regular file")
    return resolved


if __name__ == "__main__":
    main()
