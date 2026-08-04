# ruff: noqa: RUF001
from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.domain.transcript import WordTimingStatus
from liveclip.providers.asr.base import (
    ASRChunkResult,
    AudioChunkLike,
    LocalASRSegment,
)
from liveclip.providers.telemetry import ProviderCancelled

MOCK_ASR_CONTRACT_VERSION = "mock-asr-contract-v1"


class MockScriptSegment(BaseModel):
    """A fixed Chinese script segment on the absolute source timeline."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    script_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def validate_interval(self) -> MockScriptSegment:
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("Mock script end must be greater than start")
        return self


DEFAULT_MOCK_SCRIPT: tuple[MockScriptSegment, ...] = (
    MockScriptSegment(
        script_id="mock_01",
        source_start_ms=0,
        source_end_ms=4_000,
        text="今天我们聊三个能立刻改善直播表达的方法。",
    ),
    MockScriptSegment(
        script_id="mock_02",
        source_start_ms=4_000,
        source_end_ms=8_000,
        text="第一个关键，是开场十秒先说清楚观众能得到什么。",
    ),
    MockScriptSegment(
        script_id="mock_03",
        source_start_ms=8_000,
        source_end_ms=12_000,
        text="很多人一上来先介绍自己，观众却还不知道为什么要留下。",
    ),
    MockScriptSegment(
        script_id="mock_04",
        source_start_ms=12_000,
        source_end_ms=16_000,
        text="第二个方法，是每讲完一个观点就给一个具体例子。",
    ),
    MockScriptSegment(
        script_id="mock_05",
        source_start_ms=16_000,
        source_end_ms=20_000,
        text="例子越具体，观众越容易把抽象建议变成自己的行动。",
    ),
    MockScriptSegment(
        script_id="mock_06",
        source_start_ms=20_000,
        source_end_ms=24_000,
        text="第三个方法，是结尾用一句话重新收住核心观点。",
    ),
    MockScriptSegment(
        script_id="mock_07",
        source_start_ms=24_000,
        source_end_ms=28_000,
        text="如果只能记住一句话，就记住先给价值、再讲过程。",
    ),
    MockScriptSegment(
        script_id="mock_08",
        source_start_ms=28_000,
        source_end_ms=32_000,
        text="把这三个步骤练熟，直播内容就会更紧凑也更完整。",
    ),
)


class MockASRProvider:
    """Deterministic local ASR substitute; it never reads audio or calls a network."""

    def __init__(
        self,
        script: Sequence[MockScriptSegment] = DEFAULT_MOCK_SCRIPT,
        *,
        model_name: str = "mock-asr-v1",
    ) -> None:
        self._script = tuple(
            sorted(script, key=lambda item: (item.source_start_ms, item.script_id))
        )
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def contract_version(self) -> str:
        return MOCK_ASR_CONTRACT_VERSION

    def transcribe(
        self,
        chunk: AudioChunkLike,
        *,
        language: str = "zh",
        vocabulary_prompt: str | None = None,
        cancel_requested: Callable[[], bool] = lambda: False,
    ) -> ASRChunkResult:
        del vocabulary_prompt  # Mock content is fixed; transcript text never controls behavior.
        if cancel_requested():
            raise ProviderCancelled()
        if chunk.source_start_ms < 0 or chunk.source_end_ms <= chunk.source_start_ms:
            raise ValueError("audio chunk has an invalid absolute interval")

        local_segments: list[LocalASRSegment] = []
        for item in self._script:
            absolute_start = max(item.source_start_ms, chunk.source_start_ms)
            absolute_end = min(item.source_end_ms, chunk.source_end_ms)
            if absolute_end <= absolute_start:
                continue
            digest = hashlib.sha256(f"{item.script_id}\0{chunk.chunk_id}".encode()).hexdigest()[:16]
            local_segments.append(
                LocalASRSegment(
                    segment_id=f"mock_{digest}",
                    start_ms=absolute_start - chunk.source_start_ms,
                    end_ms=absolute_end - chunk.source_start_ms,
                    text=item.text,
                    words=None,
                )
            )

        return ASRChunkResult(
            chunk_id=chunk.chunk_id,
            chunk_duration_ms=chunk.source_end_ms - chunk.source_start_ms,
            language=language,
            provider=self.provider_name,
            model=self.model_name,
            word_timing_status=WordTimingStatus.UNAVAILABLE,
            segments=tuple(local_segments),
            request_id=None,
        )
