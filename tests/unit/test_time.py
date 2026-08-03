from decimal import Decimal

import pytest

from liveclip.domain.time import ms_to_ffmpeg, ms_to_srt, seconds_to_ms


def test_time_conversions_use_integer_milliseconds() -> None:
    assert seconds_to_ms("125.5004") == 125_500
    assert seconds_to_ms(Decimal("183.2005")) == 183_201
    assert ms_to_ffmpeg(125_500) == "125.500"
    assert ms_to_srt(3_723_004) == "01:02:03,004"


def test_negative_adapter_time_is_rejected() -> None:
    with pytest.raises(ValueError):
        ms_to_ffmpeg(-1)
