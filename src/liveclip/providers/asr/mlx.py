from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import math
import platform
import shutil
import stat
import subprocess
import tempfile
import time
import unicodedata
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Real
from pathlib import Path

from liveclip.domain.time import seconds_to_ms
from liveclip.domain.transcript import WordTimingStatus
from liveclip.media.process import ProcessCancelled, run_cancellable_process
from liveclip.media.secure_files import (
    SecureFileError,
    hash_regular_file_no_follow,
    read_regular_text_no_follow,
)
from liveclip.providers.asr.base import (
    ASRChunkResult,
    AudioChunkLike,
    LocalASRSegment,
    LocalASRWord,
    open_validated_audio_chunk,
)
from liveclip.providers.telemetry import (
    ProviderCallRecord,
    ProviderCallStatus,
    ProviderCancelled,
    ProviderConfigurationError,
    ProviderDeterministicError,
)

MLX_ASR_MODEL = "openai/whisper-large-v3"
MLX_ASR_REPOSITORY = "mlx-community/whisper-large-v3-mlx"
MLX_ASR_REVISION = "49e6aa286ad60c14352c404340ded53710378a11"
MLX_ASR_CONFIG_SHA256 = "34982ce6ae286095000f82ae9583b3431639e8b092bf60c961f203745e6500e3"
MLX_ASR_WEIGHTS_SHA256 = "05ff791ce3630fae47e7c51004e9666204d786246ec07cac6110af768099b40d"
MLX_ASR_WEIGHTS_SIZE_BYTES = 3_083_520_416
MLX_WHISPER_DISTRIBUTION = "mlx-whisper"
MLX_WHISPER_VERSION = "0.4.3"
MLX_ASR_UNPROBED_CONTRACT = "mlx-asr-unprobed-v1"
_MODEL_CONFIG_MAX_BYTES = 64 * 1024
_MODEL_WEIGHT_FILENAME = "weights.npz"
_DECODE_SAMPLE_RATE_HZ = 16_000
_COMPRESSION_RATIO_THRESHOLD = 2.4
_LOGPROB_THRESHOLD = -1.0
_NO_SPEECH_THRESHOLD = 0.6
_DECODE_CONTRACT = {
    "compression_ratio_threshold": _COMPRESSION_RATIO_THRESHOLD,
    "condition_on_previous_text": False,
    "fp16": True,
    "initial_prompt": None,
    "language": "zh",
    "logprob_threshold": _LOGPROB_THRESHOLD,
    "no_speech_threshold": _NO_SPEECH_THRESHOLD,
    "task": "transcribe",
    "temperature": 0.0,
    "word_timestamps": True,
}
_LARGE_V3_DIMENSIONS = {
    "n_mels": 128,
    "n_audio_ctx": 1500,
    "n_audio_state": 1280,
    "n_audio_head": 20,
    "n_audio_layer": 32,
    "n_vocab": 51866,
    "n_text_ctx": 448,
    "n_text_state": 1280,
    "n_text_head": 20,
    "n_text_layer": 32,
}

MLXTranscribe = Callable[..., Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class MLXModelSnapshot:
    path: Path
    sha256: str
    config_sha256: str
    weights_sha256: str
    weights_size_bytes: int

    @property
    def contract_version(self) -> str:
        return f"mlx-asr-large-v3-fp16-greedy-v4.{self.sha256[:32]}"


def inspect_mlx_model(model_path: Path) -> MLXModelSnapshot:
    """Validate and fingerprint the exact local full-precision large-v3 snapshot."""

    path = Path(model_path).expanduser()
    if not path.is_absolute():
        raise ProviderConfigurationError("MLX ASR model path must be absolute")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProviderConfigurationError("MLX ASR model directory is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ProviderConfigurationError("MLX ASR model path must be a non-symlink directory")

    config_path = path / "config.json"
    weights_path = path / _MODEL_WEIGHT_FILENAME
    try:
        raw_config = read_regular_text_no_follow(
            config_path,
            max_bytes=_MODEL_CONFIG_MAX_BYTES,
        )
        config = json.loads(raw_config)
        config_sha256, _ = hash_regular_file_no_follow(config_path)
        weights_sha256, weights_size = hash_regular_file_no_follow(weights_path)
    except (OSError, SecureFileError, json.JSONDecodeError) as exc:
        raise ProviderConfigurationError("MLX ASR model snapshot is incomplete or unsafe") from exc
    if not isinstance(config, dict):
        raise ProviderConfigurationError("MLX ASR model config must be a JSON object")
    if config.get("model_type") not in {None, "whisper"}:
        raise ProviderConfigurationError("MLX ASR model config is not Whisper")
    if config.get("quantization") is not None:
        raise ProviderConfigurationError(
            "quantized MLX ASR models are not allowed in accuracy mode"
        )
    if any(config.get(key) != value for key, value in _LARGE_V3_DIMENSIONS.items()):
        raise ProviderConfigurationError("MLX ASR model config is not full Whisper large-v3")
    if config_sha256 != MLX_ASR_CONFIG_SHA256:
        raise ProviderConfigurationError("MLX ASR model config does not match the pinned snapshot")
    if weights_size != MLX_ASR_WEIGHTS_SIZE_BYTES or weights_sha256 != MLX_ASR_WEIGHTS_SHA256:
        raise ProviderConfigurationError("MLX ASR weights do not match the pinned snapshot")

    identity = json.dumps(
        {
            "algorithm": "mlx-large-v3-model-snapshot-v1",
            "config_sha256": config_sha256,
            "decode": _DECODE_CONTRACT,
            "model": MLX_ASR_MODEL,
            "repository": MLX_ASR_REPOSITORY,
            "revision": MLX_ASR_REVISION,
            "weights_filename": _MODEL_WEIGHT_FILENAME,
            "weights_sha256": weights_sha256,
            "weights_size_bytes": weights_size,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return MLXModelSnapshot(
        path=path,
        sha256=hashlib.sha256(identity.encode()).hexdigest(),
        config_sha256=config_sha256,
        weights_sha256=weights_sha256,
        weights_size_bytes=weights_size,
    )


def installed_mlx_whisper_version() -> str:
    try:
        version = importlib.metadata.version(MLX_WHISPER_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError as exc:
        raise ProviderConfigurationError("optional mlx-whisper runtime is not installed") from exc
    if version != MLX_WHISPER_VERSION:
        raise ProviderConfigurationError("installed mlx-whisper version is not the pinned version")
    if importlib.util.find_spec("mlx_whisper") is None:
        raise ProviderConfigurationError("mlx-whisper runtime cannot be imported")
    return version


def assert_mlx_asr_ready(model_path: Path) -> MLXModelSnapshot:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ProviderConfigurationError("MLX ASR requires Apple Silicon macOS")
    installed_mlx_whisper_version()
    try:
        module = importlib.import_module("mlx_whisper")
        transcribe = getattr(module, "transcribe", None)
    except (ImportError, OSError, RuntimeError) as exc:
        raise ProviderConfigurationError("mlx-whisper cannot access the local MLX runtime") from exc
    if not callable(transcribe):
        raise ProviderConfigurationError("mlx-whisper transcribe entry point is invalid")
    if shutil.which("ffmpeg") is None:
        raise ProviderConfigurationError("MLX ASR requires FFmpeg")
    return inspect_mlx_model(model_path)


class MLXASRProvider:
    """Accuracy-first local Whisper large-v3 FP16 adapter for Apple Silicon."""

    def __init__(
        self,
        *,
        model_path: Path,
        model_name: str = MLX_ASR_MODEL,
        transcribe_fn: MLXTranscribe | None = None,
        runtime_version: str | None = None,
        ffmpeg_path: str | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if model_name != MLX_ASR_MODEL:
            raise ProviderConfigurationError("local MLX ASR requires full Whisper large-v3")
        self._snapshot = inspect_mlx_model(model_path)
        self._runtime_version = runtime_version or installed_mlx_whisper_version()
        if self._runtime_version != MLX_WHISPER_VERSION:
            raise ProviderConfigurationError("MLX ASR runtime version is not pinned")
        self._ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg") or ""
        if not self._ffmpeg_path:
            raise ProviderConfigurationError("MLX ASR requires FFmpeg")
        self._transcribe_fn = transcribe_fn
        self._monotonic = monotonic

    @property
    def provider_name(self) -> str:
        return "mlx"

    @property
    def model_name(self) -> str:
        return MLX_ASR_MODEL

    @property
    def contract_version(self) -> str:
        return self._snapshot.contract_version

    @property
    def model_snapshot(self) -> MLXModelSnapshot:
        return self._snapshot

    def transcribe(
        self,
        chunk: AudioChunkLike,
        *,
        language: str = "zh",
        vocabulary_prompt: str | None = None,
        cancel_requested: Callable[[], bool] = lambda: False,
    ) -> ASRChunkResult:
        if language != "zh":
            raise ProviderConfigurationError("MLX ASR accuracy mode requires language=zh")
        if cancel_requested():
            raise ProviderCancelled()

        called_at = datetime.now(UTC)
        call_id = uuid.uuid4().hex
        request_id = f"mlx_{call_id}"
        operation_key = _operation_key(
            chunk,
            language=language,
            vocabulary_prompt=vocabulary_prompt,
            contract_version=self.contract_version,
        )
        started = self._monotonic()
        try:
            with tempfile.TemporaryDirectory(prefix="liveclip-mlx-asr-") as temporary:
                wav_path = Path(temporary).resolve(strict=True) / "verified-chunk.wav"
                self._decode_verified_chunk(
                    chunk,
                    wav_path=wav_path,
                    cancel_requested=cancel_requested,
                )
                if cancel_requested():
                    raise ProcessCancelled("local ASR was cancelled after audio decode")
                raw = self._transcribe(wav_path)
                if cancel_requested():
                    raise ProcessCancelled("local ASR was cancelled after model inference")
                result = _map_mlx_result(
                    raw,
                    chunk=chunk,
                    language=language,
                    request_id=request_id,
                    call_record=_call_record(
                        call_id=call_id,
                        operation_key=operation_key,
                        chunk=chunk,
                        called_at=called_at,
                        latency_ms=_elapsed_ms(started, self._monotonic()),
                        status=ProviderCallStatus.SUCCEEDED,
                        request_id=request_id,
                        failure_code=None,
                        snapshot=self._snapshot,
                    ),
                )
        except ProcessCancelled as exc:
            record = _call_record(
                call_id=call_id,
                operation_key=operation_key,
                chunk=chunk,
                called_at=called_at,
                latency_ms=_elapsed_ms(started, self._monotonic()),
                status=ProviderCallStatus.CANCELLED,
                request_id=request_id,
                failure_code="MLX_ASR_CANCELLED",
                snapshot=self._snapshot,
            )
            raise ProviderCancelled(record) from exc
        except ProviderConfigurationError:
            raise
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            record = _call_record(
                call_id=call_id,
                operation_key=operation_key,
                chunk=chunk,
                called_at=called_at,
                latency_ms=_elapsed_ms(started, self._monotonic()),
                status=ProviderCallStatus.FAILED,
                request_id=request_id,
                failure_code="MLX_ASR_RUNTIME_FAILED",
                snapshot=self._snapshot,
            )
            raise ProviderDeterministicError(record) from exc
        except (TypeError, ValueError) as exc:
            record = _call_record(
                call_id=call_id,
                operation_key=operation_key,
                chunk=chunk,
                called_at=called_at,
                latency_ms=_elapsed_ms(started, self._monotonic()),
                status=ProviderCallStatus.INVALID,
                request_id=request_id,
                failure_code="MLX_ASR_OUTPUT_INVALID",
                snapshot=self._snapshot,
            )
            raise ProviderDeterministicError(record) from exc
        return result

    def _decode_verified_chunk(
        self,
        chunk: AudioChunkLike,
        *,
        wav_path: Path,
        cancel_requested: Callable[[], bool],
    ) -> None:
        with open_validated_audio_chunk(chunk) as handle:
            descriptor = handle.fileno()
            argv = [
                self._ffmpeg_path,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                f"/dev/fd/{descriptor}",
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(_DECODE_SAMPLE_RATE_HZ),
                "-c:a",
                "pcm_s16le",
                "-f",
                "wav",
                str(wav_path),
            ]
            result = run_cancellable_process(
                argv,
                timeout_seconds=120,
                cancel_requested=cancel_requested,
                pass_fds=(descriptor,),
            )
        if result.returncode != 0:
            raise ValueError("verified audio chunk could not be decoded for local ASR")
        try:
            metadata = wav_path.lstat()
        except OSError as exc:
            raise ValueError("local ASR audio decode produced no output") from exc
        minimum_pcm_bytes = round(
            (chunk.source_end_ms - chunk.source_start_ms)
            * _DECODE_SAMPLE_RATE_HZ
            * 2
            / 1_000
            * 0.75
        )
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size < minimum_pcm_bytes:
            raise ValueError("local ASR audio decode produced invalid output")

    def _transcribe(
        self,
        wav_path: Path,
    ) -> Mapping[str, object]:
        transcribe = self._transcribe_fn
        if transcribe is None:
            try:
                module = importlib.import_module("mlx_whisper")
                candidate = module.transcribe
            except (ImportError, AttributeError, OSError, RuntimeError) as exc:
                raise ProviderConfigurationError("mlx-whisper runtime cannot be imported") from exc
            if not callable(candidate):
                raise ProviderConfigurationError("mlx-whisper transcribe entry point is invalid")
            transcribe = candidate
        value = transcribe(
            str(wav_path),
            path_or_hf_repo=str(self._snapshot.path),
            verbose=None,
            **_DECODE_CONTRACT,
        )
        if not isinstance(value, Mapping):
            raise TypeError("MLX ASR returned a non-object result")
        return value


def _map_mlx_result(
    raw: Mapping[str, object],
    *,
    chunk: AudioChunkLike,
    language: str,
    request_id: str,
    call_record: ProviderCallRecord,
) -> ASRChunkResult:
    chunk_duration_ms = chunk.source_end_ms - chunk.source_start_ms
    root_text = raw.get("text", "")
    raw_segments = raw.get("segments")
    if (
        not isinstance(root_text, str)
        or not isinstance(raw_segments, Sequence)
        or isinstance(raw_segments, str | bytes)
    ):
        raise TypeError("MLX ASR result has invalid root fields")

    segments: list[LocalASRSegment] = []
    words_by_segment: list[tuple[LocalASRWord, ...] | None] = []
    rejected_decode_segments = 0
    for index, item in enumerate(raw_segments, start=1):
        if not isinstance(item, Mapping):
            raise TypeError("MLX ASR segment is not an object")
        text = item.get("text")
        if not isinstance(text, str):
            raise TypeError("MLX ASR segment text is invalid")
        text = text.strip()
        if not text:
            continue
        if _failed_decode_segment(item):
            rejected_decode_segments += 1
            continue
        interval = _intersect_interval(
            item.get("start"),
            item.get("end"),
            duration_ms=chunk_duration_ms,
        )
        if interval is None:
            continue
        start_ms, end_ms = interval
        segment = LocalASRSegment(
            segment_id=f"mlx_{index:06d}",
            start_ms=start_ms,
            end_ms=end_ms,
            text=text,
        )
        segments.append(segment)
        words_by_segment.append(
            _optional_segment_words(
                item.get("words"),
                segment=segment,
            )
        )
    if root_text.strip() and not segments and rejected_decode_segments == 0:
        raise ValueError("nonempty MLX transcription has no source-overlapping segments")

    usage = dict(call_record.usage_json or {})
    usage["rejected_decode_segments"] = rejected_decode_segments
    call_record = call_record.model_copy(update={"usage_json": usage})

    words_available = bool(segments) and all(value is not None for value in words_by_segment)
    if words_available:
        segments = [
            segment.model_copy(update={"words": words_by_segment[index]})
            for index, segment in enumerate(segments)
        ]
    return ASRChunkResult(
        chunk_id=chunk.chunk_id,
        chunk_duration_ms=chunk_duration_ms,
        language=language,
        provider="mlx",
        model=MLX_ASR_MODEL,
        word_timing_status=(
            WordTimingStatus.AVAILABLE if words_available else WordTimingStatus.UNAVAILABLE
        ),
        segments=tuple(segments),
        request_id=request_id,
        call_record=call_record,
    )


def _failed_decode_segment(item: Mapping[str, object]) -> bool:
    compression_ratio = _optional_finite_metric(item, "compression_ratio")
    average_logprob = _optional_finite_metric(item, "avg_logprob")
    return (compression_ratio is not None and compression_ratio > _COMPRESSION_RATIO_THRESHOLD) or (
        average_logprob is not None and average_logprob < _LOGPROB_THRESHOLD
    )


def _optional_finite_metric(item: Mapping[str, object], key: str) -> float | None:
    if key not in item:
        return None
    value = item[key]
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"MLX ASR {key} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"MLX ASR {key} must be finite")
    return normalized


def _optional_segment_words(
    raw_words: object,
    *,
    segment: LocalASRSegment,
) -> tuple[LocalASRWord, ...] | None:
    if not isinstance(raw_words, Sequence) or isinstance(raw_words, str | bytes) or not raw_words:
        return None
    words: list[LocalASRWord] = []
    previous_start = -1
    try:
        for item in raw_words:
            if not isinstance(item, Mapping):
                return None
            text = item.get("word")
            if not isinstance(text, str):
                return None
            text = text.strip()
            if not text or len(text) > 100:
                return None
            interval = _intersect_interval(
                item.get("start"),
                item.get("end"),
                duration_ms=segment.end_ms,
                lower_ms=segment.start_ms,
            )
            if interval is None:
                return None
            start_ms, end_ms = interval
            if start_ms < previous_start:
                return None
            words.append(LocalASRWord(start_ms=start_ms, end_ms=end_ms, text=text))
            previous_start = start_ms
    except (TypeError, ValueError):
        return None
    if _alignment_text("".join(value.text for value in words)) != _alignment_text(segment.text):
        return None
    return tuple(words) if words else None


def _intersect_interval(
    start: object,
    end: object,
    *,
    duration_ms: int,
    lower_ms: int = 0,
) -> tuple[int, int] | None:
    start_seconds = _finite_seconds(start)
    end_seconds = _finite_seconds(end)
    start_ms = max(lower_ms, seconds_to_ms(start_seconds))
    end_ms = min(duration_ms, seconds_to_ms(end_seconds))
    return (start_ms, end_ms) if end_ms > start_ms else None


def _finite_seconds(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError("MLX ASR timestamp must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError("MLX ASR timestamp must be finite")
    return normalized


def _alignment_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character).startswith(("L", "N"))
    )


def _operation_key(
    chunk: AudioChunkLike,
    *,
    language: str,
    vocabulary_prompt: str | None,
    contract_version: str,
) -> str:
    payload = {
        "cache_key": getattr(chunk, "cache_key", None),
        "chunk_id": chunk.chunk_id,
        "contract_version": contract_version,
        "language": language,
        "model": MLX_ASR_MODEL,
        "prompt_sha256": hashlib.sha256((vocabulary_prompt or "").encode()).hexdigest(),
        "source_end_ms": chunk.source_end_ms,
        "source_start_ms": chunk.source_start_ms,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _call_record(
    *,
    call_id: str,
    operation_key: str,
    chunk: AudioChunkLike,
    called_at: datetime,
    latency_ms: int,
    status: ProviderCallStatus,
    request_id: str,
    failure_code: str | None,
    snapshot: MLXModelSnapshot,
) -> ProviderCallRecord:
    return ProviderCallRecord(
        call_id=call_id,
        operation_key=operation_key,
        subject_id=chunk.chunk_id,
        provider="mlx",
        operation="audio.transcriptions.local",
        model=MLX_ASR_MODEL,
        request_id=request_id,
        request_count=1,
        retry_count=0,
        latency_ms=latency_ms,
        audio_seconds=(chunk.source_end_ms - chunk.source_start_ms) / 1_000,
        usage_json={
            "backend": "mlx-whisper",
            "decode": _DECODE_CONTRACT,
            "model_snapshot_sha256": snapshot.sha256,
            "runtime_version": MLX_WHISPER_VERSION,
        },
        status=status,
        failure_code=failure_code,
        called_at=called_at,
    )


def _elapsed_ms(started: float, finished: float) -> int:
    return max(0, round((finished - started) * 1_000))
