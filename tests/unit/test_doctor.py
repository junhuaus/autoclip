from liveclip.cli.doctor import parse_ffmpeg_filters


def test_parse_ffmpeg_filters_requires_exact_filter_rows() -> None:
    output = """
 Filters:
  .. loudnorm          A->A       EBU R128 loudness normalization
  .. silencedetect     A->A       Detect silence.
  T. overlay           VV->V      Overlay a video source.
  .. notdrawtext       V->V       Description mentions drawtext only.
 """

    names = parse_ffmpeg_filters(output)

    assert {"loudnorm", "silencedetect", "overlay"}.issubset(names)
    assert "drawtext" not in names
