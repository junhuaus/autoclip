from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import liveclip.providers.asr.mlx as mlx_module
from liveclip.domain.transcript import WordTimingStatus
from liveclip.media.models import AudioChunk
from liveclip.providers.asr.mlx import (
    MLX_ASR_MODEL,
    MLX_WHISPER_VERSION,
    MLXASRProvider,
    assert_mlx_asr_ready,
    inspect_mlx_model,
)
from liveclip.providers.telemetry import (
    ProviderCallStatus,
    ProviderConfigurationError,
    ProviderDeterministicError,
)

_TEST_WEIGHTS = b"full-precision-large-v3-test-weights"


@pytest.fixture(autouse=True)
def _accept_test_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    config = json.dumps(_model_config()).encode()
    monkeypatch.setattr(mlx_module, "MLX_ASR_CONFIG_SHA256", hashlib.sha256(config).hexdigest())
    monkeypatch.setattr(
        mlx_module,
        "MLX_ASR_WEIGHTS_SHA256",
        hashlib.sha256(_TEST_WEIGHTS).hexdigest(),
    )
    monkeypatch.setattr(mlx_module, "MLX_ASR_WEIGHTS_SIZE_BYTES", len(_TEST_WEIGHTS))


def _model_config() -> dict[str, object]:
    return {
        "model_type": "whisper",
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


def _model_dir(tmp_path: Path, *, quantized: bool = False) -> Path:
    model = tmp_path / "whisper-large-v3-mlx"
    model.mkdir(parents=True)
    config = _model_config()
    if quantized:
        config["quantization"] = {"bits": 4, "group_size": 64}
    (model / "config.json").write_text(
        json.dumps(config),
        encoding="utf-8",
    )
    (model / "weights.npz").write_bytes(_TEST_WEIGHTS)
    return model


def _chunk(tmp_path: Path, *, duration_ms: int = 2_000) -> AudioChunk:
    path = tmp_path / "chunk.m4a"
    content = b"verified-local-audio"
    path.write_bytes(content)
    return AudioChunk(
        index=0,
        chunk_id="chunk_000000",
        source_start_ms=10_000,
        source_end_ms=10_000 + duration_ms,
        duration_ms=duration_ms,
        overlap_before_ms=0,
        overlap_after_ms=0,
        path=path.absolute(),
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        cache_key="c" * 64,
    )


def _install_fake_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(
        argv: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        assert kwargs["pass_fds"]
        Path(argv[-1]).write_bytes(b"RIFF" + b"\0" * 64_000)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(mlx_module, "run_cancellable_process", fake_run)
    return calls


def test_model_snapshot_is_pinned_and_rejects_mutation_or_quantization(tmp_path: Path) -> None:
    model = _model_dir(tmp_path)

    first = inspect_mlx_model(model.absolute())
    second = inspect_mlx_model(model.absolute())

    assert first == second
    assert len(first.sha256) == 64
    assert first.weights_size_bytes > 0
    assert first.contract_version.startswith("mlx-asr-large-v3-fp16-greedy-v4.")

    (model / "weights.npz").write_bytes(b"different-model-bytes")
    with pytest.raises(ProviderConfigurationError, match="pinned snapshot"):
        inspect_mlx_model(model.absolute())

    quantized = _model_dir(tmp_path / "quantized", quantized=True)
    with pytest.raises(ProviderConfigurationError, match="quantized"):
        inspect_mlx_model(quantized.absolute())


def test_model_snapshot_rejects_wrong_dimensions_and_symlink(tmp_path: Path) -> None:
    model = _model_dir(tmp_path)
    config = (
        (model / "config.json")
        .read_text(encoding="utf-8")
        .replace(
            '"n_audio_layer": 32',
            '"n_audio_layer": 4',
        )
    )
    (model / "config.json").write_text(config, encoding="utf-8")

    with pytest.raises(ProviderConfigurationError, match="not full Whisper large-v3"):
        inspect_mlx_model(model.absolute())

    target = _model_dir(tmp_path / "target")
    linked = tmp_path / "linked-model"
    linked.symlink_to(target, target_is_directory=True)
    with pytest.raises(ProviderConfigurationError, match="non-symlink directory"):
        inspect_mlx_model(linked.absolute())


def test_readiness_probes_apple_silicon_runtime_ffmpeg_and_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model_dir(tmp_path)
    monkeypatch.setattr(mlx_module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(mlx_module.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        mlx_module,
        "installed_mlx_whisper_version",
        lambda: MLX_WHISPER_VERSION,
    )
    monkeypatch.setattr(
        mlx_module.importlib,
        "import_module",
        lambda _name: SimpleNamespace(transcribe=lambda *_args, **_kwargs: {}),
    )
    monkeypatch.setattr(mlx_module.shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    snapshot = assert_mlx_asr_ready(model.absolute())

    assert snapshot.path == model.absolute()


def test_provider_uses_fixed_accuracy_decode_and_maps_timestamps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model_dir(tmp_path / "model-root")
    ffmpeg_calls = _install_fake_ffmpeg(monkeypatch)
    observed: dict[str, Any] = {}

    def transcribe(path: str, **kwargs: object) -> dict[str, object]:
        assert Path(path).read_bytes().startswith(b"RIFF")
        observed.update(kwargs)
        return {
            "text": "你好世界",
            "language": "zh",
            "segments": [
                {
                    "start": 0.125,
                    "end": 1.875,
                    "text": "你好世界",
                    "words": [
                        {"start": 0.125, "end": 0.9, "word": "你好"},
                        {"start": 0.95, "end": 1.875, "word": "世界"},
                    ],
                }
            ],
        }

    provider = MLXASRProvider(
        model_path=model.absolute(),
        transcribe_fn=transcribe,
        runtime_version=MLX_WHISPER_VERSION,
        ffmpeg_path="/usr/bin/ffmpeg",
    )
    result = provider.transcribe(_chunk(tmp_path), vocabulary_prompt="专有词: LiveClip")

    assert provider.provider_name == "mlx"
    assert provider.model_name == MLX_ASR_MODEL
    assert provider.contract_version == provider.model_snapshot.contract_version
    assert len(ffmpeg_calls) == 1
    assert ffmpeg_calls[0][0] == "/usr/bin/ffmpeg"
    assert ffmpeg_calls[0][ffmpeg_calls[0].index("-i") + 1].startswith("/dev/fd/")
    assert observed == {
        "path_or_hf_repo": str(model.absolute()),
        "verbose": None,
        "compression_ratio_threshold": 2.4,
        "logprob_threshold": -1.0,
        "no_speech_threshold": 0.6,
        "initial_prompt": None,
        "condition_on_previous_text": False,
        "fp16": True,
        "language": "zh",
        "task": "transcribe",
        "temperature": 0.0,
        "word_timestamps": True,
    }
    assert result.word_timing_status is WordTimingStatus.AVAILABLE
    assert [(value.start_ms, value.end_ms, value.text) for value in result.segments] == [
        (125, 1_875, "你好世界")
    ]
    assert [
        (value.start_ms, value.end_ms, value.text) for value in result.segments[0].words or ()
    ] == [(125, 900, "你好"), (950, 1_875, "世界")]
    assert result.call_record is not None
    assert result.call_record.provider == "mlx"
    assert result.call_record.status is ProviderCallStatus.SUCCEEDED
    assert result.call_record.audio_seconds == 2.0
    assert result.call_record.usage_json is not None
    assert result.call_record.usage_json["model_snapshot_sha256"] == (
        provider.model_snapshot.sha256
    )
    assert result.call_record.usage_json["rejected_decode_segments"] == 0


def test_failed_decode_segments_are_dropped_without_losing_valid_neighbors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model_dir(tmp_path / "model-root")
    _install_fake_ffmpeg(monkeypatch)

    def transcribe(_path: str, **_kwargs: object) -> dict[str, object]:
        return {
            "text": "直播直播真实内容",
            "segments": [
                {
                    "start": 0.0,
                    "end": 1.0,
                    "text": "直播、直播、直播、直播",
                    "compression_ratio": 26.0,
                    "avg_logprob": -0.1,
                },
                {
                    "start": 1.0,
                    "end": 1.9,
                    "text": "真实内容",
                    "compression_ratio": 1.1,
                    "avg_logprob": -0.2,
                },
            ],
        }

    result = MLXASRProvider(
        model_path=model.absolute(),
        transcribe_fn=transcribe,
        runtime_version=MLX_WHISPER_VERSION,
        ffmpeg_path="/usr/bin/ffmpeg",
    ).transcribe(_chunk(tmp_path), vocabulary_prompt="直播")

    assert [segment.text for segment in result.segments] == ["真实内容"]
    assert result.call_record is not None
    assert result.call_record.usage_json is not None
    assert result.call_record.usage_json["rejected_decode_segments"] == 1


def test_optional_word_mismatch_downgrades_without_losing_segments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model_dir(tmp_path / "model-root")
    _install_fake_ffmpeg(monkeypatch)

    def transcribe(_path: str, **_kwargs: object) -> dict[str, object]:
        return {
            "text": "你好世界",
            "segments": [
                {
                    "start": 0.1,
                    "end": 1.9,
                    "text": "你好世界",
                    "words": [{"start": 0.1, "end": 1.9, "word": "错误"}],
                }
            ],
        }

    result = MLXASRProvider(
        model_path=model.absolute(),
        transcribe_fn=transcribe,
        runtime_version=MLX_WHISPER_VERSION,
        ffmpeg_path="/usr/bin/ffmpeg",
    ).transcribe(_chunk(tmp_path))

    assert result.word_timing_status is WordTimingStatus.UNAVAILABLE
    assert result.segments[0].text == "你好世界"
    assert result.segments[0].words is None


def test_invalid_model_output_fails_with_bounded_local_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model_dir(tmp_path / "model-root")
    _install_fake_ffmpeg(monkeypatch)
    provider = MLXASRProvider(
        model_path=model.absolute(),
        transcribe_fn=lambda _path, **_kwargs: {"text": "有文本", "segments": []},
        runtime_version=MLX_WHISPER_VERSION,
        ffmpeg_path="/usr/bin/ffmpeg",
    )

    with pytest.raises(ProviderDeterministicError) as raised:
        provider.transcribe(_chunk(tmp_path))

    record = raised.value.call_record
    assert record.status is ProviderCallStatus.INVALID
    assert record.failure_code == "MLX_ASR_OUTPUT_INVALID"
    assert "有文本" not in repr(record)


def test_runtime_failure_is_bounded_and_does_not_expose_raw_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model_dir(tmp_path / "model-root")
    _install_fake_ffmpeg(monkeypatch)

    def fail(_path: str, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("private MLX runtime detail")

    provider = MLXASRProvider(
        model_path=model.absolute(),
        transcribe_fn=fail,
        runtime_version=MLX_WHISPER_VERSION,
        ffmpeg_path="/usr/bin/ffmpeg",
    )

    with pytest.raises(ProviderDeterministicError) as raised:
        provider.transcribe(_chunk(tmp_path))

    record = raised.value.call_record
    assert record.status is ProviderCallStatus.FAILED
    assert record.failure_code == "MLX_ASR_RUNTIME_FAILED"
    assert "private MLX runtime detail" not in repr(record)
