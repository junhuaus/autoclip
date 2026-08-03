from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

MILLISECONDS_PER_SECOND = 1_000


def seconds_to_ms(value: str | int | float | Decimal) -> int:
    decimal_value = Decimal(str(value))
    milliseconds = (decimal_value * MILLISECONDS_PER_SECOND).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(milliseconds)


def ms_to_ffmpeg(value_ms: int) -> str:
    if value_ms < 0:
        raise ValueError("media time cannot be negative")
    seconds, milliseconds = divmod(value_ms, MILLISECONDS_PER_SECOND)
    return f"{seconds}.{milliseconds:03d}"


def ms_to_srt(value_ms: int) -> str:
    if value_ms < 0:
        raise ValueError("SRT time cannot be negative")
    hours, remainder = divmod(value_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
